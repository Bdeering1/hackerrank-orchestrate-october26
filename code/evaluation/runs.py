from __future__ import annotations

import hashlib
import json
import random
import secrets
import shutil
import subprocess
import sys
import typing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import ghost_audit
from evaluation.score import METRICS, case_scores, pooled_composite, pooled_ratio
from evaluation.usage import usage_summary
from evaluation.validate import data_rows

if typing.TYPE_CHECKING:
    from evaluation.score import CaseScore

RUNS_DIR = Path(__file__).resolve().parents[2] / "eval_runs"
BASELINE_FILENAME = "baseline.txt"
OUTPUT_FILENAME = "output.csv"
USAGE_FILENAME = "usage.json"
SCORES_FILENAME = "scores.md"
RUN_FILENAME = "run.json"
DIFF_FILENAME = "diff.md"

NOISE_FLOOR = 0.0
TIE_COST_FRACTION = 0.2
BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 0
INTERVAL_PERCENTILES = (0.025, 0.975)
YES_ANSWERS = ("y", "yes")

Outcome = typing.Literal["promoted", "not_promoted", "tie"]


class AgentVersion(typing.TypedDict):
    """Identifies the agent code a run was produced by."""

    commit: str | None
    dirty: bool | None
    source_sha256: str


class Promotion(typing.TypedDict):
    """How a run fared against the baseline it was compared with."""

    outcome: Outcome
    baseline_run_id: str | None


class RunRecord(typing.TypedDict):
    """Contents of a saved run's run.json."""

    run_id: str
    created_at: str
    agent_version: AgentVersion
    promotion: Promotion


class PromotionRefusedError(Exception):
    """Raised when a run cannot be promoted."""


@dataclass(frozen=True)
class CaseChange:
    """A case whose composite changed between two runs."""

    before: CaseScore
    after: CaseScore


@dataclass(frozen=True)
class RunComparison:
    """Scores and costs of a run and its baseline over their shared cases."""

    baseline_run_id: str
    run_id: str
    baseline_scores: list[CaseScore]
    run_scores: list[CaseScore]
    baseline_cost_per_request_usd: float
    run_cost_per_request_usd: float
    interval: tuple[float, float]

    @property
    def delta(self) -> float:
        """Run composite minus baseline composite over the shared cases."""
        return pooled_composite(self.run_scores) - pooled_composite(self.baseline_scores)

    @property
    def fixed(self) -> list[CaseChange]:
        """Cases whose composite rose."""
        return self._changes(lambda before, after: after > before)

    @property
    def regressed(self) -> list[CaseChange]:
        """Cases whose composite fell."""
        return self._changes(lambda before, after: after < before)

    def _changes(self, is_change: typing.Callable[[float, float], bool]) -> list[CaseChange]:
        return [
            CaseChange(before, after)
            for before, after in zip(self.baseline_scores, self.run_scores, strict=True)
            if is_change(before.composite, after.composite)
        ]


def record_run(output_path: Path, usage_path: Path, labels_path: Path, scores_markdown: str) -> str:
    """Save a validated run, diff it against the baseline and promote it if it earns it.

    Writes the diff and promotion outcome to stdout and returns the run ID.
    """
    now = datetime.now(UTC)
    run_id = f"{now.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(4)}"
    baseline_run_id = _baseline_run_id()
    agent_version = _agent_version()

    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True)
    try:
        outcome = _save_run(
            run_id, baseline_run_id, output_path, usage_path, labels_path, scores_markdown
        )
    except Exception:
        shutil.rmtree(run_dir)
        raise
    _write_run_record(
        run_id,
        {
            "run_id": run_id,
            "created_at": now.isoformat(),
            "agent_version": agent_version,
            "promotion": {"outcome": outcome, "baseline_run_id": baseline_run_id},
        },
    )
    if outcome == "promoted":
        _write_baseline(run_id)
    if outcome == "tie" and _is_interactive() and _confirms_promotion():
        outcome = "promoted"
        promote_run(run_id)
    sys.stdout.write(f"Run {run_id}: {outcome}\n")
    return run_id


