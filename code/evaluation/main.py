from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from evaluation.score import case_scores, render_markdown
from evaluation.validate import data_rows, validation_errors

DATASET_DIR = Path(__file__).resolve().parents[2] / "dataset"
LABELS_PATH = DATASET_DIR / "sample_output.csv"
REQUESTS_PATH = DATASET_DIR / "sample_deletion_requests.csv"
EVIDENCE_FILES_PATH = DATASET_DIR / "evidence_files.csv"
SYSTEM_ACTIVITY_PATH = DATASET_DIR / "system_activity.csv"
AUDIT_LOG_PATH = DATASET_DIR / "user_audit_log.csv"


def main(argv: list[str]) -> int:
    """Validate predictions and render weighted sample scores."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", type=Path, default=LABELS_PATH)
    arguments = _Arguments()
    parser.parse_args(argv, arguments)
    predictions_path = arguments.predictions

    errors = validation_errors(predictions_path, _audit_times(), _evidence_times())
    if errors:
        sys.stderr.write("validation failed:\n")
        for error in errors:
            sys.stderr.write(f"{error}\n")
        return 1

    sys.stdout.write(render_markdown(case_scores(predictions_path, LABELS_PATH)))
    return 0


def _audit_times() -> dict[str, datetime]:
    return {row[0]: _timestamp(row[5]) for row in data_rows(REQUESTS_PATH)}


def _evidence_times() -> dict[str, datetime]:
    evidence_times = _times_from(EVIDENCE_FILES_PATH, 3)
    evidence_times.update(_times_from(SYSTEM_ACTIVITY_PATH, 1))
    evidence_times.update(_times_from(AUDIT_LOG_PATH, 2))
    return evidence_times


def _times_from(path: Path, timestamp_index: int) -> dict[str, datetime]:
    return {row[0]: _timestamp(row[timestamp_index]) for row in data_rows(path)}


def _timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)


class _Arguments(argparse.Namespace):
    predictions: Path


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
