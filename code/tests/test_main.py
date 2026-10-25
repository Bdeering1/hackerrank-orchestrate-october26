import csv
import json
from datetime import datetime
from pathlib import Path

import pytest

import ghost_audit.llm
from evaluation.validate import data_rows, validation_errors
from ghost_audit.__main__ import main
from tests.fakes import (
    NO_DELETE_MARKER,
    FakeTransport,
    decide_intent,
    fail_to_connect,
    fake_connect,
)

DATASET_DIR = Path(__file__).resolve().parent / "fixtures" / "dataset"
REQUESTS_PATH = DATASET_DIR / "deletion_requests.csv"
ACCOUNT_SYSTEM = "account_service"
SECURITY_SYSTEM = "security_service"
IDENTITY_SYSTEM = "identity_service"
LEGAL_SYSTEM = "legal_service"
RETENTION_EVIDENCE_ID = "evidence_101"
SUPPORT_SYSTEM = "support_platform"
ANALYTICS_SYSTEM = "analytics_platform"
SEARCH_SYSTEM = "search_service"


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


def _verified_steps(
    resource_id: str,
    evidence_id: str,
    operation: str = "VERIFY_RECORD_ABSENT",
    state: str = "ABSENT",
    system_id: str = ACCOUNT_SYSTEM,
) -> list[dict[str, object]]:
    return [_step(1, "VERIFICATION", resource_id, operation, state, evidence_id, system_id)]


def _treatment_steps(
    system_id: str,
    resource_id: str,
    evidence_id: str,
    remediation: str,
    verification: str,
    end_state: str,
    finding: str = "REPORT_EXPOSED_PII",
) -> list[dict[str, object]]:
    return [
        _step(1, "FINDING", resource_id, finding, "PRESENT", evidence_id, system_id),
        _step(2, "REMEDIATION", resource_id, remediation, end_state, "", system_id),
        _step(3, "VERIFICATION", resource_id, verification, end_state, "", system_id),
    ]


def _remaining_record_steps(
    resource_id: str, evidence_id: str, system_id: str = ACCOUNT_SYSTEM
) -> list[dict[str, object]]:
    return _treatment_steps(
        system_id,
        resource_id,
        evidence_id,
        "DELETE_RECORD",
        "VERIFY_RECORD_ABSENT",
        "ABSENT",
        finding="REPORT_REMAINING_RECORD",
    )


@pytest.fixture(scope="module")
def run(tmp_path_factory: pytest.TempPathFactory) -> tuple[int, Path]:
    output_dir = tmp_path_factory.mktemp("output")
    with pytest.MonkeyPatch.context() as monkeypatch:
        connect = fake_connect(FakeTransport(decide_intent), output_dir / "llm-cache")
        monkeypatch.setattr(ghost_audit.llm, "connect", connect)
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
    # Every fixture request shares one text, so intent routing makes one call.
    assert json.loads((output_dir / "usage.json").read_text(encoding="utf-8")) == {
        "models": [
            {
                "provider": "anthropic",
                "model": "claude-haiku-5.5",
                "calls": 1,
                "input_tokens": 3,
                "output_tokens": 5,
            }
        ]
    }
    assert validation_errors(output_dir / "output.csv", audit_times, evidence_times) == []


