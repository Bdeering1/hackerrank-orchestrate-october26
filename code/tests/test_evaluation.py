import csv
from collections.abc import Callable
from pathlib import Path

import pytest

from evaluation.main import main
from evaluation.usage import usage_summary
from evaluation.validate import csv_rows, validation_errors
from ghost_audit.usage import UsageTracker

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_OUTPUT_PATH = REPO_ROOT / "dataset" / "sample_output.csv"
FIRST_CASE_ID = "case_01"
PREDICTIONS_FILENAME = "predictions.csv"
CsvRows = list[list[str]]
RowsMutator = Callable[[CsvRows], CsvRows]


def test_main_scores_sample_answers(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--predictions", str(SAMPLE_OUTPUT_PATH)]) == 0

    captured = capsys.readouterr()
    assert "32/32" in captured.out
    assert "100.0%" in captured.out


def test_main_reports_status_mismatch(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    rows = _sample_output_rows()
    rows[1][1] = "INCOMPLETE"
    predictions_path = tmp_path / PREDICTIONS_FILENAME
    _write_rows(predictions_path, rows)

    assert main(["--predictions", str(predictions_path)]) == 0

    captured = capsys.readouterr()
    assert "31/32" in captured.out
    assert "100.0%" not in captured.out


def _sample_output_rows() -> CsvRows:
    return csv_rows(SAMPLE_OUTPUT_PATH)


def _write_rows(path: Path, rows: CsvRows) -> None:
    with path.open("w", encoding="utf-8", newline="") as predictions_file:
        csv.writer(predictions_file).writerows(rows)


def _without_last_row(rows: CsvRows) -> CsvRows:
    return rows[:-1]


def _with_duplicate_row(rows: CsvRows) -> CsvRows:
    return [*rows, rows[1]]


def _with_out_of_order_rows(rows: CsvRows) -> CsvRows:
    rows[9], rows[10] = rows[10], rows[9]
    return rows


def _with_extra_row(rows: CsvRows) -> CsvRows:
    return [*rows, ["case_33", *rows[1][1:]]]


def _with_invalid_status(rows: CsvRows) -> CsvRows:
    rows[1][1] = "INVALID"
    return rows


def _with_non_array_steps(rows: CsvRows) -> CsvRows:
    rows[1][2] = "{}"
    return rows


def _with_wrong_header(rows: CsvRows) -> CsvRows:
    rows[0][1] = "status"
    return rows


@pytest.mark.parametrize(
    ("mutate_rows", "expected_problem"),
    [
        pytest.param(_without_last_row, "missing case_id: case_32", id="missing-case"),
        pytest.param(
            _with_duplicate_row, f"({FIRST_CASE_ID}): duplicate case_id", id="duplicate-case"
        ),
        pytest.param(_with_extra_row, "(case_33): unexpected case_id", id="extra-case"),
        pytest.param(_with_out_of_order_rows, "(case_09): rows are not sorted", id="out-of-order"),
        pytest.param(
            _with_invalid_status, f"({FIRST_CASE_ID}): invalid deletion_status", id="invalid-status"
        ),
        pytest.param(
            _with_non_array_steps,
            f"({FIRST_CASE_ID}): steps_json is not a JSON array",
            id="non-array-steps",
        ),
        pytest.param(_with_wrong_header, "line 1: header must be", id="wrong-header"),
    ],
)
def test_main_reports_validation_errors(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    mutate_rows: RowsMutator,
    expected_problem: str,
) -> None:
    predictions_path = tmp_path / PREDICTIONS_FILENAME
    _write_rows(predictions_path, mutate_rows(_sample_output_rows()))

    assert main(["--predictions", str(predictions_path)]) == 1

    captured = capsys.readouterr()
    assert "validation failed" in captured.err
    assert expected_problem in captured.err


def test_main_reports_unreadable_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    predictions_path = tmp_path / PREDICTIONS_FILENAME
    predictions_path.write_bytes(b"\xff")

    assert main(["--predictions", str(predictions_path)]) == 1

    assert "cannot read" in capsys.readouterr().err


def test_validation_uses_numeric_case_order(tmp_path: Path) -> None:
    rows = _sample_output_rows()
    predictions_path = tmp_path / PREDICTIONS_FILENAME
    rows = [rows[0], ["case_99", *rows[1][1:]], ["case_100", *rows[2][1:]]]
    _write_rows(predictions_path, rows)

    assert validation_errors(predictions_path, ["case_99", "case_100"]) == []

    rows[1], rows[2] = rows[2], rows[1]
    _write_rows(predictions_path, rows)

    assert validation_errors(predictions_path, ["case_99", "case_100"]) == [
        "line 3 (case_99): rows are not sorted by case number"
    ]


def test_main_runs_placeholder_agent(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0

    captured = capsys.readouterr()
    assert "status accuracy:" in captured.out
    assert "usage:" in captured.out


def test_usage_summary_calculates_model_and_overall_costs(tmp_path: Path) -> None:
    usage_path = tmp_path / "usage.json"
    tracker = UsageTracker()
    tracker.record("anthropic", "claude-opus-5.5", 750_000, 400_000)
    tracker.record("anthropic", "claude-sonnet-5.5", 500_000, 1_000_000)
    tracker.record("anthropic", "claude-opus-5.5", 250_000, 100_000)
    tracker.write(usage_path)

    summary = usage_summary(usage_path, request_count=10)

    opus, sonnet = (model.totals for model in summary.models)
    assert (opus.calls, opus.input_tokens, opus.output_tokens) == (2, 1_000_000, 500_000)
    assert opus.estimated_cost_usd == 14
    assert (sonnet.calls, sonnet.input_tokens, sonnet.output_tokens) == (1, 500_000, 1_000_000)
    assert sonnet.estimated_cost_usd == 11
    assert summary.overall.total_tokens == 3_000_000
    assert summary.overall.estimated_cost_usd == 25
    assert summary.average_tokens_per_request(summary.overall) == 300_000
    assert summary.cost_per_request_usd(summary.overall) == 2.5


def test_usage_summary_rejects_unknown_model(tmp_path: Path) -> None:
    usage_path = tmp_path / "usage.json"
    usage_path.write_text(
        '{"models":[{"provider":"test","model":"unknown","calls":1,'
        '"input_tokens":1,"output_tokens":1}]}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown"):
        usage_summary(usage_path, request_count=1)
