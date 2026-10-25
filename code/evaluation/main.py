from __future__ import annotations

import argparse
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from evaluation.runs import PromotionRefusedError, promote_run, record_run
from evaluation.score import case_scores, render_markdown
from evaluation.usage import format_usage_summary, usage_summary
from evaluation.validate import csv_rows, validation_errors
from ghost_audit.__main__ import DEFAULT_OUTPUT_PATH
from ghost_audit.__main__ import main as agent_main

DATASET_DIR = Path(__file__).resolve().parents[2] / "dataset"
LABELS_PATH = DATASET_DIR / "sample_output.csv"
REQUESTS_PATH = DATASET_DIR / "sample_deletion_requests.csv"
FULL_REQUESTS_PATH = DATASET_DIR / "deletion_requests.csv"
EVIDENCE_FILES_PATH = DATASET_DIR / "evidence_files.csv"
SYSTEM_ACTIVITY_PATH = DATASET_DIR / "system_activity.csv"
AUDIT_LOG_PATH = DATASET_DIR / "user_audit_log.csv"


def main(argv: list[str]) -> int:
    """Run, score or promote sample predictions, or validate a full-set output."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", type=Path)
    subparsers = parser.add_subparsers(dest="command")
    promote_parser = subparsers.add_parser("promote")
    promote_parser.add_argument("run_id")
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("path", nargs="?", type=Path)
    arguments = _Arguments()
    parser.parse_args(argv, arguments)

    if arguments.command == "promote":
        return _promote(arguments.run_id)

    if arguments.command == "validate":
        return _validate_full_set(arguments.path or DEFAULT_OUTPUT_PATH)

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
    audit_times = _times_from(REQUESTS_PATH, "audit_at")
    if _report_validation_errors(predictions_path, audit_times):
        return 1

    scores_markdown = render_markdown(case_scores(predictions_path, LABELS_PATH))
    sys.stdout.write(scores_markdown)
    if usage_path is None:
        return 0
    summary = usage_summary(usage_path, len(audit_times))
    sys.stdout.write(f"{format_usage_summary(summary)}\n")
    record_run(predictions_path, usage_path, LABELS_PATH, scores_markdown)
    return 0


def _validate_full_set(output_path: Path) -> int:
    """Validate an output file against the full request set without scoring."""
    audit_times = _times_from(FULL_REQUESTS_PATH, "audit_at")
    if _report_validation_errors(output_path, audit_times):
        return 1

    sys.stdout.write(f"{output_path}: {len(audit_times)} cases valid\n")
    return 0


def _report_validation_errors(predictions_path: Path, audit_times: dict[str, datetime]) -> bool:
    """Write validation errors to stderr and return whether there were any."""
    errors = validation_errors(predictions_path, audit_times, _evidence_times())
    if not errors:
        return False

    sys.stderr.write("validation failed:\n")
    for error in errors:
        sys.stderr.write(f"{error}\n")
    return True


def _promote(run_id: str) -> int:
    try:
        promote_run(run_id)
    except PromotionRefusedError as error:
        sys.stderr.write(f"{error}\n")
        return 1
    sys.stdout.write(f"Run {run_id}: promoted\n")
    return 0


def _evidence_times() -> dict[str, datetime]:
    evidence_times = _times_from(EVIDENCE_FILES_PATH, "captured_at")
    evidence_times.update(_times_from(SYSTEM_ACTIVITY_PATH, "event_time"))
    evidence_times.update(_times_from(AUDIT_LOG_PATH, "event_time"))
    return evidence_times


def _times_from(path: Path, time_column: str) -> dict[str, datetime]:
    header, *rows = csv_rows(path)
    time_index = header.index(time_column)
    return {row[0]: datetime.fromisoformat(row[time_index]) for row in rows}


class _Arguments(argparse.Namespace):
    predictions: Path | None
    command: str | None
    run_id: str
    path: Path | None


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