def _save_run(
    run_id: str,
    baseline_run_id: str | None,
    output_path: Path,
    usage_path: Path,
    labels_path: Path,
    scores_markdown: str,
) -> Outcome:
    run_dir = RUNS_DIR / run_id
    shutil.copyfile(output_path, run_dir / OUTPUT_FILENAME)
    shutil.copyfile(usage_path, run_dir / USAGE_FILENAME)
    (run_dir / SCORES_FILENAME).write_text(scores_markdown, encoding="utf-8")

    if baseline_run_id is None:
        sys.stdout.write("\nNo baseline: run promoted as the first baseline.\n")
        return "promoted"
    comparison = compare_runs(baseline_run_id, run_id, labels_path)
    diff_markdown = _render_diff(comparison)
    (run_dir / DIFF_FILENAME).write_text(diff_markdown, encoding="utf-8")
    sys.stdout.write(f"\n{diff_markdown}")
    return _outcome(comparison)


def promote_run(run_id: str) -> None:
    """Promote a recorded tied run to baseline.

    Raises PromotionRefusedError for any other run.
    """
    if Path(run_id).name != run_id or not (RUNS_DIR / run_id / RUN_FILENAME).is_file():
        raise PromotionRefusedError(f"unknown run: {run_id}")
    record = _read_run_record(run_id)
    promotion = record["promotion"]
    if promotion["outcome"] != "tie":
        raise PromotionRefusedError(f"run {run_id} is {promotion['outcome']}, not a tie")
    if promotion["baseline_run_id"] != _baseline_run_id():
        raise PromotionRefusedError(
            f"run {run_id} tied against a baseline that is no longer current"
        )
    record["promotion"]["outcome"] = "promoted"
    _write_run_record(run_id, record)
    _write_baseline(run_id)


def compare_runs(baseline_run_id: str, run_id: str, labels_path: Path) -> RunComparison:
    """Re-score two saved runs over the cases they share and compare them."""
    baseline_output_path = RUNS_DIR / baseline_run_id / OUTPUT_FILENAME
    run_output_path = RUNS_DIR / run_id / OUTPUT_FILENAME
    baseline_case_ids = _output_case_ids(baseline_output_path)
    run_case_ids = _output_case_ids(run_output_path)
    shared_case_ids = baseline_case_ids & run_case_ids
    baseline_scores = case_scores(baseline_output_path, labels_path)
    run_scores = case_scores(run_output_path, labels_path)
    baseline_scores = [score for score in baseline_scores if score.case_id in shared_case_ids]
    run_scores = [score for score in run_scores if score.case_id in shared_case_ids]
    return RunComparison(
        baseline_run_id,
        run_id,
        baseline_scores,
        run_scores,
        _cost_per_request_usd(baseline_run_id, len(baseline_case_ids)),
        _cost_per_request_usd(run_id, len(run_case_ids)),
        _bootstrap_interval(baseline_scores, run_scores),
    )


def _output_case_ids(output_path: Path) -> set[str]:
    return {row[0] for row in data_rows(output_path)}


def _outcome(comparison: RunComparison) -> Outcome:
    if not comparison.run_scores:
        return "not_promoted"
    if comparison.delta > NOISE_FLOOR:
        return "promoted"
    if comparison.delta < -NOISE_FLOOR:
        return "not_promoted"
    return _cheaper_run_outcome(comparison) or "tie"


def _cheaper_run_outcome(comparison: RunComparison) -> Outcome | None:
    baseline_cost = comparison.baseline_cost_per_request_usd
    run_cost = comparison.run_cost_per_request_usd
    larger_cost = max(baseline_cost, run_cost)
    if larger_cost <= 0 or abs(baseline_cost - run_cost) < TIE_COST_FRACTION * larger_cost:
        return None
    return "promoted" if run_cost < baseline_cost else "not_promoted"


def _is_interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _confirms_promotion() -> bool:
    try:
        return input("Promote? [y/N] ").strip().lower() in YES_ANSWERS
    except EOFError:
        return False


def _bootstrap_interval(
    baseline_scores: list[CaseScore], run_scores: list[CaseScore]
) -> tuple[float, float]:
    generator = random.Random(BOOTSTRAP_SEED)  # noqa: S311
    case_count = len(baseline_scores)
    deltas: list[float] = []
    for _ in range(BOOTSTRAP_RESAMPLES):
        indices = generator.choices(range(case_count), k=case_count)
        deltas.append(
            pooled_composite([run_scores[index] for index in indices])
            - pooled_composite([baseline_scores[index] for index in indices])
        )
    deltas.sort()
    lower, upper = (round(percentile * (len(deltas) - 1)) for percentile in INTERVAL_PERCENTILES)
    return deltas[lower], deltas[upper]


