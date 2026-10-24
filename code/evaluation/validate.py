from __future__ import annotations

import csv
import json
import typing

if typing.TYPE_CHECKING:
    from collections.abc import Collection
    from pathlib import Path

HEADER = ("case_id", "deletion_status", "steps_json")
VALID_STATUSES = frozenset({"COMPLETE", "INCOMPLETE", "NOT_APPLICABLE"})


def validation_errors(predictions_path: Path, case_ids: Collection[str]) -> list[str]:
    """Return every validation error in a predictions CSV."""
    try:
        rows = csv_rows(predictions_path)
    except OSError, UnicodeDecodeError, csv.Error:
        return [f"cannot read {predictions_path}"]

    if not rows:
        return ["line 1: missing header"]

    errors: list[str] = []
    if tuple(rows[0]) != HEADER:
        errors.append(f"line 1: header must be {','.join(HEADER)}")

    requested_ids = set(case_ids)
    found_ids: set[str] = set()
    case_numbers: list[tuple[int, int, str]] = []
    for line_number, row in enumerate(rows[1:], start=2):
        case_id = row[0] if row else ""
        if len(row) != len(HEADER):
            errors.append(f"line {line_number} ({case_id}): expected {len(HEADER)} fields")
            continue
        if case_id in found_ids:
            errors.append(f"line {line_number} ({case_id}): duplicate case_id")
        found_ids.add(case_id)
        if case_id not in requested_ids:
            errors.append(f"line {line_number} ({case_id}): unexpected case_id")

        try:
            case_number = _case_number(case_id)
        except ValueError:
            errors.append(f"line {line_number} ({case_id}): malformed case_id")
        else:
            case_numbers.append((case_number, line_number, case_id))

        if row[1] not in VALID_STATUSES:
            errors.append(f"line {line_number} ({case_id}): invalid deletion_status")
        errors.extend(_steps_json_errors(line_number, case_id, row[2]))

    errors.extend(
        f"missing case_id: {case_id}"
        for case_id in sorted(requested_ids - found_ids, key=_case_number)
    )
    errors.extend(_sort_errors(case_numbers))
    return errors


def csv_rows(path: Path) -> list[list[str]]:
    """Return all rows in a UTF-8 CSV file."""
    with path.open(encoding="utf-8", newline="") as csv_file:
        return list(csv.reader(csv_file))


def data_rows(path: Path) -> list[list[str]]:
    """Return CSV rows after the header."""
    return csv_rows(path)[1:]


def _case_number(case_id: str) -> int:
    prefix = "case_"
    suffix = case_id.removeprefix(prefix)
    if suffix == case_id or not suffix.isdecimal():
        raise ValueError
    return int(suffix)


def _steps_json_errors(line_number: int, case_id: str, steps_json: str) -> list[str]:
    try:
        is_steps_array = isinstance(json.loads(steps_json), list)
    except json.JSONDecodeError:
        is_steps_array = False
    if not is_steps_array:
        return [f"line {line_number} ({case_id}): steps_json is not a JSON array"]
    return []


def _sort_errors(case_numbers: list[tuple[int, int, str]]) -> list[str]:
    errors: list[str] = []
    previous_number = -1
    for case_number, line_number, case_id in case_numbers:
        if case_number < previous_number:
            errors.append(f"line {line_number} ({case_id}): rows are not sorted by case number")
        previous_number = case_number
    return errors
