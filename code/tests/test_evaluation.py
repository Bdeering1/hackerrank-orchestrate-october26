import csv
import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import pytest

from evaluation.main import main
from evaluation.score import case_scores
from evaluation.validate import csv_rows, validation_errors

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_OUTPUT_PATH = REPO_ROOT / "dataset" / "sample_output.csv"
FIRST_CASE_ID = "case_01"
MULTI_STEP_CASE_ID = "case_03"
INCOMPLETE_CASE_ID = "case_05"
CITED_EVIDENCE_ID = "evidence_54"
PREDICTIONS_FILENAME = "predictions.csv"
CsvRows = list[list[str]]
RowsMutator = Callable[[CsvRows], CsvRows]


def test_main_scores_sample_answers(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0

    captured = capsys.readouterr()
    assert "Average composite: 100.0%" in captured.out
    assert "Status matches: 32/32" in captured.out


def test_main_reports_status_mismatch(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    rows = _sample_output_rows()
    rows[1][1] = "NOT_APPLICABLE"
    rows[1][2] = "[]"
    predictions_path = tmp_path / PREDICTIONS_FILENAME
    _write_rows(predictions_path, rows)

    assert main(["--predictions", str(predictions_path)]) == 0

    captured = capsys.readouterr()
    assert "Status matches: 31/32" in captured.out
    assert "Average composite: 100.0%" not in captured.out


def _sample_output_rows() -> CsvRows:
    return csv_rows(SAMPLE_OUTPUT_PATH)


def _write_rows(path: Path, rows: CsvRows) -> None:
    with path.open("w", encoding="utf-8", newline="") as predictions_file:
        csv.writer(predictions_file).writerows(rows)


def _case_row(rows: CsvRows, case_id: str) -> list[str]:
    return next(row for row in rows[1:] if row[0] == case_id)


def _steps(rows: CsvRows, case_id: str) -> list[dict[str, object]]:
    steps = json.loads(_case_row(rows, case_id)[2])
    assert isinstance(steps, list)
    return steps


def _set_steps(rows: CsvRows, case_id: str, steps: list[dict[str, object]]) -> CsvRows:
    _case_row(rows, case_id)[2] = json.dumps(steps)
    return rows


def _update_step(
    rows: CsvRows, case_id: str, step_index: int, updates: dict[str, object]
) -> CsvRows:
    steps = _steps(rows, case_id)
    steps[step_index].update(updates)
    return _set_steps(rows, case_id, steps)


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


def _with_extra_step_key(rows: CsvRows) -> CsvRows:
    return _update_step(rows, FIRST_CASE_ID, 0, {"extra": "value"})


def _with_missing_step_key(rows: CsvRows) -> CsvRows:
    steps = _steps(rows, FIRST_CASE_ID)
    del steps[0]["state"]
    return _set_steps(rows, FIRST_CASE_ID, steps)


def _with_non_integer_step_no(rows: CsvRows) -> CsvRows:
    return _update_step(rows, FIRST_CASE_ID, 0, {"step_no": True})


def _with_non_consecutive_step_no(rows: CsvRows) -> CsvRows:
    steps = _steps(rows, MULTI_STEP_CASE_ID)
    steps[1]["step_no"] = 5
    return _set_steps(rows, MULTI_STEP_CASE_ID, steps)


def _with_disallowed_step_combination(rows: CsvRows) -> CsvRows:
    return _update_step(rows, FIRST_CASE_ID, 0, {"operation": "DELETE_RECORD"})


def _with_out_of_order_steps(rows: CsvRows) -> CsvRows:
    steps = _steps(rows, MULTI_STEP_CASE_ID)
    steps[0], steps[1] = steps[1], steps[0]
    for step_position, step in enumerate(steps, start=1):
        step["step_no"] = step_position
    return _set_steps(rows, MULTI_STEP_CASE_ID, steps)


def _with_steps_for_not_applicable(rows: CsvRows) -> CsvRows:
    row = rows[1]
    row[1] = "NOT_APPLICABLE"
    row[2] = json.dumps([_verification_step(1, "account_001", "")])
    return rows


def _with_complete_without_steps(rows: CsvRows) -> CsvRows:
    return _set_steps(rows, FIRST_CASE_ID, [])


def _with_incomplete_without_steps(rows: CsvRows) -> CsvRows:
    return _set_steps(rows, INCOMPLETE_CASE_ID, [])


def _with_complete_finding(rows: CsvRows) -> CsvRows:
    return _update_step(
        rows,
        FIRST_CASE_ID,
        0,
        {"phase": "FINDING", "operation": "REPORT_REMAINING_RECORD", "state": "PRESENT"},
    )


def _with_complete_without_evidence(rows: CsvRows) -> CsvRows:
    return _update_step(rows, FIRST_CASE_ID, 0, {"evidence_id": ""})


def _with_incomplete_finding_without_evidence(rows: CsvRows) -> CsvRows:
    return _update_step(rows, INCOMPLETE_CASE_ID, 0, {"evidence_id": ""})


def _with_incomplete_remediation_evidence(rows: CsvRows) -> CsvRows:
    return _update_step(rows, INCOMPLETE_CASE_ID, 1, {"evidence_id": CITED_EVIDENCE_ID})


def _with_incomplete_verification_evidence(rows: CsvRows) -> CsvRows:
    return _update_step(rows, INCOMPLETE_CASE_ID, 2, {"evidence_id": CITED_EVIDENCE_ID})


def _with_unknown_evidence(rows: CsvRows) -> CsvRows:
    return _update_step(rows, FIRST_CASE_ID, 0, {"evidence_id": "evidence_unknown"})


def _with_late_evidence(rows: CsvRows) -> CsvRows:
    return _update_step(rows, FIRST_CASE_ID, 0, {"evidence_id": "evidence_03"})


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
        pytest.param(_with_extra_step_key, "step 1: must have exactly", id="extra-step-key"),
        pytest.param(_with_missing_step_key, "step 1: must have exactly", id="missing-step-key"),
        pytest.param(_with_non_integer_step_no, "step 1: must have exactly", id="non-integer-step"),
        pytest.param(_with_non_consecutive_step_no, "step 2: step_no must equal", id="step-number"),
        pytest.param(_with_disallowed_step_combination, "invalid phase, operation", id="operation"),
        pytest.param(_with_out_of_order_steps, "steps are not in canonical order", id="step-order"),
        pytest.param(
            _with_steps_for_not_applicable, "NOT_APPLICABLE must have", id="not-applicable"
        ),
        pytest.param(
            _with_complete_without_steps,
            "COMPLETE must have at least one step",
            id="complete-empty",
        ),
        pytest.param(
            _with_incomplete_without_steps,
            "INCOMPLETE must have at least one step",
            id="incomplete-empty",
        ),
        pytest.param(
            _with_complete_finding, "COMPLETE steps must be VERIFICATION", id="complete-phase"
        ),
        pytest.param(
            _with_complete_without_evidence, "COMPLETE steps must cite", id="complete-evidence"
        ),
        pytest.param(
            _with_incomplete_finding_without_evidence,
            "INCOMPLETE findings must cite",
            id="incomplete-finding",
        ),
        pytest.param(
            _with_incomplete_remediation_evidence,
            "INCOMPLETE remediation and verification steps must not cite",
            id="incomplete-remediation",
        ),
        pytest.param(
            _with_incomplete_verification_evidence,
            "INCOMPLETE remediation and verification steps must not cite",
            id="incomplete-verification",
        ),
        pytest.param(_with_unknown_evidence, "unknown evidence_id", id="unknown-evidence"),
        pytest.param(_with_late_evidence, "dated after audit_at", id="late-evidence"),
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
    audit_time = datetime.fromisoformat("2026-12-01T00:00:00Z")
    evidence_time = datetime.fromisoformat("2026-01-01T00:00:00Z")
    audit_times = {"case_99": audit_time, "case_100": audit_time}

    assert (
        validation_errors(predictions_path, audit_times, {CITED_EVIDENCE_ID: evidence_time}) == []
    )

    rows[1], rows[2] = rows[2], rows[1]
    _write_rows(predictions_path, rows)

    assert validation_errors(predictions_path, audit_times, {CITED_EVIDENCE_ID: evidence_time}) == [
        "line 3 (case_99): rows are not sorted by case number"
    ]


def _verification_step(step_no: int, resource_id: str, evidence_id: str) -> dict[str, object]:
    return {
        "step_no": step_no,
        "phase": "VERIFICATION",
        "system_id": "account_service",
        "resource_id": resource_id,
        "operation": "VERIFY_RECORD_ABSENT",
        "state": "ABSENT",
        "evidence_id": evidence_id,
    }


FIRST_EXPECTED_STEP = _verification_step(1, "account_001", "evidence_01")
SECOND_EXPECTED_STEP = _verification_step(2, "account_002", "evidence_02")


def _score_rows(status: str, steps: list[dict[str, object]]) -> CsvRows:
    return [
        ["case_id", "deletion_status", "steps_json"],
        ["case_01", status, json.dumps(steps)],
    ]


@pytest.mark.parametrize(
    ("status", "steps", "metric", "expected_value"),
    [
        pytest.param("INCOMPLETE", [FIRST_EXPECTED_STEP], "status", 0.0, id="status"),
        pytest.param(
            "COMPLETE",
            [{**FIRST_EXPECTED_STEP, "operation": "VERIFY_RECORD_PRESENT"}],
            "step",
            0.0,
            id="step",
        ),
        pytest.param(
            "COMPLETE",
            [{**FIRST_EXPECTED_STEP, "evidence_id": "evidence_02"}],
            "field",
            pytest.approx(1 / 3),
            id="field",
        ),
        pytest.param(
            "COMPLETE",
            [{**SECOND_EXPECTED_STEP, "step_no": 1}],
            "sequence",
            0.5,
            id="sequence",
        ),
        pytest.param(
            "COMPLETE", [FIRST_EXPECTED_STEP], "composite", pytest.approx(205 / 3), id="composite"
        ),
    ],
)
def test_case_scores_partial_metrics(
    tmp_path: Path,
    status: str,
    steps: list[dict[str, object]],
    metric: str,
    expected_value: object,
) -> None:
    labels_path = tmp_path / "labels.csv"
    predictions_path = tmp_path / PREDICTIONS_FILENAME
    _write_rows(labels_path, _score_rows("COMPLETE", [FIRST_EXPECTED_STEP, SECOND_EXPECTED_STEP]))
    _write_rows(predictions_path, _score_rows(status, steps))

    score = case_scores(predictions_path, labels_path)[0]

    assert getattr(score, metric) == expected_value


def test_case_scores_missing_prediction_is_zero(tmp_path: Path) -> None:
    labels_path = tmp_path / "labels.csv"
    predictions_path = tmp_path / PREDICTIONS_FILENAME
    _write_rows(labels_path, _score_rows("NOT_APPLICABLE", []))
    _write_rows(predictions_path, [["case_id", "deletion_status", "steps_json"]])

    score = case_scores(predictions_path, labels_path)[0]

    assert (score.status, score.step, score.field, score.sequence, score.composite) == (
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
    )
