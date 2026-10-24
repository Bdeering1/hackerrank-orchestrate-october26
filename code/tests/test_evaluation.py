import csv
from collections.abc import Callable
from pathlib import Path

import pytest

from evaluation.main import main
from evaluation.validate import validation_errors

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_OUTPUT_PATH = REPO_ROOT / "dataset" / "sample_output.csv"
FIRST_CASE_ID = "case_01"
PREDICTIONS_FILENAME = "predictions.csv"
CsvRows = list[list[str]]
RowsMutator = Callable[[CsvRows], CsvRows]


def test_main_scores_sample_answers(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0

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
    with SAMPLE_OUTPUT_PATH.open(encoding="utf-8", newline="") as sample_file:
        return list(csv.reader(sample_file))


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
        pytest.param(_without_last_row, "case_32", id="missing-case"),
        pytest.param(_with_duplicate_row, FIRST_CASE_ID, id="duplicate-case"),
        pytest.param(_with_out_of_order_rows, "case_09", id="out-of-order"),
        pytest.param(_with_invalid_status, FIRST_CASE_ID, id="invalid-status"),
        pytest.param(_with_non_array_steps, FIRST_CASE_ID, id="non-array-steps"),
        pytest.param(_with_wrong_header, "header", id="wrong-header"),
        pytest.param(None, "cannot read", id="non-utf8"),
    ],
)
def test_main_reports_validation_errors(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    mutate_rows: RowsMutator | None,
    expected_problem: str,
) -> None:
    predictions_path = tmp_path / PREDICTIONS_FILENAME
    if mutate_rows is None:
        predictions_path.write_bytes(b"\xff")
    else:
        _write_rows(predictions_path, mutate_rows(_sample_output_rows()))

    assert main(["--predictions", str(predictions_path)]) == 1

    captured = capsys.readouterr()
    assert "validation failed" in captured.err
    assert expected_problem in captured.err


def test_validation_uses_numeric_case_order(tmp_path: Path) -> None:
    rows = _sample_output_rows()
    predictions_path = tmp_path / PREDICTIONS_FILENAME
    rows = [rows[0], ["case_99", *rows[1][1:]], ["case_100", *rows[2][1:]]]
    _write_rows(predictions_path, rows)

    assert validation_errors(predictions_path, ["case_99", "case_100"]) == []

    rows[1], rows[2] = rows[2], rows[1]
    _write_rows(predictions_path, rows)

    assert any(
        "case_99" in error for error in validation_errors(predictions_path, ["case_99", "case_100"])
    )
