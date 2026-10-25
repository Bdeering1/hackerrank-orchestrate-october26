from __future__ import annotations

import csv
import json
import typing

from ghost_audit.output_format import HEADER, case_number

if typing.TYPE_CHECKING:
    from collections.abc import Collection
    from pathlib import Path

VALID_STATUSES = frozenset({"COMPLETE", "INCOMPLETE", "NOT_APPLICABLE"})


def validation_errors(predictions_path: Path, case_ids: Collection[str]) -> list[str]:
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

    requested_ids = set(case_ids)
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

        if row[1] not in VALID_STATUSES:
            errors.append(_row_error(line_number, case_id, "invalid deletion_status"))
        errors.extend(_steps_json_errors(line_number, case_id, row[2]))

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


def _steps_json_errors(line_number: int, case_id: str, steps_json: str) -> list[str]:
    try:
        is_steps_array = isinstance(json.loads(steps_json, parse_constant=_reject_constant), list)
    except ValueError:
        is_steps_array = False
    if not is_steps_array:
        return [_row_error(line_number, case_id, "steps_json is not a JSON array")]
    return []


def _reject_constant(constant: str) -> typing.NoReturn:
    raise ValueError(constant)


def _row_error(line_number: int, case_id: str, message: str) -> str:
    return f"line {line_number} ({case_id}): {message}"


def _sort_errors(case_positions: list[tuple[int, int, str]]) -> list[str]:
    errors: list[str] = []
    previous_number = -1
    for number, line_number, case_id in case_positions:
        if number < previous_number:
            errors.append(_row_error(line_number, case_id, "rows are not sorted by case number"))
        previous_number = number
    return errors
