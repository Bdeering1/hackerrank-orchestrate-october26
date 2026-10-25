from __future__ import annotations

import contextlib
import hashlib
import json
import os
import random
import secrets
import shutil
import subprocess
import sys
import time
import typing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import ghost_audit
from evaluation.score import (
    METRICS,
    Ratio,
    case_scores,
    pooled_composite,
    pooled_ratio,
    rows_by_case,
)
from evaluation.usage import usage_summary
from evaluation.validate import VALID_STATUSES, data_rows

if typing.TYPE_CHECKING:
    from evaluation.score import CaseScore

RUNS_DIR = Path(__file__).resolve().parents[2] / "eval_runs"
HOLDOUT_DIRNAME = "holdout"
SCORE_PATH = Path(__file__).with_name("score.py")
BASELINE_FILENAME = "baseline.txt"
OUTPUT_FILENAME = "output.csv"
USAGE_FILENAME = "usage.json"
FULL_OUTPUT_FILENAME = "full_output.csv"
FULL_USAGE_FILENAME = "full_usage.json"
SCORES_FILENAME = "scores.md"
RUN_FILENAME = "run.json"
DIFF_FILENAME = "diff.md"
LOCK_FILENAME = ".runs.lock"
LOCK_POLL_SECONDS = 0.1
BASELINE_REFERENCE = "baseline"
HOLDOUT_REFERENCE = "previous holdout run"

NOISE_FLOOR = 0.0
# Most changed full-set cases an unchanged agent shows between runs.
FULL_SET_NOISE_CASES = 0
TIE_COST_FRACTION = 0.2
BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 0
INTERVAL_PERCENTILES = (0.025, 0.975)
YES_ANSWERS = ("y", "yes")
STATUSES = tuple(sorted(VALID_STATUSES))

Outcome = typing.Literal["promoted", "not_promoted", "tie"]


class FullSetPaths(typing.NamedTuple):
    output_path: Path
    usage_path: Path


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
    scoring_sha256: str
    promotion: Promotion


class HoldoutRunRecord(typing.TypedDict):
    """Contents of a saved holdout run's run.json."""

    run_id: str
    created_at: str
    agent_version: AgentVersion
    scoring_sha256: str
    previous_run_id: str | None


class PromotionRefusedError(Exception):
    """Raised when a run cannot be promoted."""


@dataclass(frozen=True, kw_only=True)
class RunFiles:
    """The validated predictions, usage and rendered scores of a run, and the labels they used."""

    output_path: Path
    usage_path: Path
    labels_path: Path
    scores_markdown: str
    full_set_paths: FullSetPaths | None = None

    def copy_into(self, run_dir: Path) -> None:
        shutil.copyfile(self.output_path, run_dir / OUTPUT_FILENAME)
        shutil.copyfile(self.usage_path, run_dir / USAGE_FILENAME)
        if self.full_set_paths is not None:
            shutil.copyfile(self.full_set_paths.output_path, run_dir / FULL_OUTPUT_FILENAME)
            shutil.copyfile(self.full_set_paths.usage_path, run_dir / FULL_USAGE_FILENAME)
        (run_dir / SCORES_FILENAME).write_text(self.scores_markdown, encoding="utf-8")


@dataclass(frozen=True)
class CaseChange:
    """A case whose composite changed between two runs.

    The pooled effect is how much the pooled composite moves when only this case changes, which
    can disagree with the per-case change because pooling weights cases by their step counts.
    """

    before: CaseScore
    after: CaseScore
    pooled_effect: float


@dataclass(frozen=True)
class FullSetCaseDisagreement:
    """A full-set case with unmatched steps between the baseline and run."""

    case_id: str
    baseline_status: str
    run_status: str | None
    unmatched_step_count: int


