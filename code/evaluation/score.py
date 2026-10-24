from __future__ import annotations

import typing

from evaluation.validate import data_rows

if typing.TYPE_CHECKING:
    from pathlib import Path


def status_match_counts(predictions_path: Path, labels_path: Path) -> tuple[int, int]:
    """Return matching statuses and total labelled cases."""
    predictions = _statuses_by_case(predictions_path)
    labels = _statuses_by_case(labels_path)
    match_count = sum(
        predictions.get(case_id) == deletion_status for case_id, deletion_status in labels.items()
    )
    return match_count, len(labels)


def _statuses_by_case(path: Path) -> dict[str, str]:
    return {row[0]: row[1] for row in data_rows(path)}
