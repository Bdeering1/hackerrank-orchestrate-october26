from __future__ import annotations

import argparse
import csv
import sys
import tempfile
import typing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from evaluation.runs import (
    FullSetPaths,
    PromotionRefusedError,
    RunFiles,
    promote_run,
    record_holdout_run,
    record_run,
)
from evaluation.score import case_scores, render_markdown
from evaluation.usage import format_usage_summary, usage_summary
from evaluation.validate import csv_rows, validation_errors
from ghost_audit.__main__ import DEFAULT_OUTPUT_PATH
from ghost_audit.__main__ import main as agent_main
from ghost_audit.output_format import case_number

if typing.TYPE_CHECKING:
    from collections.abc import Callable

DATASET_DIR = Path(__file__).resolve().parents[2] / "dataset"
CASES_DIR = Path(__file__).with_name("cases")
SAMPLE_LABELS_PATH = DATASET_DIR / "sample_output.csv"
SAMPLE_REQUESTS_PATH = DATASET_DIR / "sample_deletion_requests.csv"
FULL_REQUESTS_PATH = DATASET_DIR / "deletion_requests.csv"
CUSTOM_LABELS_PATH = CASES_DIR / "custom_output.csv"
CUSTOM_REQUESTS_PATH = CASES_DIR / "custom_requests.csv"
HOLDOUT_PATH = CASES_DIR / "holdout.txt"
EVIDENCE_FILES_PATH = DATASET_DIR / "evidence_files.csv"
SYSTEM_ACTIVITY_PATH = DATASET_DIR / "system_activity.csv"
AUDIT_LOG_PATH = DATASET_DIR / "user_audit_log.csv"


@dataclass(frozen=True)
class Suite:
    """Merged requests and labels for the cases one harness run evaluates."""

    is_holdout: bool
    requests_path: Path
    labels_path: Path


def main(argv: list[str]) -> int:
    """Run, score or promote suite predictions, or validate a full-set output."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", type=Path)
    parser.add_argument("--holdout", action="store_true")
    parser.add_argument("--full-set", action="store_true")
    subparsers = parser.add_subparsers(dest="command")
    promote_parser = subparsers.add_parser("promote")
    promote_parser.add_argument("run_id")
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("output_path", nargs="?", type=Path)
    arguments = _Arguments()
    parser.parse_args(argv, arguments)

    if arguments.full_set and (
        arguments.predictions is not None or arguments.holdout or arguments.command is not None
    ):
        parser.error("--full-set is only available for the default run")

    if arguments.command == "promote":
        return _promote(arguments.run_id)

    if arguments.command == "validate":
        return _validate_full_set(arguments.output_path or DEFAULT_OUTPUT_PATH)

    with tempfile.TemporaryDirectory() as temporary_directory:
        directory = Path(temporary_directory)
        suite = write_suite(directory, is_holdout=arguments.holdout)
        if arguments.predictions is not None:
            return _score_predictions(arguments.predictions, suite)

        output_path = directory / "output.csv"
        usage_path = directory / "usage.json"
        agent_exit_code = _run_agent(suite.requests_path, output_path, usage_path)
        if agent_exit_code != 0:
            return agent_exit_code
        if not arguments.full_set:
            return _score_predictions(output_path, suite, usage_path)

        if _report_validation_errors(output_path, audit_times(suite.requests_path)):
            return 1
        full_set_paths = FullSetPaths(directory / "full_output.csv", directory / "full_usage.json")
        agent_exit_code = _run_agent(FULL_REQUESTS_PATH, *full_set_paths)
        if agent_exit_code != 0:
            return agent_exit_code
        if _report_validation_errors(full_set_paths.output_path, audit_times(FULL_REQUESTS_PATH)):
            return 1
        return _score_predictions(output_path, suite, usage_path, full_set_paths)


def _run_agent(requests_path: Path, output_path: Path, usage_path: Path) -> int:
    return agent_main(
        [
            "--requests",
            str(requests_path),
            "--output",
            str(output_path),
            "--usage",
            str(usage_path),
        ]
    )


def holdout_case_ids() -> frozenset[str]:
    """Return the case IDs left out of default runs, promotion and prompt examples."""
    return frozenset(HOLDOUT_PATH.read_text(encoding="utf-8").split())


def write_suite(directory: Path, *, is_holdout: bool) -> Suite:
    """Write the holdout cases, or every other sample and custom case, into directory."""
    holdout_ids = holdout_case_ids()

    def is_selected(row: list[str]) -> bool:
        return (row[0] in holdout_ids) == is_holdout

    suite = Suite(is_holdout, directory / "requests.csv", directory / "labels.csv")
    _write_merged_rows(
        suite.requests_path, (SAMPLE_REQUESTS_PATH, CUSTOM_REQUESTS_PATH), is_selected
    )
    _write_merged_rows(suite.labels_path, (SAMPLE_LABELS_PATH, CUSTOM_LABELS_PATH), is_selected)
    return suite


def evidence_times() -> dict[str, datetime]:
    """Return when each citable file, activity and audit entry was recorded."""
    times = _times_from(EVIDENCE_FILES_PATH, "captured_at")
    times.update(_times_from(SYSTEM_ACTIVITY_PATH, "event_time"))
    times.update(_times_from(AUDIT_LOG_PATH, "event_time"))
    return times


def audit_times(requests_path: Path) -> dict[str, datetime]:
    """Return each request's audit_at cutoff by case ID."""
    return _times_from(requests_path, "audit_at")