@dataclass(frozen=True)
class FullSetComparison:
    """Agreement, transition and cost details for two full-set outputs."""

    case_count: int
    status_transitions: dict[str, dict[str, int]]
    changed_case_count: int
    pooled_step_f1: float
    top_step_disagreements: list[FullSetCaseDisagreement]
    baseline_cost_per_request_usd: float
    run_cost_per_request_usd: float


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
    full_set: FullSetComparison | None
    has_baseline_full_set: bool
    has_run_full_set: bool

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
        changes = [
            CaseChange(before, after, self._pooled_effect(index))
            for index, (before, after) in enumerate(
                zip(self.baseline_scores, self.run_scores, strict=True)
            )
            if is_change(before.composite, after.composite)
        ]
        return sorted(changes, key=lambda change: -abs(change.pooled_effect))

    def _pooled_effect(self, index: int) -> float:
        changed_scores = [*self.baseline_scores]
        changed_scores[index] = self.run_scores[index]
        return pooled_composite(changed_scores) - pooled_composite(self.baseline_scores)


def record_run(files: RunFiles) -> str:
    """Save a validated run, diff it against the baseline and promote it if it earns it.

    Writes the diff and promotion outcome to stdout and returns the run ID.
    """
    now = datetime.now(UTC)
    run_id = _new_run_id(now)
    agent_version = _agent_version()

    # The lock keeps a concurrent run from moving the baseline between the comparison and the
    # promotion, which would leave a baseline that was never compared against this run.
    with _runs_lock():
        baseline_run_id = _baseline_run_id()
        run_dir = RUNS_DIR / run_id
        outcome, comparison = _save_into_new_dir(
            run_dir,
            lambda: _save_run(run_id, baseline_run_id, files),
        )
        _write_run_record(
            run_dir,
            {
                "run_id": run_id,
                "created_at": now.isoformat(),
                "agent_version": agent_version,
                "scoring_sha256": _scoring_sha256(files.labels_path),
                "promotion": {"outcome": outcome, "baseline_run_id": baseline_run_id},
            },
        )
        if outcome == "promoted":
            _write_baseline(run_id)
    if outcome == "tie" and _is_interactive() and _confirms_promotion(comparison):
        outcome = "promoted"
        promote_run(run_id)
    sys.stdout.write(f"Run {run_id}: {outcome}\n")
    return run_id


def record_holdout_run(files: RunFiles) -> str:
    """Save a validated holdout run and diff it against the previous holdout run.

    Holdout runs are never promoted. Writes the diff to stdout and returns the run ID.
    """
    now = datetime.now(UTC)
    run_id = _new_run_id(now)
    agent_version = _agent_version()
    holdout_dir = RUNS_DIR / HOLDOUT_DIRNAME

    # The lock keeps concurrent holdout runs from diffing against the same previous run.
    with _runs_lock():
        previous_record = _latest_holdout_record(holdout_dir)
        run_dir = holdout_dir / run_id
        _save_into_new_dir(
            run_dir,
            lambda: _save_holdout_run(run_dir, previous_record, files),
        )
        _write_run_record(
            run_dir,
            {
                "run_id": run_id,
                "created_at": now.isoformat(),
                "agent_version": agent_version,
                "scoring_sha256": _scoring_sha256(files.labels_path),
                "previous_run_id": previous_record["run_id"] if previous_record else None,
            },
        )
    sys.stdout.write(f"Holdout run {run_id}: saved\n")
    return run_id


def _new_run_id(now: datetime) -> str:
    return f"{now.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(4)}"


def _save_into_new_dir[T](run_dir: Path, save: typing.Callable[[], T]) -> T:
    """Create run_dir, fill it with save and remove it again if saving fails."""
    run_dir.mkdir(parents=True)
    try:
        return save()
    except Exception:
        shutil.rmtree(run_dir)
        raise


def _save_holdout_run(
    run_dir: Path,
    previous_record: HoldoutRunRecord | None,
    files: RunFiles,
) -> None:
    files.copy_into(run_dir)
    if previous_record is None:
        sys.stdout.write("\nNo previous holdout run to compare with.\n")
        return
    comparison = compare_runs(
        previous_record["run_id"], run_dir.name, files.labels_path, runs_dir=run_dir.parent
    )
    diff_markdown = _render_diff(comparison, HOLDOUT_REFERENCE) + _scoring_warning(
        previous_record["scoring_sha256"], files.labels_path, HOLDOUT_REFERENCE
    )
    (run_dir / DIFF_FILENAME).write_text(diff_markdown, encoding="utf-8")
    sys.stdout.write(f"\n{diff_markdown}")


