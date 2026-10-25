import json
from datetime import datetime
from pathlib import Path

from evaluation.validate import data_rows, validation_errors
from ghost_audit.__main__ import main

REQUESTS_PATH = Path(__file__).resolve().parents[2] / "dataset" / "sample_deletion_requests.csv"


def test_main_writes_placeholder_output(tmp_path: Path) -> None:
    output_path = tmp_path / "output.csv"
    usage_path = tmp_path / "usage.json"

    assert (
        main(
            [
                "--requests",
                str(REQUESTS_PATH),
                "--output",
                str(output_path),
                "--usage",
                str(usage_path),
            ]
        )
        == 0
    )

    audit_times = {row[0]: datetime.fromisoformat(row[5]) for row in data_rows(REQUESTS_PATH)}
    assert validation_errors(output_path, audit_times, evidence_times={}) == []
    assert json.loads(usage_path.read_text(encoding="utf-8")) == {"models": []}
