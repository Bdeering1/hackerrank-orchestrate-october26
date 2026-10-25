import pytest

from ghost_audit.categories import backup, data_flow
from ghost_audit.model import ACTIVE, BLOCKED, DISABLED


@pytest.mark.parametrize(
    ("record", "expected_state"),
    [
        pytest.param({"result": "ACTIVE"}, ACTIVE, id="active ledger item"),
        pytest.param({"result": "DISABLED"}, DISABLED, id="disabled ledger item"),
        pytest.param({"enabled": 1}, ACTIVE, id="sql enabled integer"),
        pytest.param({"enabled": 0}, DISABLED, id="sql disabled integer"),
        pytest.param({"enabled": "true"}, ACTIVE, id="log enabled text"),
        pytest.param({"enabled": "false"}, DISABLED, id="log disabled text"),
        pytest.param({}, ACTIVE, id="missing enabled fails closed"),
        pytest.param({"result": None}, ACTIVE, id="null result fails closed"),
        pytest.param({"result": "UNKNOWN"}, ACTIVE, id="unknown result fails closed"),
    ],
)
def test_data_flow_state_comes_from_enabled_or_ledger_result(record, expected_state):
    assert data_flow.CATEGORY.existing_state(record) == expected_state


@pytest.mark.parametrize(
    ("record", "expected_state"),
    [
        pytest.param({"result": "ACTIVE"}, ACTIVE, id="active ledger item"),
        pytest.param({"result": "BLOCKED"}, BLOCKED, id="blocked ledger item"),
        pytest.param({"decision": "deny"}, BLOCKED, id="denied restore authorization"),
        pytest.param({"restore_allowed": 1}, ACTIVE, id="sql restore integer"),
        pytest.param({"restore_allowed": 0}, BLOCKED, id="sql block integer"),
        pytest.param({"restore_allowed": "true"}, ACTIVE, id="log restore text"),
        pytest.param({"restore_allowed": "false"}, BLOCKED, id="log block text"),
        pytest.param(
            {"eligible": "true", "deletion_block": "false"}, ACTIVE, id="eligible candidate"
        ),
        pytest.param(
            {"eligible": "false", "deletion_block": "false"}, BLOCKED, id="ineligible candidate"
        ),
        pytest.param(
            {"eligible": "true", "deletion_block": "true"}, BLOCKED, id="deletion blocked"
        ),
        pytest.param({"result": "UNKNOWN"}, ACTIVE, id="unknown result fails closed"),
        pytest.param({}, ACTIVE, id="missing restore fields fail closed"),
        pytest.param({"restore_allowed": None}, ACTIVE, id="null restore fails closed"),
        pytest.param({"decision": "allow"}, ACTIVE, id="allowed restore authorization"),
    ],
)
def test_backup_state_comes_from_restore_evidence(record, expected_state):
    assert backup.CATEGORY.existing_state(record) == expected_state