def _latest_holdout_record(holdout_dir: Path) -> HoldoutRunRecord | None:
    records = [
        typing.cast("HoldoutRunRecord", json.loads(run_path.read_text(encoding="utf-8")))
        for run_path in holdout_dir.glob(f"*/{RUN_FILENAME}")
    ]
    return max(records, key=lambda record: record["created_at"], default=None)


def _scoring_warning(recorded_scoring_sha256: str, labels_path: Path, reference_name: str) -> str:
    if recorded_scoring_sha256 == _scoring_sha256(labels_path):
        return ""
    return (
        f"\nWarning: the scoring code or labels changed since the {reference_name} was "
        f"recorded, so another saved run may now score higher than the {reference_name}.\n"
    )


def _save_run(
    run_id: str, baseline_run_id: str | None, files: RunFiles
) -> tuple[Outcome, RunComparison | None]:
    run_dir = RUNS_DIR / run_id
    files.copy_into(run_dir)

    if baseline_run_id is None:
        sys.stdout.write("\nNo baseline: run promoted as the first baseline.\n")
        return "promoted", None
    comparison = compare_runs(baseline_run_id, run_id, files.labels_path)
    diff_markdown = _render_diff(comparison, BASELINE_REFERENCE) + _scoring_warning(
        _read_run_record(RUNS_DIR / baseline_run_id)["scoring_sha256"],
        files.labels_path,
        BASELINE_REFERENCE,
    )
    (run_dir / DIFF_FILENAME).write_text(diff_markdown, encoding="utf-8")
    sys.stdout.write(f"\n{diff_markdown}")
    return _outcome(comparison), comparison


def promote_run(run_id: str) -> None:
    """Promote a recorded tied run to baseline.

    Raises PromotionRefusedError for any other run, including every holdout run.
    """
    if Path(run_id).name != run_id:
        raise PromotionRefusedError(f"unknown run: {run_id}")
    if (RUNS_DIR / HOLDOUT_DIRNAME / run_id / RUN_FILENAME).is_file():
        raise PromotionRefusedError(f"run {run_id} is a holdout run, which is never promoted")
    run_dir = RUNS_DIR / run_id
    if not (run_dir / RUN_FILENAME).is_file():
        raise PromotionRefusedError(f"unknown run: {run_id}")
    with _runs_lock():
        record = _read_run_record(run_dir)
        promotion = record["promotion"]
        if promotion["outcome"] != "tie":
            raise PromotionRefusedError(f"run {run_id} is {promotion['outcome']}, not a tie")
        if promotion["baseline_run_id"] != _baseline_run_id():
            raise PromotionRefusedError(
                f"run {run_id} tied against a baseline that is no longer current"
            )
        record["promotion"]["outcome"] = "promoted"
        _write_run_record(run_dir, record)
        _write_baseline(run_id)


@contextlib.contextmanager
def _runs_lock() -> typing.Generator[None]:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = RUNS_DIR / LOCK_FILENAME
    is_waiting_reported = False
    while True:
        try:
            lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            if not is_waiting_reported:
                sys.stderr.write(f"Waiting for {lock_path}; delete it if no other run is active.\n")
                is_waiting_reported = True
            time.sleep(LOCK_POLL_SECONDS)
    os.close(lock_fd)
    try:
        yield
    finally:
        lock_path.unlink()


