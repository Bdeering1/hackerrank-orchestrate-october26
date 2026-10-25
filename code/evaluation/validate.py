from __future__ import annotations

import csv
import json
import typing

from ghost_audit.output_format import HEADER, case_number

if typing.TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime
    from pathlib import Path

FINDING_PHASE = "FINDING"
REMEDIATION_PHASE = "REMEDIATION"
VERIFICATION_PHASE = "VERIFICATION"
VALID_STATUSES = frozenset({"COMPLETE", "INCOMPLETE", "NOT_APPLICABLE"})
STEP_FIELDS = frozenset(
    {"step_no", "phase", "system_id", "resource_id", "operation", "state", "evidence_id"}
)
ALLOWED_OPERATIONS = (
    (FINDING_PHASE, "REPORT_REMAINING_RECORD", "PRESENT"),
    (FINDING_PHASE, "REPORT_EXPOSED_PII", "PRESENT"),
    (FINDING_PHASE, "REPORT_ACTIVE_DATA_FLOW", "ACTIVE"),
    (FINDING_PHASE, "REPORT_RESTORE_RISK", "ACTIVE"),
    (REMEDIATION_PHASE, "DISABLE_DATA_FLOW", "DISABLED"),
    (REMEDIATION_PHASE, "BLOCK_RESTORE", "BLOCKED"),
    (REMEDIATION_PHASE, "DELETE_RECORD", "ABSENT"),
    (REMEDIATION_PHASE, "REDACT_RECORD", "REDACTED"),
    (REMEDIATION_PHASE, "ANONYMIZE_RECORD", "ANONYMIZED"),
    (VERIFICATION_PHASE, "VERIFY_RECORD_ABSENT", "ABSENT"),
    (VERIFICATION_PHASE, "VERIFY_RECORD_PRESENT", "PRESENT"),
    (VERIFICATION_PHASE, "VERIFY_RECORD_REDACTED", "REDACTED"),
    (VERIFICATION_PHASE, "VERIFY_RECORD_ANONYMIZED", "ANONYMIZED"),
    (VERIFICATION_PHASE, "VERIFY_DATA_FLOW_DISABLED", "DISABLED"),
    (VERIFICATION_PHASE, "VERIFY_RESTORE_BLOCKED", "BLOCKED"),
)
OPERATION_ORDER = {operation: index for index, operation in enumerate(ALLOWED_OPERATIONS)}


class Step(typing.TypedDict):
    step_no: int
    phase: str
    system_id: str
    resource_id: str
    operation: str
    state: str
    evidence_id: str


def validation_errors(
    predictions_path: Path,
    audit_times: Mapping[str, datetime],
    evidence_times: Mapping[str, datetime],
) -> list[str]:
    """Return every validation error in a predictions CSV."""
    try:
        rows = csv_rows(predictions_path)
    except (OSError, UnicodeDecodeError, csv.Error) as error:
        return [f"cannot read {predictions_path}: {error}"]

    if not rows:
        return ["line 1: missing header"]

    errors: list[str] = []
    if tuple(rows[0]) != HEADER:
        errors.append(f"line 1: header must be {','.join(HEADER)}")

    requested_ids = set(audit_times)
    found_ids: set[str] = set()
    case_positions: list[tuple[int, int, str]] = []
    for line_number, row in enumerate(rows[1:], start=2):
        case_id = row[0] if row else ""
        if len(row) != len(HEADER):
            errors.append(_row_error(line_number, case_id, f"expected {len(HEADER)} fields"))
            found_ids.add(case_id)
            continue
        if case_id in found_ids:
            errors.append(_row_error(line_number, case_id, "duplicate case_id"))
        found_ids.add(case_id)
        if case_id not in requested_ids:
            errors.append(_row_error(line_number, case_id, "unexpected case_id"))

        try:
            number = case_number(case_id)
        except ValueError:
            errors.append(_row_error(line_number, case_id, "malformed case_id"))
        else:
            case_positions.append((number, line_number, case_id))

        deletion_status = row[1]
        if deletion_status not in VALID_STATUSES:
            errors.append(_row_error(line_number, case_id, "invalid deletion_status"))
        errors.extend(
            _step_errors(
                line_number,
                case_id,
                deletion_status,
                row[2],
                audit_times,
                evidence_times,
            )
        )

    errors.extend(
        f"missing case_id: {case_id}"
        for case_id in sorted(requested_ids - found_ids, key=case_number)
    )
    errors.extend(_sort_errors(case_positions))
    return errors


def csv_rows(path: Path) -> list[list[str]]:
    """Return all rows in a UTF-8 CSV file."""
    with path.open(encoding="utf-8", newline="") as csv_file:
        return list(csv.reader(csv_file))


def data_rows(path: Path) -> list[list[str]]:
    """Return CSV rows after the header."""
    return csv_rows(path)[1:]


