import json
from pathlib import Path

from evaluation.validate import data_rows, validation_errors
from ghost_audit.__main__ import main


def test_main_writes_placeholder_output(tmp_path: Path) -> None:
    requests_path = Path(__file__).resolve().parents[2] / "dataset" / "sample_deletion_requests.csv"
    output_path = tmp_path / "output.csv"
    usage_path = tmp_path / "usage.json"

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

    assert validation_errors(output_path, [row[0] for row in data_rows(requests_path)]) == []
    assert json.loads(usage_path.read_text(encoding="utf-8")) == {"models": []}
