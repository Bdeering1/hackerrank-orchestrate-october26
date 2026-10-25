import json
from datetime import datetime
from pathlib import Path

import pytest

from evaluation.validate import data_rows, validation_errors
from ghost_audit.__main__ import main

DATASET_DIR = Path(__file__).resolve().parent / "fixtures" / "dataset"
REQUESTS_PATH = DATASET_DIR / "deletion_requests.csv"
ACCOUNT_SYSTEM = "account_service"


def _step(
    step_no: int, phase: str, resource_id: str, operation: str, state: str, evidence_id: str
) -> dict[str, object]:
    return {
        "step_no": step_no,
        "phase": phase,
        "system_id": ACCOUNT_SYSTEM,
        "resource_id": resource_id,
        "operation": operation,
        "state": state,
        "evidence_id": evidence_id,
    }


def _remaining_account_steps(resource_id: str, evidence_id: str) -> list[dict[str, object]]:
    return [
        _step(1, "FINDING", resource_id, "REPORT_REMAINING_RECORD", "PRESENT", evidence_id),
        _step(2, "REMEDIATION", resource_id, "DELETE_RECORD", "ABSENT", ""),
        _step(3, "VERIFICATION", resource_id, "VERIFY_RECORD_ABSENT", "ABSENT", ""),
    ]


def _absent_account_steps(resource_id: str, evidence_id: str) -> list[dict[str, object]]:
    return [_step(1, "VERIFICATION", resource_id, "VERIFY_RECORD_ABSENT", "ABSENT", evidence_id)]


@pytest.fixture(scope="module")
def run(tmp_path_factory: pytest.TempPathFactory) -> tuple[int, Path]:
    output_dir = tmp_path_factory.mktemp("output")
    exit_code = main(
        [
            "--dataset",
            str(DATASET_DIR),
            "--output",
            str(output_dir / "output.csv"),
            "--usage",
            str(output_dir / "usage.json"),
        ]
    )
    return exit_code, output_dir


def test_main_writes_valid_output_and_usage(run):
    exit_code, output_dir = run
    audit_times = {row[0]: datetime.fromisoformat(row[5]) for row in data_rows(REQUESTS_PATH)}
    evidence_times = {
        row[0]: datetime.fromisoformat(row[3])
        for row in data_rows(DATASET_DIR / "evidence_files.csv")
    }

    assert exit_code == 0
    assert json.loads((output_dir / "usage.json").read_text(encoding="utf-8")) == {"models": []}
    assert validation_errors(output_dir / "output.csv", audit_times, evidence_times) == []


@pytest.mark.parametrize(
    ("case_id", "expected_status", "expected_steps"),
    [
        pytest.param(
            "case_01",
            "INCOMPLETE",
            _remaining_account_steps("account_101", "evidence_01"),
            id="replica copy remains",
        ),
        pytest.param(
            "case_02",
            "COMPLETE",
            _absent_account_steps("account_202", "evidence_02"),
            id="historical email linked by log trace",
        ),
        pytest.param(
            "case_03",
            "COMPLETE",
            _absent_account_steps("account_303", "evidence_02"),
            id="snapshot after audit_at ignored",
        ),
        pytest.param(
            "case_04",
            "INCOMPLETE",
            _remaining_account_steps("account_303", "evidence_03"),
            id="snapshot before audit_at applies",
        ),
        pytest.param(
            "case_05", "NOT_APPLICABLE", [], id="no linked account, catalog link after audit_at"
        ),
        pytest.param(
            "case_06",
            "INCOMPLETE",
            _remaining_account_steps("account_303", "evidence_02"),
            id="latest record uncitable, latest citable evidence cited",
        ),
        pytest.param(
            "case_07",
            "INCOMPLETE",
            _remaining_account_steps("account_505", "evidence_04"),
            id="service export lookup found",
        ),
        pytest.param(
            "case_08",
            "COMPLETE",
            _absent_account_steps("account_606", "evidence_04"),
            id="catalog link to service export lookup not found",
        ),
        pytest.param(
            "case_09",
            "COMPLETE",
            _absent_account_steps("account_707", "evidence_05"),
            id="bracketed log trace",
        ),
        pytest.param(
            "case_10",
            "COMPLETE",
            _absent_account_steps("account_808", "evidence_05"),
            id="pipe log trace",
        ),
        pytest.param(
            "case_11",
            "COMPLETE",
            _absent_account_steps("account_909", "evidence_05"),
            id="syslog trace with uppercase email",
        ),
        pytest.param(
            "case_12",
            "COMPLETE",
            _absent_account_steps("account_1010", "evidence_05"),
            id="json log trace",
        ),
        pytest.param(
            "case_13",
            "INCOMPLETE",
            _remaining_account_steps("account_1111", "evidence_06"),
            id="inventory sql snapshot",
        ),
        pytest.param(
            "case_14",
            "COMPLETE",
            _absent_account_steps("account_1212", "evidence_07"),
            id="text handover record",
        ),
        pytest.param(
            "case_15",
            "INCOMPLETE",
            _remaining_account_steps("account_1313", "evidence_02"),
            id="uncitable replica copy remains, phone linked by log trace",
        ),
    ],
)
def test_main_audits_account_records(run, case_id, expected_status, expected_steps):
    _, output_dir = run
    output_rows = {
        row[0]: (row[1], json.loads(row[2])) for row in data_rows(output_dir / "output.csv")
    }

    assert output_rows[case_id] == (expected_status, expected_steps)
