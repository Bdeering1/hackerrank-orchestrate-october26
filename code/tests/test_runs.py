import csv
import json
import threading
from collections.abc import Mapping
from pathlib import Path

import pytest

from evaluation import runs
from evaluation.main import main
from evaluation.runs import PromotionRefusedError, compare_runs, promote_run, record_run
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
DOUBLE_EXPENSIVE_USAGE = {"models": [{**EXPENSIVE_USAGE["models"][0], "input_tokens": 2_000_000}]}


@pytest.fixture
def record(tmp_path: Path):
    def record_rows(rows: list[list[str]], usage: Mapping[str, object] = NO_USAGE) -> str:
        output_path = tmp_path / "output.csv"
        usage_path = tmp_path / "usage.json"
        with output_path.open("w", encoding="utf-8", newline="") as output_file:
            csv.writer(output_file).writerows(rows)
        usage_path.write_text(json.dumps(usage), encoding="utf-8")
        return record_run(output_path, usage_path, SAMPLE_OUTPUT_PATH, "scores")

    return record_rows


def _perfect_rows() -> list[list[str]]:
    return csv_rows(SAMPLE_OUTPUT_PATH)


def _degraded_rows() -> list[list[str]]:
    rows = _perfect_rows()
    row = next(row for row in rows[1:] if row[0] == DEGRADED_CASE_ID)
    row[1:] = ["NOT_APPLICABLE", "[]"]
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
def test_tie_is_decided_by_large_cost_difference(
    record, baseline_usage, run_usage, outcome
) -> None:
    record(_perfect_rows(), baseline_usage)

    assert _outcome(record(_perfect_rows(), run_usage)) == outcome


def test_cost_tiebreak_compares_cost_per_request(record) -> None:
    rows = _perfect_rows()
    half_case_count = (len(rows) - 1) // 2
    record(rows[: 1 + half_case_count], EXPENSIVE_USAGE)

    assert _outcome(record(rows, DOUBLE_EXPENSIVE_USAGE)) == "tie"


def test_run_waits_for_the_baseline_lock(record) -> None:
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
    ("answer", "outcome"),
    [pytest.param("y", "promoted", id="yes"), pytest.param("", "tie", id="default-no")],
)
def test_interactive_tie_prompts_for_promotion(
    record, monkeypatch: pytest.MonkeyPatch, answer: str, outcome: str
) -> None:
    record(_perfect_rows())
    monkeypatch.setattr(runs, "_is_interactive", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: answer)

    assert _outcome(record(_perfect_rows())) == outcome


def test_predictions_scoring_is_not_saved(runs_dir: Path) -> None:
    assert main(["--predictions", str(SAMPLE_OUTPUT_PATH)]) == 0

    assert not runs_dir.exists()
