import csv
import json
import threading
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

from evaluation import main as evaluation_main
from evaluation import runs
from evaluation.main import main, write_suite
from evaluation.runs import (
    FullSetPaths,
    PromotionRefusedError,
    compare_runs,
    promote_run,
    record_holdout_run,
    record_run,
)
from evaluation.validate import csv_rows

SAMPLE_OUTPUT_PATH = Path(__file__).resolve().parents[2] / "dataset" / "sample_output.csv"
DEGRADED_CASE_ID = "case_01"
NO_USAGE = {"models": []}
EXPENSIVE_USAGE = {
    "models": [
        {
            "provider": "anthropic",
            "model": "claude-sonnet-5.5",
            "calls": 1,
            "input_tokens": 1_000_000,
            "output_tokens": 0,
        }
    ]
}
SLIGHTLY_CHEAPER_USAGE = {"models": [{**EXPENSIVE_USAGE["models"][0], "input_tokens": 900_000}]}


def _recorder(
    tmp_path: Path, record_saved_run: Callable[[runs.RunFiles], str]
) -> Callable[..., str]:
    def record_rows(
        rows: list[list[str]],
        usage: Mapping[str, object] = NO_USAGE,
        full_rows: list[list[str]] | None = None,
        full_usage: Mapping[str, object] | None = None,
    ) -> str:
        output_path = tmp_path / "output.csv"
        usage_path = tmp_path / "usage.json"
        with output_path.open("w", encoding="utf-8", newline="") as output_file:
            csv.writer(output_file).writerows(rows)
        usage_path.write_text(json.dumps(usage), encoding="utf-8")
        full_set_paths = None
        if full_rows is not None:
            full_set_paths = FullSetPaths(
                tmp_path / "full_output.csv", tmp_path / "full_usage.json"
            )
            with full_set_paths.output_path.open(
                "w", encoding="utf-8", newline=""
            ) as full_output_file:
                csv.writer(full_output_file).writerows(full_rows)
            full_set_paths.usage_path.write_text(
                json.dumps(full_usage if full_usage is not None else usage), encoding="utf-8"
            )
        return record_saved_run(
            runs.RunFiles(
                output_path=output_path,
                usage_path=usage_path,
                labels_path=SAMPLE_OUTPUT_PATH,
                scores_markdown="scores",
                full_set_paths=full_set_paths,
            )
        )

    return record_rows


@pytest.fixture
def record(tmp_path: Path):
    return _recorder(tmp_path, record_run)


@pytest.fixture
def record_holdout(tmp_path: Path):
    return _recorder(tmp_path, record_holdout_run)


def _perfect_rows() -> list[list[str]]:
    return csv_rows(SAMPLE_OUTPUT_PATH)


def _degraded_rows() -> list[list[str]]:
    rows = _perfect_rows()
    row = next(row for row in rows[1:] if row[0] == DEGRADED_CASE_ID)
    row[1:] = ["NOT_APPLICABLE", "[]"]
    return rows


def _rows_with_steps_removed(removed_step_counts: Mapping[str, int]) -> list[list[str]]:
    rows = _perfect_rows()
    for case_id, removed_step_count in removed_step_counts.items():
        row = next(row for row in rows[1:] if row[0] == case_id)
        steps = json.loads(row[2])
        row[2] = json.dumps(steps[:-removed_step_count])
    return rows


def _rows_with_reformatted_steps() -> list[list[str]]:
    rows = _perfect_rows()
    row = next(row for row in rows[1:] if row[0] == DEGRADED_CASE_ID)
    steps = json.loads(row[2])
    row[2] = json.dumps([dict(reversed(step.items())) for step in steps], indent=2)
    return rows


def _outcome(run_id: str) -> str:
    run_record = json.loads((runs.RUNS_DIR / run_id / runs.RUN_FILENAME).read_text())
    return run_record["promotion"]["outcome"]


def _baseline() -> str:
    return (runs.RUNS_DIR / runs.BASELINE_FILENAME).read_text().strip()


def test_first_run_is_saved_and_promoted(record) -> None:
    run_id = record(_perfect_rows())

    run_dir = runs.RUNS_DIR / run_id
    saved = json.loads((run_dir / runs.RUN_FILENAME).read_text())
    assert saved["promotion"] == {"outcome": "promoted", "baseline_run_id": None}
    assert saved["agent_version"]["source_sha256"]
    assert _baseline() == run_id
    assert not (run_dir / runs.DIFF_FILENAME).exists()