@pytest.mark.parametrize(
    ("case_id", "expected_status", "expected_steps"),
    [
        pytest.param(
            "case_01",
            "INCOMPLETE",
            _remaining_record_steps("account_101", "evidence_01"),
            id="replica copy remains",
        ),
        pytest.param(
            "case_02",
            "COMPLETE",
            _verified_steps("account_202", "evidence_02"),
            id="historical email linked by log trace",
        ),
        pytest.param(
            "case_03",
            "COMPLETE",
            _verified_steps("account_303", "evidence_02"),
            id="snapshot after audit_at ignored",
        ),
        pytest.param(
            "case_04",
            "INCOMPLETE",
            _remaining_record_steps("account_303", "evidence_03"),
            id="snapshot before audit_at applies",
        ),
        pytest.param(
            "case_05", "NOT_APPLICABLE", [], id="no linked account, catalog link after audit_at"
        ),
        pytest.param(
            "case_06",
            "INCOMPLETE",
            _remaining_record_steps("account_303", "evidence_02"),
            id="latest record uncitable, latest citable evidence cited",
        ),
        pytest.param(
            "case_07",
            "INCOMPLETE",
            _remaining_record_steps("account_505", "evidence_04"),
            id="service export lookup found",
        ),
        pytest.param(
            "case_08",
            "COMPLETE",
            _verified_steps("account_606", "evidence_04"),
            id="catalog link to service export lookup not found",
        ),
        pytest.param(
            "case_09",
            "COMPLETE",
            _verified_steps("account_707", "evidence_05"),
            id="bracketed log trace",
        ),
        pytest.param(
            "case_10",
            "COMPLETE",
            _verified_steps("account_808", "evidence_05"),
            id="pipe log trace",
        ),
        pytest.param(
            "case_11",
            "COMPLETE",
            _verified_steps("account_909", "evidence_05"),
            id="syslog trace with uppercase email",
        ),
        pytest.param(
            "case_12",
            "COMPLETE",
            _verified_steps("account_1010", "evidence_05"),
            id="json log trace",
        ),
        pytest.param(
            "case_13",
            "INCOMPLETE",
            _remaining_record_steps("account_1111", "evidence_06"),
            id="inventory sql snapshot",
        ),
        pytest.param(
            "case_14",
            "COMPLETE",
            _verified_steps("account_1212", "evidence_07"),
            id="text handover record",
        ),
        pytest.param(
            "case_15",
            "INCOMPLETE",
            _remaining_record_steps("account_1313", "evidence_09"),
            id="record found only in uncitable log, earlier citable record cited",
        ),
        pytest.param(
            "case_16",
            "COMPLETE",
            _verified_steps("account_1414", "evidence_03"),
            id="later snapshot omits earlier record",
        ),
        pytest.param(
            "case_17",
            "INCOMPLETE",
            [
                *_remaining_record_steps("account_1515", "evidence_09"),
                _step(
                    4,
                    "VERIFICATION",
                    "search_4618",
                    "VERIFY_RECORD_ABSENT",
                    "ABSENT",
                    "",
                    SEARCH_SYSTEM,
                ),
            ],
            id="json replica row remains, search entry gone in evidence_15 snapshot",
        ),
        pytest.param(
            "case_18",
            "INCOMPLETE",
            _remaining_record_steps("account_1616", "evidence_10"),
            id="json ledger record found",
        ),
        pytest.param(
            "case_19",
            "COMPLETE",
            _verified_steps("account_1717", "evidence_11"),
            id="log ledger record not found",
        ),
        pytest.param(
            "case_20",
            "COMPLETE",
            _verified_steps("account_1819", "evidence_02"),
            id="account deleted before an earlier request ignored",
        ),
        pytest.param(
            "case_22",
            "COMPLETE",
            _verified_steps("account_2121", "evidence_06"),
            id="nominated account absent from snapshot",
        ),
        pytest.param("case_23", "NOT_APPLICABLE", [], id="ambiguous nomination"),
        pytest.param(
            "case_24",
            "COMPLETE",
            _verified_steps("account_2424", "evidence_06"),
            id="nominee linked to another user ruled out",
        ),
        pytest.param(
            "case_25",
            "COMPLETE",
            _verified_steps("account_2525", "evidence_06"),
            id="nominee matches reported result",
        ),
        pytest.param(
            "case_26",
            "COMPLETE",
            _verified_steps("account_2626", "evidence_06"),
            id="no nominee matches reported result",
        ),
        pytest.param(
            "case_27",
            "COMPLETE",
            _verified_steps("account_2727", "evidence_06"),
            id="nomination window earliest edge",
        ),
        pytest.param(
            "case_28",
            "COMPLETE",
            _verified_steps("account_2828", "evidence_06"),
            id="targeted nomination window earliest edge",
        ),
        pytest.param(
            "case_29",
            "COMPLETE",
            _verified_steps("account_2929", "evidence_06"),
            id="nomination after audit_at ignored",
        ),
        pytest.param(
            "case_30",
            "COMPLETE",
            _verified_steps("account_3030", "evidence_06"),
            id="other activity never nominates",
        ),
        pytest.param(
            "case_32",
            "COMPLETE",
            _verified_steps("account_3232", "evidence_06"),
            id="links after audit_at never rule out a nominee",
        ),
        pytest.param(
            "case_33",
            "COMPLETE",
            _verified_steps("account_3333", "evidence_06"),
            id="nomination window latest edge",
        ),
        pytest.param(
            "case_34",
            "COMPLETE",
            _verified_steps("account_3434", "evidence_06"),
            id="targeted nomination window latest edge",
        ),
        pytest.param(
            "case_101",
            "COMPLETE",
            _verified_steps(
                "audit_record_2101",
                RETENTION_EVIDENCE_ID,
                "VERIFY_RECORD_PRESENT",
                "PRESENT",
                SECURITY_SYSTEM,
            ),
            id="retained security audit record",
        ),
        pytest.param(
            "case_102",
            "INCOMPLETE",
            _remaining_record_steps("audit_record_2202", RETENTION_EVIDENCE_ID, SECURITY_SYSTEM),
            id="expired security audit record",
        ),
        pytest.param(
            "case_103",
            "COMPLETE",
            _verified_steps(
                "legal_hold_2303",
                RETENTION_EVIDENCE_ID,
                "VERIFY_RECORD_PRESENT",
                "PRESENT",
                LEGAL_SYSTEM,
            ),
            id="retained legal hold record",
        ),
        pytest.param(
            "case_104",
            "COMPLETE",
            _verified_steps(
                "tombstone_2505",
                RETENTION_EVIDENCE_ID,
                "VERIFY_RECORD_REDACTED",
                "REDACTED",
                IDENTITY_SYSTEM,
            ),
            id="clean tombstone",
        ),
        pytest.param(
            "case_105",
            "INCOMPLETE",
            _treatment_steps(
                IDENTITY_SYSTEM,
                "tombstone_2606",
                RETENTION_EVIDENCE_ID,
                "REDACT_RECORD",
                "VERIFY_RECORD_REDACTED",
                "REDACTED",
            ),
            id="tombstone exposing some identifiers",
        ),
        pytest.param(
            "case_106",
            "COMPLETE",
            _verified_steps(
                "audit_record_2808",
                RETENTION_EVIDENCE_ID,
                "VERIFY_RECORD_PRESENT",
                "PRESENT",
                SECURITY_SYSTEM,
            ),
            id="retained record remains compliant when a later snapshot omits it",
        ),
        pytest.param(
            "case_107",
            "INCOMPLETE",
            _verified_steps(
                "audit_record_3210", "", "VERIFY_RECORD_PRESENT", "PRESENT", SECURITY_SYSTEM
            ),
            id="retained record explicitly absent",
        ),
    ],
)
def test_main_audits_records(run, case_id, expected_status, expected_steps):
    _, output_dir = run
    output_rows = {
        row[0]: (row[1], json.loads(row[2])) for row in data_rows(output_dir / "output.csv")
    }

    assert output_rows[case_id] == (expected_status, expected_steps)


