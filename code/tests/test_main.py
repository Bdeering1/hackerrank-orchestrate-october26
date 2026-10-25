import csv
import json
from pathlib import Path

import pytest

import ghost_audit.__main__
import ghost_audit.llm
from evaluation.validate import data_rows, validation_errors
from ghost_audit.__main__ import main
from ghost_audit.llm import StructuredLLM
from ghost_audit.usage import UsageTracker
from tests.fakes import FakeTransport, fail_to_connect

REQUESTS_PATH = Path(__file__).resolve().parents[2] / "dataset" / "sample_deletion_requests.csv"


def test_main_writes_valid_output_for_samples(tmp_path: Path) -> None:
    output_path = tmp_path / "output.csv"

    assert main(["--requests", str(REQUESTS_PATH), "--output", str(output_path)]) == 0

    assert validation_errors(output_path, [row[0] for row in data_rows(REQUESTS_PATH)]) == []


def test_main_routes_non_deletion_and_deletion_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests_path = tmp_path / "requests.csv"
    output_path = tmp_path / "output.csv"
    _write_requests(
        requests_path,
        [
            ("case_02", "NO_DELETE send me a copy"),
            ("case_01", "Please delete my account"),
        ],
    )
    monkeypatch.setattr(
        ghost_audit.__main__,
        "_audit_deletion_request",
        lambda _request: ("COMPLETE", "[]"),
    )

    assert main(["--requests", str(requests_path), "--output", str(output_path)]) == 0

    assert _read_output(output_path) == [
        ["case_id", "deletion_status", "steps_json"],
        ["case_01", "COMPLETE", "[]"],
        ["case_02", "NOT_APPLICABLE", "[]"],
    ]


def test_main_writes_usage_for_one_call_per_distinct_text(tmp_path: Path) -> None:
    requests_path = tmp_path / "requests.csv"
    output_path = tmp_path / "output.csv"
    usage_path = tmp_path / "usage.json"
    _write_requests(
        requests_path,
        [
            ("case_01", "Please delete my account"),
            ("case_02", "NO_DELETE send me a copy"),
            ("case_03", "Please delete my account"),
        ],
    )

    assert (
        main(
            [
                "--requests",
                str(requests_path),
                "--output",
                str(output_path),
                "--usage",
                str(usage_path),
            ]
        )
        == 0
    )

    assert json.loads(usage_path.read_text(encoding="utf-8")) == {
        "models": [
            {
                "provider": "anthropic",
                "model": "claude-haiku-5.5",
                "calls": 2,
                "input_tokens": 6,
                "output_tokens": 10,
            }
        ]
    }


def test_main_keeps_existing_output_when_intent_routing_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests_path = tmp_path / "requests.csv"
    output_path = tmp_path / "output.csv"
    _write_requests(requests_path, [("case_01", "Please delete my account")])
    output_path.write_text("previous output", encoding="utf-8")

    def connect(usage_tracker: UsageTracker) -> StructuredLLM:
        return StructuredLLM(
            FakeTransport(fail_to_connect),
            usage_tracker,
            tmp_path / "llm-cache",
            max_attempts=1,
        )

    monkeypatch.setattr(ghost_audit.llm, "connect", connect)

    assert main(["--requests", str(requests_path), "--output", str(output_path)]) == 1

    assert output_path.read_text(encoding="utf-8") == "previous output"


def _write_requests(path: Path, rows: list[tuple[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as requests_file:
        writer = csv.DictWriter(requests_file, fieldnames=["case_id", "request_text"])
        writer.writeheader()
        writer.writerows({"case_id": case_id, "request_text": text} for case_id, text in rows)


def _read_output(path: Path) -> list[list[str]]:
    with path.open(encoding="utf-8", newline="") as output_file:
        return list(csv.reader(output_file))