@pytest.mark.parametrize(
    ("baseline_rows", "run_rows", "outcome", "is_baseline_replaced"),
    [
        pytest.param(_degraded_rows, _perfect_rows, "promoted", True, id="better"),
        pytest.param(_perfect_rows, _degraded_rows, "not_promoted", False, id="worse"),
        pytest.param(_perfect_rows, _perfect_rows, "tie", False, id="identical"),
    ],
)
def test_second_run_outcome(record, baseline_rows, run_rows, outcome, is_baseline_replaced) -> None:
    baseline_id = record(baseline_rows())
    run_id = record(run_rows())

    assert _outcome(run_id) == outcome
    assert _baseline() == (run_id if is_baseline_replaced else baseline_id)
    assert (runs.RUNS_DIR / run_id / runs.DIFF_FILENAME).is_file()


@pytest.mark.parametrize(
    ("baseline_usage", "run_usage", "outcome"),
    [
        pytest.param(EXPENSIVE_USAGE, NO_USAGE, "promoted", id="cheaper-run"),
        pytest.param(NO_USAGE, EXPENSIVE_USAGE, "not_promoted", id="costlier-run"),
        pytest.param(EXPENSIVE_USAGE, SLIGHTLY_CHEAPER_USAGE, "tie", id="small-cost-gap"),
    ],
)
def test_tie_is_decided_by_large_full_set_cost_difference(
    record, baseline_usage, run_usage, outcome
) -> None:
    record(_perfect_rows(), run_usage, _perfect_rows(), baseline_usage)

    assert _outcome(record(_perfect_rows(), baseline_usage, _perfect_rows(), run_usage)) == outcome


@pytest.mark.parametrize(
    ("run_full_rows", "changed_case_count"),
    [
        pytest.param(lambda: _rows_with_steps_removed({DEGRADED_CASE_ID: 1}), 1, id="step-removed"),
        pytest.param(_rows_with_reformatted_steps, 0, id="reformatted"),
    ],
)
def test_full_set_changed_cases_compare_parsed_steps(
    record, run_full_rows, changed_case_count
) -> None:
    baseline_id = record(_perfect_rows(), full_rows=_perfect_rows())
    run_id = record(_perfect_rows(), full_rows=run_full_rows())

    full_set = compare_runs(baseline_id, run_id, SAMPLE_OUTPUT_PATH).full_set

    assert full_set is not None
    assert full_set.changed_case_count == changed_case_count


@pytest.mark.parametrize(
    "run_full_rows",
    [
        pytest.param(_degraded_rows, id="status-change"),
        pytest.param(lambda: _rows_with_steps_removed({DEGRADED_CASE_ID: 1}), id="step-change"),
    ],
)
def test_cheaper_run_with_full_set_changes_ties(record, run_full_rows) -> None:
    record(_perfect_rows(), EXPENSIVE_USAGE, _perfect_rows())

    assert _outcome(record(_perfect_rows(), NO_USAGE, run_full_rows())) == "tie"


def test_cheaper_run_without_full_set_ties(record) -> None:
    record(_perfect_rows(), EXPENSIVE_USAGE)

    assert _outcome(record(_perfect_rows(), NO_USAGE)) == "tie"


def test_run_waits_for_the_runs_lock(record) -> None:
    runs.RUNS_DIR.mkdir(parents=True)
    lock_path = runs.RUNS_DIR / runs.LOCK_FILENAME
    lock_path.touch()
    run = threading.Thread(target=record, args=(_perfect_rows(),))
    run.start()

    run.join(timeout=0.5)
    assert run.is_alive()
    assert not (runs.RUNS_DIR / runs.BASELINE_FILENAME).exists()

    lock_path.unlink()
    run.join(timeout=10)
    assert not run.is_alive()
    assert (runs.RUNS_DIR / runs.BASELINE_FILENAME).is_file()
    assert not lock_path.exists()


def test_tied_run_can_be_promoted(record) -> None:
    record(_perfect_rows())
    tied_run_id = record(_perfect_rows())

    assert main(["promote", tied_run_id]) == 0

    assert _baseline() == tied_run_id
    assert _outcome(tied_run_id) == "promoted"


def test_promote_refuses_stale_tie(record) -> None:
    record(_degraded_rows())
    stale_tie_id = record(_degraded_rows())
    record(_perfect_rows())

    with pytest.raises(PromotionRefusedError, match="no longer current"):
        promote_run(stale_tie_id)


def test_promote_refuses_non_tie_and_unknown_runs(record) -> None:
    promoted_id = record(_perfect_rows())

    assert main(["promote", promoted_id]) == 1
    assert main(["promote", "missing-run"]) == 1
    assert _baseline() == promoted_id


def test_diff_lists_fixed_and_regressed_cases(record) -> None:
    baseline_id = record(_degraded_rows())
    run_id = record(_perfect_rows())

    fixed = compare_runs(baseline_id, run_id, SAMPLE_OUTPUT_PATH)
    regressed = compare_runs(run_id, baseline_id, SAMPLE_OUTPUT_PATH)

    assert [change.after.case_id for change in fixed.fixed] == [DEGRADED_CASE_ID]
    assert fixed.regressed == []
    assert [change.after.case_id for change in regressed.regressed] == [DEGRADED_CASE_ID]
    assert fixed.delta > 0
    assert fixed.fixed[0].pooled_effect == pytest.approx(fixed.delta)
    assert fixed.interval[1] > 0


