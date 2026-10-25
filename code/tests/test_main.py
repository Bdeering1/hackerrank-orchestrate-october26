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
    step_no: int,
    phase: str,
    resource_id: str,
    operation: str,
    state: str,
    evidence_id: str,
    system_id: str = ACCOUNT_SYSTEM,
) -> dict[str, object]:
    return {
        "step_no": step_no,
        "phase": phase,
        "system_id": system_id,
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


def _remaining_steps(resource_id: str, system_id: str) -> list[dict[str, object]]:
    return [
        _step(
            1,
            "FINDING",
            resource_id,
            "REPORT_REMAINING_RECORD",
            "PRESENT",
            "evidence_13",
            system_id,
        ),
        _step(2, "REMEDIATION", resource_id, "DELETE_RECORD", "ABSENT", "", system_id),
        _step(3, "VERIFICATION", resource_id, "VERIFY_RECORD_ABSENT", "ABSENT", "", system_id),
    ]


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
            _remaining_account_steps("account_1313", "evidence_09"),
            id="record found only in uncitable log, earlier citable record cited",
        ),
        pytest.param(
            "case_16",
            "COMPLETE",
            _absent_account_steps("account_1414", "evidence_03"),
            id="later snapshot omits earlier record",
        ),
        pytest.param(
            "case_17",
            "INCOMPLETE",
            _remaining_account_steps("account_1515", "evidence_09"),
            id="json replica row remains",
        ),
        pytest.param(
            "case_18",
            "INCOMPLETE",
            _remaining_account_steps("account_1616", "evidence_10"),
            id="json ledger record found",
        ),
        pytest.param(
            "case_19",
            "COMPLETE",
            _absent_account_steps("account_1717", "evidence_11"),
            id="log ledger record not found",
        ),
        pytest.param(
            "case_20",
            "COMPLETE",
            _absent_account_steps("account_1819", "evidence_02"),
            id="account deleted before an earlier request ignored",
        ),
    ],
)
def test_main_audits_account_records(run, case_id, expected_status, expected_steps):
    _, output_dir = run
    output_rows = {
        row[0]: (row[1], json.loads(row[2])) for row in data_rows(output_dir / "output.csv")
    }

    assert output_rows[case_id] == (expected_status, expected_steps)


@pytest.mark.parametrize(
    ("case_id", "expected_status", "expected_steps"),
    [
        pytest.param(
            "case_21",
            "COMPLETE",
            [
                _step(
                    1,
                    "VERIFICATION",
                    "audit_record_2101",
                    "VERIFY_RECORD_PRESENT",
                    "PRESENT",
                    "evidence_13",
                    "security_service",
                )
            ],
            id="retained security audit record",
        ),
        pytest.param(
            "case_22",
            "INCOMPLETE",
            _remaining_steps("audit_record_2202", "security_service"),
            id="expired security audit record",
        ),
        pytest.param(
            "case_23",
            "COMPLETE",
            [
                _step(
                    1,
                    "VERIFICATION",
                    "legal_hold_2303",
                    "VERIFY_RECORD_PRESENT",
                    "PRESENT",
                    "evidence_13",
                    "legal_service",
                )
            ],
            id="retained legal hold record",
        ),
        pytest.param(
            "case_24",
            "INCOMPLETE",
            _remaining_steps("legal_hold_2404", "legal_service"),
            id="expired legal hold record",
        ),
        pytest.param(
            "case_25",
            "COMPLETE",
            [
                _step(
                    1,
                    "VERIFICATION",
                    "tombstone_2505",
                    "VERIFY_RECORD_REDACTED",
                    "REDACTED",
                    "evidence_13",
                    "identity_service",
                )
            ],
            id="clean tombstone",
        ),
        pytest.param(
            "case_26",
            "INCOMPLETE",
            [
                _step(
                    1,
                    "FINDING",
                    "tombstone_2606",
                    "REPORT_EXPOSED_PII",
                    "PRESENT",
                    "evidence_13",
                    "identity_service",
                ),
                _step(
                    2,
                    "REMEDIATION",
                    "tombstone_2606",
                    "REDACT_RECORD",
                    "REDACTED",
                    "",
                    "identity_service",
                ),
                _step(
                    3,
                    "VERIFICATION",
                    "tombstone_2606",
                    "VERIFY_RECORD_REDACTED",
                    "REDACTED",
                    "",
                    "identity_service",
                ),
            ],
            id="tombstone exposing identifiers",
        ),
        pytest.param(
            "case_28",
            "COMPLETE",
            [
                _step(
                    1,
                    "VERIFICATION",
                    "audit_record_2808",
                    "VERIFY_RECORD_PRESENT",
                    "PRESENT",
                    "evidence_13",
                    "security_service",
                )
            ],
            id="retained record remains compliant when a later snapshot omits it",
        ),
        pytest.param(
            "case_29",
            "INCOMPLETE",
            _remaining_steps("audit_record_2909", "security_service"),
            id="retention expires after the request",
        ),
        pytest.param(
            "case_30",
            "COMPLETE",
            _absent_account_steps("account_omitted", "evidence_06"),
            id="account absence predates its uncitable lookup",
        ),
        pytest.param(
            "case_31",
            "COMPLETE",
            [
                _step(
                    1,
                    "VERIFICATION",
                    "tombstone_3101",
                    "VERIFY_RECORD_REDACTED",
                    "REDACTED",
                    "evidence_13",
                    "identity_service",
                )
            ],
            id="tombstone remains compliant when a later snapshot omits it",
        ),
        pytest.param(
            "case_32",
            "INCOMPLETE",
            [
                _step(
                    1,
                    "VERIFICATION",
                    "audit_record_3210",
                    "VERIFY_RECORD_PRESENT",
                    "PRESENT",
                    "",
                    "security_service",
                )
            ],
            id="retained record explicitly absent",
        ),
        pytest.param(
            "case_34",
            "COMPLETE",
            [
                _step(
                    1,
                    "VERIFICATION",
                    "audit_record_3411",
                    "VERIFY_RECORD_PRESENT",
                    "PRESENT",
                    "evidence_13",
                    "security_service",
                )
            ],
            id="retained record observed before request",
        ),
    ],
)
def test_main_audits_retained_records_and_tombstones(run, case_id, expected_status, expected_steps):
    _, output_dir = run
    output_rows = {
        row[0]: (row[1], json.loads(row[2])) for row in data_rows(output_dir / "output.csv")
    }

    assert output_rows[case_id] == (expected_status, expected_steps)
