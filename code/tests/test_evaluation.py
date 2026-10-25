import csv
import json
import tempfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import pytest

from evaluation.main import FULL_REQUESTS_PATH, main, write_suite
from evaluation.score import CaseScore, case_scores, pooled_composite
from evaluation.usage import usage_summary
from evaluation.validate import csv_rows, validation_errors
from ghost_audit.__main__ import main as agent_main
from ghost_audit.usage import UsageTracker

FIRST_CASE_ID = "case_01"
MULTI_STEP_CASE_ID = "case_03"
INCOMPLETE_CASE_ID = "case_05"
CITED_EVIDENCE_ID = "evidence_54"
PREDICTIONS_FILENAME = "predictions.csv"
CsvRows = list[list[str]]
RowsMutator = Callable[[CsvRows], CsvRows]


@pytest.mark.parametrize("holdout_argv", [[], ["--holdout"]], ids=["default", "holdout"])
def test_main_scores_suite_answers(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, holdout_argv: list[str]
) -> None:
    rows = _suite_label_rows(is_holdout=bool(holdout_argv))
    predictions_path = tmp_path / PREDICTIONS_FILENAME
    _write_rows(predictions_path, rows)

    assert main([*holdout_argv, "--predictions", str(predictions_path)]) == 0

    captured = capsys.readouterr()
    case_count = len(rows) - 1
    assert "Composite: 100.0%" in captured.out
    assert f"Status matches: {case_count}/{case_count}" in captured.out


def test_main_reports_status_mismatch(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    rows = _suite_label_rows()
    rows[1][1] = "NOT_APPLICABLE"
    rows[1][2] = "[]"
    predictions_path = tmp_path / PREDICTIONS_FILENAME
    _write_rows(predictions_path, rows)

    assert main(["--predictions", str(predictions_path)]) == 0

    captured = capsys.readouterr()
    case_count = len(rows) - 1
    assert f"Status matches: {case_count - 1}/{case_count}" in captured.out


def _suite_label_rows(*, is_holdout: bool = False) -> CsvRows:
    with tempfile.TemporaryDirectory() as suite_dir:
        return csv_rows(write_suite(Path(suite_dir), is_holdout=is_holdout).labels_path)


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


def _without_first_case(rows: CsvRows) -> CsvRows:
    return [rows[0], *rows[2:]]


def _with_duplicate_row(rows: CsvRows) -> CsvRows:
    return [*rows, rows[1]]


def _with_out_of_order_rows(rows: CsvRows) -> CsvRows:
    rows[1], rows[2] = rows[2], rows[1]
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
        pytest.param(_without_first_case, f"missing case_id: {FIRST_CASE_ID}", id="missing-case"),
        pytest.param(
            _with_duplicate_row, f"({FIRST_CASE_ID}): duplicate case_id", id="duplicate-case"
        ),
        pytest.param(_with_extra_row, "(case_33): unexpected case_id", id="extra-case"),
        pytest.param(
            _with_out_of_order_rows, f"({FIRST_CASE_ID}): rows are not sorted", id="out-of-order"
        ),
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
    _write_rows(predictions_path, mutate_rows(_suite_label_rows()))

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
    rows = _suite_label_rows()
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
    ("status", "steps", "metric_value", "expected_value"),
    [
        pytest.param(
            "INCOMPLETE",
            [FIRST_EXPECTED_STEP],
            lambda score: score.status_match.value,
            0.0,
            id="status",
        ),
        pytest.param(
            "COMPLETE",
            [{**FIRST_EXPECTED_STEP, "operation": "VERIFY_RECORD_PRESENT"}],
            lambda score: score.step_f1.value,
            0.0,
            id="step",
        ),
        pytest.param(
            "COMPLETE",
            [{**FIRST_EXPECTED_STEP, "evidence_id": "evidence_02"}],
            lambda score: score.field_accuracy.value,
            pytest.approx(1 / 3),
            id="field",
        ),
        pytest.param(
            "COMPLETE",
            [{**SECOND_EXPECTED_STEP, "step_no": 1}],
            lambda score: score.sequence_similarity.value,
            0.5,
            id="sequence",
        ),
        pytest.param(
            "COMPLETE",
            [FIRST_EXPECTED_STEP],
            lambda score: score.composite,
            pytest.approx(205 / 3),
            id="composite",
        ),
    ],
)
def test_case_scores_partial_metrics(
    tmp_path: Path,
    status: str,
    steps: list[dict[str, object]],
    metric_value: Callable[[CaseScore], float],
    expected_value: object,
) -> None:
    labels_path = tmp_path / "labels.csv"
    predictions_path = tmp_path / PREDICTIONS_FILENAME
    _write_rows(labels_path, _score_rows("COMPLETE", [FIRST_EXPECTED_STEP, SECOND_EXPECTED_STEP]))
    _write_rows(predictions_path, _score_rows(status, steps))

    score = case_scores(predictions_path, labels_path)[0]

    assert metric_value(score) == expected_value