def _step_errors(
    line_number: int,
    case_id: str,
    deletion_status: str,
    steps_json: str,
    audit_times: Mapping[str, datetime],
    evidence_times: Mapping[str, datetime],
) -> list[str]:
    steps = _parsed_steps(steps_json)
    if steps is None:
        return [_row_error(line_number, case_id, "steps_json is not a JSON array")]

    errors: list[str] = []
    valid_steps: list[tuple[int, Step, int]] = []
    for step_position, raw_step in enumerate(steps, start=1):
        step = _step_with_shape(raw_step)
        if step is None:
            errors.append(
                _step_error(
                    line_number,
                    case_id,
                    step_position,
                    "must have exactly the seven step fields with valid types",
                )
            )
            continue
        if step["step_no"] != step_position:
            errors.append(
                _step_error(
                    line_number, case_id, step_position, "step_no must equal its array position"
                )
            )

        errors.extend(
            _evidence_errors(
                line_number,
                case_id,
                step_position,
                step["evidence_id"],
                audit_times,
                evidence_times,
            )
        )
        operation = (step["phase"], step["operation"], step["state"])
        operation_index = OPERATION_ORDER.get(operation)
        if operation_index is None:
            errors.append(
                _step_error(
                    line_number,
                    case_id,
                    step_position,
                    "invalid phase, operation, state combination",
                )
            )
            continue
        valid_steps.append((step_position, step, operation_index))

    errors.extend(_step_order_errors(line_number, case_id, valid_steps))
    if deletion_status in VALID_STATUSES:
        errors.extend(_status_errors(line_number, case_id, deletion_status, steps, valid_steps))
    return errors


def _parsed_steps(steps_json: str) -> list[object] | None:
    try:
        parsed = typing.cast("object", json.loads(steps_json, parse_constant=_reject_constant))
    except ValueError:
        return None
    if not isinstance(parsed, list):
        return None
    return typing.cast("list[object]", parsed)


def _step_with_shape(raw_step: object) -> Step | None:
    if not isinstance(raw_step, dict):
        return None
    raw_fields = typing.cast("dict[str, object]", raw_step)
    if frozenset(raw_fields) != STEP_FIELDS:
        return None
    step_no = raw_fields["step_no"]
    if not isinstance(step_no, int) or isinstance(step_no, bool):
        return None
    for field in STEP_FIELDS - {"step_no"}:
        value = raw_fields[field]
        if not isinstance(value, str):
            return None
    return typing.cast("Step", raw_fields)


def _evidence_errors(
    line_number: int,
    case_id: str,
    step_position: int,
    evidence_id: str,
    audit_times: Mapping[str, datetime],
    evidence_times: Mapping[str, datetime],
) -> list[str]:
    if not evidence_id:
        return []
    evidence_time = evidence_times.get(evidence_id)
    if evidence_time is None:
        return [_step_error(line_number, case_id, step_position, "unknown evidence_id")]
    audit_time = audit_times.get(case_id)
    if audit_time is not None and evidence_time > audit_time:
        return [
            _step_error(line_number, case_id, step_position, "evidence_id is dated after audit_at")
        ]
    return []


def _step_order_errors(
    line_number: int,
    case_id: str,
    valid_steps: list[tuple[int, Step, int]],
) -> list[str]:
    errors: list[str] = []
    previous_key: tuple[int, str, str] | None = None
    for step_position, step, operation_index in valid_steps:
        order_key = (operation_index, step["system_id"], step["resource_id"])
        if previous_key is not None and order_key < previous_key:
            errors.append(
                _step_error(line_number, case_id, step_position, "steps are not in canonical order")
            )
        previous_key = order_key
    return errors


def _status_errors(
    line_number: int,
    case_id: str,
    deletion_status: str,
    steps: list[object],
    valid_steps: list[tuple[int, Step, int]],
) -> list[str]:
    if deletion_status == "NOT_APPLICABLE":
        if steps:
            return [_row_error(line_number, case_id, "NOT_APPLICABLE must have steps_json []")]
        return []
    if not steps:
        return [_row_error(line_number, case_id, f"{deletion_status} must have at least one step")]

    errors: list[str] = []
    for step_position, step, _ in valid_steps:
        if deletion_status == "COMPLETE":
            if step["phase"] != VERIFICATION_PHASE:
                errors.append(
                    _step_error(
                        line_number, case_id, step_position, "COMPLETE steps must be VERIFICATION"
                    )
                )
            if not step["evidence_id"]:
                errors.append(
                    _step_error(
                        line_number, case_id, step_position, "COMPLETE steps must cite evidence"
                    )
                )
        elif step["phase"] == FINDING_PHASE and not step["evidence_id"]:
            errors.append(
                _step_error(
                    line_number, case_id, step_position, "INCOMPLETE findings must cite evidence"
                )
            )
        elif step["phase"] in {REMEDIATION_PHASE, VERIFICATION_PHASE} and step["evidence_id"]:
            errors.append(
                _step_error(
                    line_number,
                    case_id,
                    step_position,
                    "INCOMPLETE remediation and verification steps must not cite evidence",
                )
            )
    return errors


def _reject_constant(constant: str) -> typing.NoReturn:
    raise ValueError(constant)


def _row_error(line_number: int, case_id: str, message: str) -> str:
    return f"line {line_number} ({case_id}): {message}"


def _step_error(line_number: int, case_id: str, step_position: int, message: str) -> str:
    return _row_error(line_number, case_id, f"step {step_position}: {message}")


def _sort_errors(case_positions: list[tuple[int, int, str]]) -> list[str]:
    errors: list[str] = []
    previous_number = -1
    for number, line_number, case_id in case_positions:
        if number < previous_number:
            errors.append(_row_error(line_number, case_id, "rows are not sorted by case number"))
        previous_number = number
    return errors
