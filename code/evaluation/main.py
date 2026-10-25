import argparse
import sys
from pathlib import Path

from evaluation.score import status_match_counts
from evaluation.validate import data_rows, validation_errors

DATASET_DIR = Path(__file__).resolve().parents[2] / "dataset"
LABELS_PATH = DATASET_DIR / "sample_output.csv"
REQUESTS_PATH = DATASET_DIR / "sample_deletion_requests.csv"


def main(argv: list[str]) -> int:
    """Validate predictions and report sample status accuracy."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", type=Path, default=LABELS_PATH)
    arguments = _Arguments()
    parser.parse_args(argv, arguments)
    predictions_path = arguments.predictions

    errors = validation_errors(predictions_path, _requested_case_ids())
    if errors:
        sys.stderr.write("validation failed:\n")
        for error in errors:
            sys.stderr.write(f"{error}\n")
        return 1

    match_count, case_count = status_match_counts(predictions_path, LABELS_PATH)
    percentage = match_count / case_count * 100
    sys.stdout.write(f"status accuracy: {match_count}/{case_count} ({percentage:.1f}%)\n")
    return 0


def _requested_case_ids() -> list[str]:
    return [row[0] for row in data_rows(REQUESTS_PATH)]


class _Arguments(argparse.Namespace):
    predictions: Path


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
