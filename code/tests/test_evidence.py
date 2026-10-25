from pathlib import Path

import pytest

from ghost_audit.dataset import loaded_dataset
from ghost_audit.model import ACTIVE, BLOCKED, DISABLED

DATASET_DIR = Path(__file__).resolve().parent / "fixtures" / "dataset"


@pytest.mark.parametrize(
    ("resource_id", "expected_state"),
    [
        pytest.param("data_flow_101", ACTIVE, id="sql-integer-enabled"),
        pytest.param("backup_202", BLOCKED, id="sql-integer-restore-blocked"),
        pytest.param("data_flow_json", ACTIVE, id="json-boolean-enabled"),
        pytest.param("backup_json", BLOCKED, id="json-boolean-restore-blocked"),
        pytest.param("data_flow_log", ACTIVE, id="log-string-enabled"),
        pytest.param("backup_log", BLOCKED, id="log-string-restore-blocked"),
        pytest.param("data_flow_ledger", DISABLED, id="ledger-result-disabled"),
        pytest.param("backup_ledger", ACTIVE, id="ledger-result-active"),
    ],
)
def test_evidence_states_for_data_flows_and_backups(resource_id: str, expected_state: str) -> None:
    observations = loaded_dataset(DATASET_DIR).evidence.observations
    observed_state = next(
        observation.state for observation in observations if observation.resource_id == resource_id
    )

    assert observed_state == expected_state
