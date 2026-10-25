from __future__ import annotations

import argparse
import csv
import pathlib
import sys

import ghost_audit.usage

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_REQUESTS_PATH = REPO_ROOT / "dataset" / "deletion_requests.csv"
DEFAULT_OUTPUT_PATH = REPO_ROOT / "output.csv"
HEADER = ("case_id", "deletion_status", "steps_json")


def main(argv: list[str]) -> int:
    """Write placeholder deletion-audit results and optional usage data."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests", type=pathlib.Path, default=DEFAULT_REQUESTS_PATH)
    parser.add_argument("--output", type=pathlib.Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--usage", type=pathlib.Path)
    arguments = _Arguments()
    parser.parse_args(argv, arguments)

    _write_placeholder_output(arguments.requests, arguments.output)
    if arguments.usage is not None:
        ghost_audit.usage.UsageTracker().write(arguments.usage)
    return 0


def _write_placeholder_output(requests_path: pathlib.Path, output_path: pathlib.Path) -> None:
    with (
        requests_path.open(encoding="utf-8", newline="") as requests_file,
        output_path.open("w", encoding="utf-8", newline="") as output_file,
    ):
        requests = csv.DictReader(requests_file)
        case_ids = sorted((request["case_id"] for request in requests), key=case_number)
        writer = csv.writer(output_file)
        writer.writerow(HEADER)
        writer.writerows((case_id, "NOT_APPLICABLE", "[]") for case_id in case_ids)


def case_number(case_id: str) -> int:
    """Return the numeric portion of a well-formed case ID."""
    suffix = case_id.removeprefix("case_")
    if suffix == case_id or not suffix.isdecimal():
        raise ValueError
    return int(suffix)


class _Arguments(argparse.Namespace):
    requests: pathlib.Path
    output: pathlib.Path
    usage: pathlib.Path | None


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