def compare_runs(
    baseline_run_id: str, run_id: str, labels_path: Path, runs_dir: Path | None = None
) -> RunComparison:
    """Re-score two saved runs over the cases they share and compare them.

    Runs are read from runs_dir, which defaults to the directory of promotable runs.
    """
    runs_dir = runs_dir or RUNS_DIR
    baseline_output_path = runs_dir / baseline_run_id / OUTPUT_FILENAME
    run_output_path = runs_dir / run_id / OUTPUT_FILENAME
    baseline_case_ids = _output_case_ids(baseline_output_path)
    run_case_ids = _output_case_ids(run_output_path)
    shared_case_ids = baseline_case_ids & run_case_ids
    baseline_scores = case_scores(baseline_output_path, labels_path)
    run_scores = case_scores(run_output_path, labels_path)
    baseline_scores = [score for score in baseline_scores if score.case_id in shared_case_ids]
    run_scores = [score for score in run_scores if score.case_id in shared_case_ids]
    has_baseline_full_set = (runs_dir / baseline_run_id / FULL_OUTPUT_FILENAME).is_file()
    has_run_full_set = (runs_dir / run_id / FULL_OUTPUT_FILENAME).is_file()
    return RunComparison(
        baseline_run_id,
        run_id,
        baseline_scores,
        run_scores,
        _cost_per_request_usd(runs_dir / baseline_run_id, len(baseline_case_ids)),
        _cost_per_request_usd(runs_dir / run_id, len(run_case_ids)),
        _bootstrap_interval(baseline_scores, run_scores),
        (
            _compare_full_sets(runs_dir / baseline_run_id, runs_dir / run_id)
            if has_baseline_full_set and has_run_full_set
            else None
        ),
        has_baseline_full_set,
        has_run_full_set,
    )


def _output_case_ids(output_path: Path) -> set[str]:
    return {row[0] for row in data_rows(output_path)}


def _compare_full_sets(baseline_run_dir: Path, run_dir: Path) -> FullSetComparison:
    baseline_output_path = baseline_run_dir / FULL_OUTPUT_FILENAME
    run_output_path = run_dir / FULL_OUTPUT_FILENAME
    baseline_rows = rows_by_case(baseline_output_path)
    run_rows = rows_by_case(run_output_path)
    full_scores = case_scores(run_output_path, baseline_output_path)
    status_transitions = {
        baseline_status: dict.fromkeys(STATUSES, 0) for baseline_status in STATUSES
    }
    changed_case_count = 0
    for case_id, (baseline_status, baseline_steps) in baseline_rows.items():
        run_status, run_steps = run_rows[case_id]
        status_transitions[baseline_status][run_status] += 1
        if baseline_status != run_status or baseline_steps != run_steps:
            changed_case_count += 1

    disagreements = [
        FullSetCaseDisagreement(
            score.case_id,
            score.expected_status,
            score.predicted_status,
            score.step_f1.denominator - score.step_f1.numerator,
        )
        for score in full_scores
        if score.step_f1.denominator != score.step_f1.numerator
    ]
    return FullSetComparison(
        len(baseline_rows),
        status_transitions,
        changed_case_count,
        sum((score.step_f1 for score in full_scores), Ratio(0, 0)).value,
        sorted(disagreements, key=lambda disagreement: -disagreement.unmatched_step_count)[:10],
        _cost_per_request_usd(baseline_run_dir, len(baseline_rows), FULL_USAGE_FILENAME),
        _cost_per_request_usd(run_dir, len(run_rows), FULL_USAGE_FILENAME),
    )


def _outcome(comparison: RunComparison) -> Outcome:
    if not comparison.run_scores:
        return "not_promoted"
    if comparison.delta > NOISE_FLOOR:
        return "promoted"
    if comparison.delta < -NOISE_FLOOR:
        return "not_promoted"
    return _cheaper_run_outcome(comparison) or "tie"


def _cheaper_run_outcome(comparison: RunComparison) -> Outcome | None:
    full_set = comparison.full_set
    if full_set is None or full_set.changed_case_count > FULL_SET_NOISE_CASES:
        return None
    baseline_cost = full_set.baseline_cost_per_request_usd
    run_cost = full_set.run_cost_per_request_usd
    larger_cost = max(baseline_cost, run_cost)
    if larger_cost <= 0 or abs(baseline_cost - run_cost) < TIE_COST_FRACTION * larger_cost:
        return None
    if run_cost < baseline_cost and comparison.delta >= 0:
        return "promoted"
    if baseline_cost < run_cost and comparison.delta <= 0:
        return "not_promoted"
    return None


def _is_interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _confirms_promotion(comparison: RunComparison | None) -> bool:
    try:
        if comparison is not None and comparison.full_set is not None:
            sys.stdout.write(_full_set_summary(comparison.full_set) + "\n")
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


