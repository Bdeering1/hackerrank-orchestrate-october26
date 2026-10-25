from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from evaluation.score import status_match_counts
from evaluation.usage import format_usage_summary, usage_summary
from evaluation.validate import data_rows, validation_errors
from ghost_audit.__main__ import main as agent_main

DATASET_DIR = Path(__file__).resolve().parents[2] / "dataset"
LABELS_PATH = DATASET_DIR / "sample_output.csv"
REQUESTS_PATH = DATASET_DIR / "sample_deletion_requests.csv"


def main(argv: list[str]) -> int:
    """Run or validate sample predictions and report status accuracy."""
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
    """Validate predictions and report sample status accuracy."""
    requested_case_ids = _requested_case_ids()
    errors = validation_errors(predictions_path, requested_case_ids)
    if errors:
        sys.stderr.write("validation failed:\n")
        for error in errors:
            sys.stderr.write(f"{error}\n")
        return 1

    match_count, case_count = status_match_counts(predictions_path, LABELS_PATH)
    percentage = match_count / case_count * 100
    sys.stdout.write(f"status accuracy: {match_count}/{case_count} ({percentage:.1f}%)\n")
    if usage_path is not None:
        summary = usage_summary(usage_path, len(requested_case_ids))
        sys.stdout.write(f"{format_usage_summary(summary)}\n")
    return 0


def _requested_case_ids() -> list[str]:
    return [row[0] for row in data_rows(REQUESTS_PATH)]


class _Arguments(argparse.Namespace):
    predictions: Path | None


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