def test_full_set_diff_reports_transitions_changes_and_disagreements(record) -> None:
    baseline_id = record(_perfect_rows(), full_rows=_perfect_rows())
    run_id = record(_perfect_rows(), full_rows=_degraded_rows())

    comparison = compare_runs(baseline_id, run_id, SAMPLE_OUTPUT_PATH)
    full_set = comparison.full_set

    assert full_set is not None
    assert full_set.status_transitions["COMPLETE"]["NOT_APPLICABLE"] == 1
    assert full_set.changed_case_count == 1
    assert full_set.pooled_step_f1 < 1
    assert full_set.top_step_disagreements[0].case_id == DEGRADED_CASE_ID
    assert full_set.top_step_disagreements[0].unmatched_step_count == 1
    diff_markdown = (runs.RUNS_DIR / run_id / runs.DIFF_FILENAME).read_text()
    assert "### Full set" in diff_markdown


def test_full_set_top_step_disagreements_are_ordered(record) -> None:
    baseline_id = record(_perfect_rows(), full_rows=_perfect_rows())
    run_id = record(
        _perfect_rows(),
        full_rows=_rows_with_steps_removed({"case_01": 1, "case_02": 1, "case_05": 2}),
    )

    full_set = compare_runs(baseline_id, run_id, SAMPLE_OUTPUT_PATH).full_set

    assert full_set is not None
    assert [
        (disagreement.case_id, disagreement.unmatched_step_count)
        for disagreement in full_set.top_step_disagreements
    ] == [("case_05", 2), ("case_01", 1), ("case_02", 1)]


def test_diff_warns_when_scoring_changed_since_baseline(
    record, monkeypatch: pytest.MonkeyPatch
) -> None:
    record(_perfect_rows())
    monkeypatch.setattr(runs, "_scoring_sha256", lambda _: "changed")
    run_id = record(_perfect_rows())

    diff_markdown = (runs.RUNS_DIR / run_id / runs.DIFF_FILENAME).read_text()
    assert "scoring code or labels changed" in diff_markdown


def test_comparison_covers_only_shared_cases(record) -> None:
    baseline_id = record(_perfect_rows()[:-1])
    run_id = record(_perfect_rows())

    comparison = compare_runs(baseline_id, run_id, SAMPLE_OUTPUT_PATH)

    assert len(comparison.run_scores) == len(_perfect_rows()) - 2
    assert comparison.delta == 0
    assert _outcome(run_id) == "tie"


def test_run_without_shared_cases_is_not_promoted(record) -> None:
    header, first_row, *other_rows = _perfect_rows()
    baseline_id = record([header, first_row], EXPENSIVE_USAGE)

    assert _outcome(record([header, *other_rows])) == "not_promoted"
    assert _baseline() == baseline_id


@pytest.mark.parametrize(
    ("baseline_rows", "run_rows", "outcome"),
    [
        pytest.param(_degraded_rows, _perfect_rows, "promoted", id="positive-delta"),
        pytest.param(_perfect_rows, _degraded_rows, "not_promoted", id="negative-delta"),
    ],
)
def test_large_labelled_delta_ignores_full_set_changes(
    record, baseline_rows, run_rows, outcome
) -> None:
    record(baseline_rows(), full_rows=_perfect_rows())

    assert _outcome(record(run_rows(), full_rows=_degraded_rows())) == outcome


@pytest.mark.parametrize(
    ("answer", "outcome"),
    [pytest.param("y", "promoted", id="yes"), pytest.param("", "tie", id="default-no")],
)
def test_interactive_tie_prompts_for_promotion(
    record,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    answer: str,
    outcome: str,
) -> None:
    record(_perfect_rows(), full_rows=_perfect_rows())
    capsys.readouterr()
    monkeypatch.setattr(runs, "_is_interactive", lambda: True)
    prompt_outputs: list[str] = []

    def respond(_: str) -> str:
        prompt_outputs.append(capsys.readouterr().out)
        return answer

    monkeypatch.setattr("builtins.input", respond)

    assert _outcome(record(_perfect_rows(), full_rows=_perfect_rows())) == outcome
    assert prompt_outputs[0].splitlines()[-1].startswith("Full set:")


def test_predictions_scoring_is_not_saved(runs_dir: Path, tmp_path: Path) -> None:
    labels_path = write_suite(tmp_path, is_holdout=False).labels_path

    assert main(["--predictions", str(labels_path)]) == 0

    assert not runs_dir.exists()


