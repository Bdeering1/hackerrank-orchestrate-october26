from __future__ import annotations

HEADER = ("case_id", "deletion_status", "steps_json")


def case_number(case_id: str) -> int:
    """Return the numeric portion of a well-formed case ID."""
    suffix = case_id.removeprefix("case_")
    if suffix == case_id or not suffix.isdecimal():
        raise ValueError
    return int(suffix)