def _cost_per_request_usd(run_id: str, request_count: int) -> float:
    summary = usage_summary(RUNS_DIR / run_id / USAGE_FILENAME, request_count)
    return summary.cost_per_request_usd(summary.overall)


def _render_diff(comparison: RunComparison) -> str:
    lines = [
        f"## Diff against baseline {comparison.baseline_run_id}",
        "",
        f"Shared cases: {len(comparison.run_scores)}",
        (
            f"Composite: {pooled_composite(comparison.baseline_scores):.1f}% -> "
            f"{pooled_composite(comparison.run_scores):.1f}% ({comparison.delta:+.1f})"
        ),
        (
            f"95% paired bootstrap interval of the change: [{comparison.interval[0]:+.1f}, "
            f"{comparison.interval[1]:+.1f}] ({BOOTSTRAP_RESAMPLES} resamples, "
            f"seed {BOOTSTRAP_SEED})"
        ),
        (
            f"Cost per request: ${comparison.baseline_cost_per_request_usd:.6f} -> "
            f"${comparison.run_cost_per_request_usd:.6f}"
        ),
        "",
        "| Metric | Baseline | Run | Change |",
        "| --- | ---: | ---: | ---: |",
    ]
    for metric in METRICS:
        before = pooled_ratio(metric, comparison.baseline_scores).value
        after = pooled_ratio(metric, comparison.run_scores).value
        lines.append(
            f"| {metric.label} | {before:.1%} | {after:.1%} | {100 * (after - before):+.1f} |"
        )
    lines.extend(_render_changes("Fixed", comparison.fixed))
    lines.extend(_render_changes("Regressed", comparison.regressed))
    return "\n".join(lines) + "\n"


def _render_changes(title: str, changes: list[CaseChange]) -> list[str]:
    lines = ["", f"### {title} ({len(changes)})"]
    if not changes:
        return lines
    lines.extend(
        [
            "",
            "| Case ID | Composite | Status |",
            "| --- | --- | --- |",
        ]
    )
    lines.extend(
        f"| {change.before.case_id} | {change.before.composite:.1f}% -> "
        f"{change.after.composite:.1f}% | {change.before.predicted_status} -> "
        f"{change.after.predicted_status} (expected {change.after.expected_status}) |"
        for change in changes
    )
    return lines


def _baseline_run_id() -> str | None:
    baseline_path = RUNS_DIR / BASELINE_FILENAME
    if not baseline_path.is_file():
        return None
    return baseline_path.read_text(encoding="utf-8").strip()


def _write_baseline(run_id: str) -> None:
    (RUNS_DIR / BASELINE_FILENAME).write_text(f"{run_id}\n", encoding="utf-8")


def _read_run_record(run_id: str) -> RunRecord:
    run_text = (RUNS_DIR / run_id / RUN_FILENAME).read_text(encoding="utf-8")
    return typing.cast("RunRecord", json.loads(run_text))


def _write_run_record(run_id: str, record: RunRecord) -> None:
    (RUNS_DIR / run_id / RUN_FILENAME).write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8"
    )


def _agent_version() -> AgentVersion:
    commit = _git_output("rev-parse", "HEAD")
    status = _git_output("status", "--porcelain", "--", str(_package_dir()))
    return {
        "commit": commit.strip() if commit is not None else None,
        "dirty": bool(status.strip()) if status is not None else None,
        "source_sha256": _source_sha256(),
    }


def _git_output(*arguments: str) -> str | None:
    git_path = shutil.which("git")
    if git_path is None:
        return None
    result = subprocess.run(  # noqa: S603
        [git_path, *arguments],
        cwd=Path(__file__).parent,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else None


def _package_dir() -> Path:
    return Path(ghost_audit.__file__).parent


def _source_sha256() -> str:
    package_dir = _package_dir()
    digest = hashlib.sha256()
    source_paths = (
        path
        for path in package_dir.rglob("*")
        if path.is_file() and "__pycache__" not in path.relative_to(package_dir).parts
    )
    for source_path in sorted(source_paths):
        digest.update(source_path.relative_to(package_dir).as_posix().encode())
        digest.update(source_path.read_bytes())
    return digest.hexdigest()