def test_full_set_run_saves_full_set_artifacts(runs_dir: Path) -> None:
    assert main(["--full-set"]) == 0

    run_dir = runs_dir / _baseline()
    assert (run_dir / runs.FULL_OUTPUT_FILENAME).is_file()
    assert (run_dir / runs.FULL_USAGE_FILENAME).is_file()


@pytest.mark.parametrize(
    "arguments",
    [
        pytest.param(["--full-set", "--predictions", str(SAMPLE_OUTPUT_PATH)], id="predictions"),
        pytest.param(["--full-set", "--holdout"], id="holdout"),
        pytest.param(["--full-set", "validate"], id="subcommand"),
    ],
)
def test_full_set_rejects_incompatible_arguments(arguments: list[str]) -> None:
    with pytest.raises(SystemExit) as error:
        main(arguments)

    assert error.value.code == 2


@pytest.mark.parametrize(
    ("failure_mode", "expected_exit_code"),
    [
        pytest.param("invalid-output", 1, id="validation"),
        pytest.param("agent-exit", 7, id="agent-exit"),
    ],
)
def test_full_set_failure_is_not_saved(
    runs_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_mode: str,
    expected_exit_code: int,
) -> None:
    original_run_agent = evaluation_main._run_agent

    def run_agent(requests_path: Path, output_path: Path, usage_path: Path) -> int:
        if requests_path != evaluation_main.FULL_REQUESTS_PATH:
            return original_run_agent(requests_path, output_path, usage_path)
        if failure_mode == "agent-exit":
            return expected_exit_code
        output_path.write_text("case_id,deletion_status,steps_json\n", encoding="utf-8")
        usage_path.write_text(json.dumps(NO_USAGE), encoding="utf-8")
        return 0

    monkeypatch.setattr(evaluation_main, "_run_agent", run_agent)

    assert main(["--full-set"]) == expected_exit_code
    assert not runs_dir.exists()


@pytest.mark.parametrize(
    ("baseline_rows", "run_rows", "baseline_usage", "run_usage"),
    [
        pytest.param(
            _perfect_rows,
            _degraded_rows,
            EXPENSIVE_USAGE,
            NO_USAGE,
            id="cheaper-run-with-negative-delta",
        ),
        pytest.param(
            _degraded_rows,
            _perfect_rows,
            NO_USAGE,
            EXPENSIVE_USAGE,
            id="costlier-run-with-positive-delta",
        ),
    ],
)
def test_cost_tiebreak_requires_the_cheaper_side_to_not_lose_labelled_score(
    record,
    monkeypatch: pytest.MonkeyPatch,
    baseline_rows,
    run_rows,
    baseline_usage,
    run_usage,
) -> None:
    monkeypatch.setattr(runs, "NOISE_FLOOR", 100)
    record(baseline_rows(), baseline_usage, full_rows=_perfect_rows())

    assert _outcome(record(run_rows(), run_usage, full_rows=_perfect_rows())) == "tie"


def test_holdout_runs_diff_against_previous_holdout_run(
    record_holdout, capsys: pytest.CaptureFixture[str]
) -> None:
    first_run_id = record_holdout(_degraded_rows())
    assert "No previous holdout run" in capsys.readouterr().out

    second_run_id = record_holdout(_perfect_rows())
    third_run_id = record_holdout(_perfect_rows())

    second_dir = runs.RUNS_DIR / runs.HOLDOUT_DIRNAME / second_run_id
    second_diff = (second_dir / runs.DIFF_FILENAME).read_text()
    third_record = json.loads(
        (runs.RUNS_DIR / runs.HOLDOUT_DIRNAME / third_run_id / runs.RUN_FILENAME).read_text()
    )
    assert f"previous holdout run {first_run_id}" in second_diff
    assert f"| {DEGRADED_CASE_ID} |" in second_diff.split("### Fixed")[1]
    assert third_record["previous_run_id"] == second_run_id
    assert not (runs.RUNS_DIR / runs.BASELINE_FILENAME).exists()


def test_promote_refuses_holdout_runs(record_holdout) -> None:
    holdout_run_id = record_holdout(_perfect_rows())

    with pytest.raises(PromotionRefusedError, match="holdout run"):
        promote_run(holdout_run_id)


def test_holdout_agent_runs_are_saved_as_holdout_runs(runs_dir: Path) -> None:
    assert main(["--holdout"]) == 0
    assert main(["--holdout"]) == 0

    holdout_run_dirs = list((runs_dir / runs.HOLDOUT_DIRNAME).iterdir())
    assert len(holdout_run_dirs) == 2
    assert sum((run_dir / runs.DIFF_FILENAME).is_file() for run_dir in holdout_run_dirs) == 1
    assert not (runs_dir / runs.BASELINE_FILENAME).exists()