@pytest.mark.parametrize(
    ("case_id", "expected_status", "expected_steps"),
    [
        pytest.param(
            "case_35",
            "INCOMPLETE",
            _treatment_steps(
                SUPPORT_SYSTEM,
                "support_2101",
                "evidence_13",
                "REDACT_RECORD",
                "VERIFY_RECORD_REDACTED",
                "REDACTED",
            ),
            id="support message exposes direct identifiers",
        ),
        pytest.param(
            "case_36",
            "COMPLETE",
            _verified_steps(
                "support_2201", "evidence_13", "VERIFY_RECORD_REDACTED", "REDACTED", SUPPORT_SYSTEM
            ),
            id="redacted support message retains stable reference",
        ),
        pytest.param(
            "case_37",
            "INCOMPLETE",
            _treatment_steps(
                ANALYTICS_SYSTEM,
                "analytics_2301",
                "evidence_13",
                "ANONYMIZE_RECORD",
                "VERIFY_RECORD_ANONYMIZED",
                "ANONYMIZED",
            ),
            id="analytics profile exposes direct identifiers",
        ),
        pytest.param(
            "case_38",
            "INCOMPLETE",
            _remaining_record_steps("support_2401", "evidence_13", SUPPORT_SYSTEM),
            id="contact index lookup does not retain shared context",
        ),
        pytest.param(
            "case_39",
            "INCOMPLETE",
            _remaining_record_steps("analytics_2501", "evidence_13", ANALYTICS_SYSTEM),
            id="analytics contact lookup is a marketing profile",
        ),
        pytest.param(
            "case_40",
            "COMPLETE",
            _verified_steps(
                "support_2601", "evidence_14", "VERIFY_RECORD_REDACTED", "REDACTED", SUPPORT_SYSTEM
            ),
            id="later snapshot omission does not erase retained support record",
        ),
        pytest.param(
            "case_41",
            "INCOMPLETE",
            _treatment_steps(
                ANALYTICS_SYSTEM,
                "analytics_2701",
                "evidence_13",
                "ANONYMIZE_RECORD",
                "VERIFY_RECORD_ANONYMIZED",
                "ANONYMIZED",
            ),
            id="analytics profile user id remains attributable",
        ),
        pytest.param(
            "case_42",
            "INCOMPLETE",
            _treatment_steps(
                SUPPORT_SYSTEM,
                "support_2801",
                "evidence_13",
                "REDACT_RECORD",
                "VERIFY_RECORD_REDACTED",
                "REDACTED",
            ),
            id="contact index hit remains present after a redacted ticket read",
        ),
        pytest.param(
            "case_43",
            "INCOMPLETE",
            _treatment_steps(
                SUPPORT_SYSTEM,
                "support_2901",
                "evidence_07",
                "REDACT_RECORD",
                "VERIFY_RECORD_REDACTED",
                "REDACTED",
            ),
            id="ledger identifiable support message is exposed",
        ),
        pytest.param(
            "case_44",
            "INCOMPLETE",
            _treatment_steps(
                ANALYTICS_SYSTEM,
                "analytics_3001",
                "evidence_07",
                "ANONYMIZE_RECORD",
                "VERIFY_RECORD_ANONYMIZED",
                "ANONYMIZED",
            ),
            id="ledger identifiable analytics profile is exposed",
        ),
        pytest.param(
            "case_45",
            "COMPLETE",
            _verified_steps(
                "support_3101", "evidence_07", "VERIFY_RECORD_REDACTED", "REDACTED", SUPPORT_SYSTEM
            ),
            id="ledger redacted support message is compliant",
        ),
    ],
)
def test_main_audits_support_and_analytics_records(run, case_id, expected_status, expected_steps):
    _, output_dir = run
    output_rows = {
        row[0]: (row[1], json.loads(row[2])) for row in data_rows(output_dir / "output.csv")
    }

    assert output_rows[case_id] == (expected_status, expected_steps)


