from __future__ import annotations

import typing

from ghost_audit.categories import Category, has_falsey_value, state_from_result
from ghost_audit.model import ACTIVE, DISABLED

if typing.TYPE_CHECKING:
    from collections.abc import Mapping


def _existing_state(record: Mapping[str, object]) -> str:
    if "result" in record:
        return state_from_result(record, DISABLED)
    return DISABLED if has_falsey_value(record, "enabled") else ACTIVE


CATEGORY = Category(
    rule_category="DATA_FLOW",
    default_system="integration_service",
    table_names=frozenset({"connector_subscriptions"}),
    collection_names=frozenset({"connectors", "connector_configurations"}),
    record_types=frozenset({"DATA_FLOW"}),
    log_events=frozenset(
        {
            "connector_heartbeat",
            "connector_config_loaded",
            "connector_config_read_completed",
        }
    ),
    existing_state=_existing_state,
)
