from __future__ import annotations

import argparse
import asyncio
import csv
import pathlib
import sys

import ghost_audit.intent
import ghost_audit.llm
import ghost_audit.usage
from ghost_audit.output_format import HEADER, case_number

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_REQUESTS_PATH = REPO_ROOT / "dataset" / "deletion_requests.csv"
DEFAULT_OUTPUT_PATH = REPO_ROOT / "output.csv"


def main(argv: list[str]) -> int:
    """Route requests by intent and write placeholder audit results."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests", type=pathlib.Path, default=DEFAULT_REQUESTS_PATH)
    parser.add_argument("--output", type=pathlib.Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--usage", type=pathlib.Path)
    arguments = _Arguments()
    parser.parse_args(argv, arguments)

    requests = _read_requests(arguments.requests)
    tracker = ghost_audit.usage.UsageTracker()
    try:
        llm = ghost_audit.llm.connect(tracker)
        authorizations = asyncio.run(
            ghost_audit.intent.classify_intents(
                llm, (request["request_text"] for request in requests)
            )
        )
    except ghost_audit.llm.LLMError as error:
        sys.stderr.write(f"intent routing failed: {error}\n")
        return 1

    _write_output(requests, authorizations, arguments.output)
    if arguments.usage is not None:
        tracker.write(arguments.usage)
    return 0


def _read_requests(requests_path: pathlib.Path) -> list[dict[str, str]]:
    with requests_path.open(encoding="utf-8", newline="") as requests_file:
        requests = [dict(request) for request in csv.DictReader(requests_file)]
    return sorted(requests, key=lambda request: case_number(request["case_id"]))


def _write_output(
    requests: list[dict[str, str]], authorizations: dict[str, bool], output_path: pathlib.Path
) -> None:
    with output_path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.writer(output_file)
        writer.writerow(HEADER)
        for request in requests:
            request_text = request["request_text"]
            if not authorizations[request_text]:
                writer.writerow((request["case_id"], "NOT_APPLICABLE", "[]"))
                continue
            writer.writerow((request["case_id"], *_audit_deletion_request(request)))


def _audit_deletion_request(_request: dict[str, str]) -> tuple[str, str]:
    return "NOT_APPLICABLE", "[]"


class _Arguments(argparse.Namespace):
    requests: pathlib.Path
    output: pathlib.Path
    usage: pathlib.Path | None


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