@pytest.mark.parametrize(
    ("case_id", "expected_status", "expected_steps"),
    [
        pytest.param(
            "case_46",
            "INCOMPLETE",
            _remaining_record_steps("search_201", "evidence_15", SEARCH_SYSTEM),
            id="search index entry remains",
        ),
        pytest.param(
            "case_47",
            "INCOMPLETE",
            _remaining_record_steps("export_301", "evidence_15", "export_service"),
            id="export remains with download unavailable",
        ),
        pytest.param(
            "case_48",
            "INCOMPLETE",
            _remaining_record_steps("support_401", "evidence_15", SUPPORT_SYSTEM),
            id="ticket attachment remains",
        ),
        pytest.param(
            "case_49",
            "COMPLETE",
            _verified_steps("search_501", "evidence_15", system_id=SEARCH_SYSTEM),
            id="search index entry dropped from later snapshot",
        ),
        pytest.param(
            "case_50",
            "INCOMPLETE",
            _remaining_record_steps("search_601", "evidence_02", SEARCH_SYSTEM),
            id="later partial snapshot never listed the search entry",
        ),
    ],
)
def test_main_audits_search_export_and_attachment_records(
    run, case_id, expected_status, expected_steps
):
    _, output_dir = run
    output_rows = {
        row[0]: (row[1], json.loads(row[2])) for row in data_rows(output_dir / "output.csv")
    }

    assert output_rows[case_id] == (expected_status, expected_steps)


def test_main_skips_audit_for_requests_that_do_not_authorize_deletion(tmp_path: Path) -> None:
    requests_path = tmp_path / "deletion_requests.csv"
    output_path = tmp_path / "output.csv"
    _write_requests_with_text(requests_path, "case_01", f"{NO_DELETE_MARKER} send me a copy")

    assert main(_main_arguments(requests_path, output_path)) == 0

    output_rows = {row[0]: (row[1], row[2]) for row in data_rows(output_path)}
    assert output_rows["case_01"] == ("NOT_APPLICABLE", "[]")
    assert output_rows["case_02"][0] == "COMPLETE"


def test_main_keeps_existing_output_when_intent_routing_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_path = tmp_path / "output.csv"
    output_path.write_text("previous output", encoding="utf-8")
    connect = fake_connect(FakeTransport(fail_to_connect), tmp_path / "llm-cache", max_attempts=1)
    monkeypatch.setattr(ghost_audit.llm, "connect", connect)

    assert main(_main_arguments(REQUESTS_PATH, output_path)) == 1

    assert output_path.read_text(encoding="utf-8") == "previous output"


def _main_arguments(requests_path: Path, output_path: Path) -> list[str]:
    return [
        "--dataset",
        str(DATASET_DIR),
        "--requests",
        str(requests_path),
        "--output",
        str(output_path),
    ]


def _write_requests_with_text(path: Path, case_id: str, request_text: str) -> None:
    with REQUESTS_PATH.open(encoding="utf-8", newline="") as requests_file:
        requests = list(csv.DictReader(requests_file))
    for request in requests:
        if request["case_id"] == case_id:
            request["request_text"] = request_text
    with path.open("w", encoding="utf-8", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=list(requests[0]))
        writer.writeheader()
        writer.writerows(requests)
