from __future__ import annotations

import argparse
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from evaluation.score import case_scores, render_markdown
from evaluation.usage import format_usage_summary, usage_summary
from evaluation.validate import data_rows, validation_errors
from ghost_audit.__main__ import main as agent_main

DATASET_DIR = Path(__file__).resolve().parents[2] / "dataset"
LABELS_PATH = DATASET_DIR / "sample_output.csv"
REQUESTS_PATH = DATASET_DIR / "sample_deletion_requests.csv"
EVIDENCE_FILES_PATH = DATASET_DIR / "evidence_files.csv"
SYSTEM_ACTIVITY_PATH = DATASET_DIR / "system_activity.csv"
AUDIT_LOG_PATH = DATASET_DIR / "user_audit_log.csv"


def main(argv: list[str]) -> int:
    """Run or validate sample predictions and render weighted scores."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", type=Path)
    arguments = _Arguments()
    parser.parse_args(argv, arguments)

    if arguments.predictions is not None:
        return _score_predictions(arguments.predictions)

    with tempfile.TemporaryDirectory() as temporary_directory:
        output_path = Path(temporary_directory) / "output.csv"
        usage_path = Path(temporary_directory) / "usage.json"
        agent_exit_code = agent_main(
            [
                "--requests",
                str(REQUESTS_PATH),
                "--output",
                str(output_path),
                "--usage",
                str(usage_path),
            ]
        )
        if agent_exit_code != 0:
            return agent_exit_code
        return _score_predictions(output_path, usage_path)


def _score_predictions(predictions_path: Path, usage_path: Path | None = None) -> int:
    """Validate predictions and render weighted sample scores."""
    audit_times = _times_from(REQUESTS_PATH, 5)
    errors = validation_errors(predictions_path, audit_times, _evidence_times())
    if errors:
        sys.stderr.write("validation failed:\n")
        for error in errors:
            sys.stderr.write(f"{error}\n")
        return 1

    sys.stdout.write(render_markdown(case_scores(predictions_path, LABELS_PATH)))
    if usage_path is not None:
        summary = usage_summary(usage_path, len(audit_times))
        sys.stdout.write(f"{format_usage_summary(summary)}\n")
    return 0


def _evidence_times() -> dict[str, datetime]:
    evidence_times = _times_from(EVIDENCE_FILES_PATH, 3)
    evidence_times.update(_times_from(SYSTEM_ACTIVITY_PATH, 1))
    evidence_times.update(_times_from(AUDIT_LOG_PATH, 2))
    return evidence_times


def _times_from(path: Path, timestamp_index: int) -> dict[str, datetime]:
    return {row[0]: datetime.fromisoformat(row[timestamp_index]) for row in data_rows(path)}


class _Arguments(argparse.Namespace):
    predictions: Path | None


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