def _write_merged_rows(
    output_path: Path, source_paths: tuple[Path, Path], is_selected: Callable[[list[str]], bool]
) -> None:
    header, *rows = csv_rows(source_paths[0])
    extra_header, *extra_rows = csv_rows(source_paths[1])
    if extra_header != header:
        raise ValueError(f"{source_paths[1]} columns differ from {source_paths[0]}")
    rows.extend(extra_rows)
    selected_rows = sorted(filter(is_selected, rows), key=lambda row: case_number(row[0]))
    with output_path.open("w", encoding="utf-8", newline="") as output_file:
        csv.writer(output_file).writerows([header, *selected_rows])


def _score_predictions(
    predictions_path: Path,
    suite: Suite,
    usage_path: Path | None = None,
    full_set_paths: FullSetPaths | None = None,
) -> int:
    """Validate predictions and render weighted suite scores."""
    request_audit_times = audit_times(suite.requests_path)
    if _report_validation_errors(predictions_path, request_audit_times):
        return 1

    scores_markdown = render_markdown(case_scores(predictions_path, suite.labels_path))
    sys.stdout.write(scores_markdown)
    if usage_path is None:
        return 0
    summary = usage_summary(usage_path, len(request_audit_times))
    sys.stdout.write(f"{format_usage_summary(summary)}\n")
    record = record_holdout_run if suite.is_holdout else record_run
    record(
        RunFiles(
            output_path=predictions_path,
            usage_path=usage_path,
            labels_path=suite.labels_path,
            scores_markdown=scores_markdown,
            full_set_paths=full_set_paths,
        )
    )
    return 0


def _validate_full_set(output_path: Path) -> int:
    """Validate an output file against the full request set without scoring."""
    request_audit_times = audit_times(FULL_REQUESTS_PATH)
    if _report_validation_errors(output_path, request_audit_times):
        return 1

    sys.stdout.write(f"{output_path}: {len(request_audit_times)} cases valid\n")
    return 0


def _report_validation_errors(
    predictions_path: Path, request_audit_times: dict[str, datetime]
) -> bool:
    """Write validation errors to stderr and return whether there were any."""
    errors = validation_errors(predictions_path, request_audit_times, evidence_times())
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


def _times_from(path: Path, time_column: str) -> dict[str, datetime]:
    header, *rows = csv_rows(path)
    time_index = header.index(time_column)
    return {row[0]: datetime.fromisoformat(row[time_index]) for row in rows}


class _Arguments(argparse.Namespace):
    predictions: Path | None
    holdout: bool
    full_set: bool
    command: str | None
    run_id: str
    output_path: Path | None


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
