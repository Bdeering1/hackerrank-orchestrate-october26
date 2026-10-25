from pathlib import Path

import pytest

from ghost_audit.dataset import loaded_dataset
from ghost_audit.model import ACTIVE, BLOCKED, Observation

DATASET_DIR = Path(__file__).resolve().parent / "fixtures" / "dataset"


@pytest.fixture(scope="module")
def observations() -> tuple[Observation, ...]:
    return loaded_dataset(DATASET_DIR).evidence.observations


@pytest.mark.parametrize(
    ("resource_id", "expected_state"),
    [
        pytest.param("data_flow_json", ACTIVE, id="json-boolean-enabled"),
        pytest.param("backup_json", BLOCKED, id="json-boolean-restore-blocked"),
        pytest.param("data_flow_log", ACTIVE, id="log-string-enabled"),
        pytest.param("backup_log", BLOCKED, id="log-string-restore-blocked"),
        pytest.param("backup_eligible", ACTIVE, id="log-eligible-without-deletion-block"),
        pytest.param("backup_deletion_block", BLOCKED, id="log-eligible-with-deletion-block"),
        pytest.param("data_flow_ledger", ACTIVE, id="ledger-result-active-flow"),
        pytest.param("backup_ledger", ACTIVE, id="ledger-result-active-backup"),
    ],
)
def test_evidence_states_for_data_flows_and_backups(
    observations: tuple[Observation, ...], resource_id: str, expected_state: str
) -> None:
    observed_state = next(
        observation.state for observation in observations if observation.resource_id == resource_id
    )

    assert observed_state == expected_state