@pytest.mark.parametrize(
    ("prediction_rows", "expected_composite"),
    [
        pytest.param(_score_rows("NOT_APPLICABLE", []), 100.0, id="match"),
        pytest.param([["case_id", "deletion_status", "steps_json"]], 0.0, id="missing"),
    ],
)
def test_case_scores_not_applicable_label(
    tmp_path: Path, prediction_rows: CsvRows, expected_composite: float
) -> None:
    labels_path = tmp_path / "labels.csv"
    predictions_path = tmp_path / PREDICTIONS_FILENAME
    _write_rows(labels_path, _score_rows("NOT_APPLICABLE", []))
    _write_rows(predictions_path, prediction_rows)

    assert case_scores(predictions_path, labels_path)[0].composite == pytest.approx(
        expected_composite
    )


def test_field_score_pairs_identical_steps_on_shared_key(tmp_path: Path) -> None:
    retained_step = {
        **FIRST_EXPECTED_STEP,
        "operation": "VERIFY_RECORD_PRESENT",
        "state": "PRESENT",
    }
    labels_path = tmp_path / "labels.csv"
    predictions_path = tmp_path / PREDICTIONS_FILENAME
    _write_rows(labels_path, _score_rows("COMPLETE", [retained_step]))
    _write_rows(
        predictions_path,
        _score_rows("COMPLETE", [FIRST_EXPECTED_STEP, {**retained_step, "step_no": 2}]),
    )

    assert case_scores(predictions_path, labels_path)[0].field_accuracy.value == 0.5


def test_pooled_composite_counts_each_step_once(tmp_path: Path) -> None:
    labels_path = tmp_path / "labels.csv"
    predictions_path = tmp_path / PREDICTIONS_FILENAME
    labels = [
        *_score_rows("COMPLETE", [FIRST_EXPECTED_STEP]),
        ["case_02", "COMPLETE", json.dumps([FIRST_EXPECTED_STEP, SECOND_EXPECTED_STEP])],
    ]
    _write_rows(labels_path, labels)
    _write_rows(
        predictions_path,
        [
            *_score_rows("COMPLETE", [{**FIRST_EXPECTED_STEP, "evidence_id": "evidence_02"}]),
            labels[2],
        ],
    )

    assert pooled_composite(case_scores(predictions_path, labels_path)) == pytest.approx(245 / 3)


def test_main_runs_placeholder_agent(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0

    captured = capsys.readouterr()
    assert "Composite:" in captured.out
    assert "usage:" in captured.out


def test_usage_summary_calculates_model_and_overall_costs(tmp_path: Path) -> None:
    usage_path = tmp_path / "usage.json"
    tracker = UsageTracker()
    tracker.record("anthropic", "claude-opus-5-5", 750_000, 400_000)
    tracker.record("anthropic", "claude-sonnet-5-5", 500_000, 1_000_000)
    tracker.record("anthropic", "claude-opus-5-5", 250_000, 100_000)
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


@pytest.fixture(name="full_set_output_path")
def _full_set_output_path(tmp_path: Path) -> Path:
    output_path = tmp_path / PREDICTIONS_FILENAME
    assert agent_main(["--requests", str(FULL_REQUESTS_PATH), "--output", str(output_path)]) == 0
    return output_path


def test_validate_accepts_full_set_output(
    full_set_output_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["validate", str(full_set_output_path)]) == 0

    assert "518 cases valid" in capsys.readouterr().out


def test_validate_defaults_to_root_output(
    full_set_output_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("evaluation.main.DEFAULT_OUTPUT_PATH", full_set_output_path)

    assert main(["validate"]) == 0


def test_validate_reports_missing_case(
    full_set_output_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rows = csv_rows(full_set_output_path)
    missing_case_id = rows[-1][0]
    _write_rows(full_set_output_path, rows[:-1])

    assert main(["validate", str(full_set_output_path)]) == 1

    stderr = capsys.readouterr().err
    assert "validation failed:" in stderr
    assert f"missing case_id: {missing_case_id}" in stderr
