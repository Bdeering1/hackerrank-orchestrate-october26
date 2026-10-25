from __future__ import annotations

import argparse
import asyncio
import csv
import dataclasses
import json
import pathlib
import sys
import typing

import ghost_audit.intent
import ghost_audit.llm
import ghost_audit.usage
from ghost_audit.audit import NOT_APPLICABLE, Auditor
from ghost_audit.dataset import DELETION_REQUESTS_FILE_NAME, csv_records, loaded_dataset
from ghost_audit.output_format import HEADER, case_number

if typing.TYPE_CHECKING:
    from ghost_audit.model import Step

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_DATASET_DIR = REPO_ROOT / "dataset"
DEFAULT_OUTPUT_PATH = REPO_ROOT / "output.csv"


def main(argv: list[str]) -> int:
    """Audit every deletion request and write the results and optional usage data."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=pathlib.Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--requests", type=pathlib.Path)
    parser.add_argument("--output", type=pathlib.Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--usage", type=pathlib.Path)
    parser.add_argument("--no-cache", action="store_false", dest="is_cache_enabled")
    arguments = _Arguments()
    parser.parse_args(argv, arguments)

    requests_path = arguments.requests or arguments.dataset / DELETION_REQUESTS_FILE_NAME
    requests = sorted(
        csv_records(requests_path), key=lambda request: case_number(request["case_id"])
    )
    dataset = loaded_dataset(arguments.dataset)
    tracker = ghost_audit.usage.UsageTracker()
    try:
        llm = ghost_audit.llm.connect(tracker, is_cache_enabled=arguments.is_cache_enabled)
        # The auditor also needs the intent of each subject's earlier requests.
        authorizations = asyncio.run(
            ghost_audit.intent.classify_intents(
                llm, (request["request_text"] for request in (*requests, *dataset.requests))
            )
        )
    except ghost_audit.llm.LLMError as error:
        sys.stderr.write(f"intent routing failed: {error}\n")
        return 1

    auditor = Auditor(dataset, authorizations)
    with arguments.output.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.writer(output_file)
        writer.writerow(HEADER)
        for request in requests:
            if not authorizations[request["request_text"]]:
                writer.writerow((request["case_id"], NOT_APPLICABLE, "[]"))
                continue
            status, steps = auditor.audited_case(request)
            writer.writerow((request["case_id"], status, _steps_json(steps)))
    if arguments.usage is not None:
        tracker.write(arguments.usage)
    return 0


def _steps_json(steps: list[Step]) -> str:
    numbered_steps = [
        {"step_no": step_no, **dataclasses.asdict(step)}
        for step_no, step in enumerate(steps, start=1)
    ]
    return json.dumps(numbered_steps, sort_keys=True, separators=(",", ":"))


class _Arguments(argparse.Namespace):
    dataset: pathlib.Path
    requests: pathlib.Path | None
    output: pathlib.Path
    usage: pathlib.Path | None
    is_cache_enabled: bool


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