def _cost_per_request_usd(
    run_dir: Path, request_count: int, usage_filename: str = USAGE_FILENAME
) -> float:
    summary = usage_summary(run_dir / usage_filename, request_count)
    return summary.cost_per_request_usd(summary.overall)


def _render_diff(comparison: RunComparison, reference_name: str) -> str:
    lines = [
        f"## Diff against {reference_name} {comparison.baseline_run_id}",
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
        f"| Metric | {reference_name.capitalize()} | Run | Change |",
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
    lines.extend(_render_full_set(comparison))
    return "\n".join(lines) + "\n"


def _render_changes(title: str, changes: list[CaseChange]) -> list[str]:
    lines = ["", f"### {title} ({len(changes)})"]
    if not changes:
        return lines
    lines.extend(
        [
            "",
            "| Case ID | Composite | Pooled effect | Status |",
            "| --- | --- | ---: | --- |",
        ]
    )
    lines.extend(
        f"| {change.before.case_id} | {change.before.composite:.1f}% -> "
        f"{change.after.composite:.1f}% | {change.pooled_effect:+.2f} | "
        f"{change.before.predicted_status} -> "
        f"{change.after.predicted_status} (expected {change.after.expected_status}) |"
        for change in changes
    )
    return lines


def _render_full_set(comparison: RunComparison) -> list[str]:
    full_set = comparison.full_set
    if full_set is None:
        if comparison.has_baseline_full_set == comparison.has_run_full_set:
            return []
        missing_side = "run" if comparison.has_baseline_full_set else "baseline"
        return ["", f"Full set: {missing_side} lacks full-set output."]

    lines = [
        "",
        "### Full set",
        "",
        _full_set_summary(full_set),
        "",
        "Status transitions (baseline rows, run columns):",
        "| Baseline status | " + " | ".join(STATUSES) + " |",
        "| --- | " + " | ".join("---:" for _ in STATUSES) + " |",
    ]
    lines.extend(
        "| "
        + baseline_status
        + " | "
        + " | ".join(
            str(full_set.status_transitions[baseline_status][run_status]) for run_status in STATUSES
        )
        + " |"
        for baseline_status in STATUSES
    )
    lines.extend(
        [
            "",
            f"#### Top step disagreements ({len(full_set.top_step_disagreements)})",
        ]
    )
    if not full_set.top_step_disagreements:
        return lines
    lines.extend(
        [
            "",
            "| Case ID | Unmatched steps | Baseline status | Run status |",
            "| --- | ---: | --- | --- |",
        ]
    )
    lines.extend(
        f"| {disagreement.case_id} | {disagreement.unmatched_step_count} | "
        f"{disagreement.baseline_status} | {disagreement.run_status or ''} |"
        for disagreement in full_set.top_step_disagreements
    )
    return lines


def _full_set_summary(full_set: FullSetComparison) -> str:
    return (
        f"Full set: {full_set.changed_case_count}/{full_set.case_count} changed, pooled step F1 "
        f"{full_set.pooled_step_f1:.1%}, cost per request "
        f"${full_set.baseline_cost_per_request_usd:.6f} -> "
        f"${full_set.run_cost_per_request_usd:.6f}"
    )


def _baseline_run_id() -> str | None:
    baseline_path = RUNS_DIR / BASELINE_FILENAME
    if not baseline_path.is_file():
        return None
    return baseline_path.read_text(encoding="utf-8").strip()


def _write_baseline(run_id: str) -> None:
    (RUNS_DIR / BASELINE_FILENAME).write_text(f"{run_id}\n", encoding="utf-8")


def _read_run_record(run_dir: Path) -> RunRecord:
    run_text = (run_dir / RUN_FILENAME).read_text(encoding="utf-8")
    return typing.cast("RunRecord", json.loads(run_text))


def _write_run_record(run_dir: Path, record: RunRecord | HoldoutRunRecord) -> None:
    (run_dir / RUN_FILENAME).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


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


def _scoring_sha256(labels_path: Path) -> str:
    digest = hashlib.sha256()
    for path in (SCORE_PATH, labels_path):
        digest.update(path.read_bytes())
    return digest.hexdigest()


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
