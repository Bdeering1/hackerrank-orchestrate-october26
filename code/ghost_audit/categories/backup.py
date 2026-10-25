from __future__ import annotations

import typing

from ghost_audit.categories import Category, is_truthy
from ghost_audit.model import ACTIVE, BLOCKED

if typing.TYPE_CHECKING:
    from collections.abc import Mapping


def _existing_state(record: Mapping[str, object]) -> str:
    can_restore = is_truthy(record.get("restore_allowed")) or (
        is_truthy(record.get("eligible")) and not is_truthy(record.get("deletion_block"))
    )
    if can_restore or record.get("result") == ACTIVE:
        return ACTIVE
    return BLOCKED


CATEGORY = Category(
    rule_category="BACKUP_ARCHIVE",
    default_system="backup_service",
    table_names=frozenset({"backup_restore_entries"}),
    collection_names=frozenset({"restore_entries", "backup_catalog"}),
    record_types=frozenset({"BACKUP_ARCHIVE"}),
    log_events=frozenset(
        {
            "restore_policy_read_completed",
            "restore_candidate_evaluated",
            "restore_authorization_completed",
        }
    ),
    existing_state=_existing_state,
)
