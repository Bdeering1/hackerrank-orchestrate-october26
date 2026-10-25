from __future__ import annotations

import typing

from ghost_audit.categories import Category, is_truthy
from ghost_audit.model import ACTIVE, DISABLED

if typing.TYPE_CHECKING:
    from collections.abc import Mapping


def _existing_state(record: Mapping[str, object]) -> str:
    if is_truthy(record.get("enabled")) or record.get("result") == ACTIVE:
        return ACTIVE
    return DISABLED


CATEGORY = Category(
    rule_category="DATA_FLOW",
    default_system="integration_service",
    table_names=frozenset({"connector_subscriptions"}),
    collection_names=frozenset({"connectors", "connector_configurations"}),
    record_types=frozenset({"DATA_FLOW"}),
    log_events=frozenset(
        {"connector_config_read_completed", "connector_heartbeat", "connector_config_loaded"}
    ),
    existing_state=_existing_state,
)
