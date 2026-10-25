from __future__ import annotations

import typing

from ghost_audit.categories import (
    Category,
    has_falsey_value,
    has_truthy_value,
    state_from_result,
)
from ghost_audit.model import ACTIVE, BLOCKED

if typing.TYPE_CHECKING:
    from collections.abc import Mapping


def _existing_state(record: Mapping[str, object]) -> str:
    if "result" in record:
        return state_from_result(record, BLOCKED)
    if "decision" in record:
        return BLOCKED if str(record["decision"]).casefold() == "deny" else ACTIVE
    if "restore_allowed" in record:
        return BLOCKED if has_falsey_value(record, "restore_allowed") else ACTIVE
    if "eligible" in record or "deletion_block" in record:
        is_restore_blocked = has_falsey_value(record, "eligible") or has_truthy_value(
            record, "deletion_block"
        )
        return BLOCKED if is_restore_blocked else ACTIVE
    return ACTIVE


CATEGORY = Category(
    rule_category="BACKUP_ARCHIVE",
    default_system="backup_service",
    table_names=frozenset({"backup_restore_entries"}),
    collection_names=frozenset({"restore_entries", "backup_catalog"}),
    record_types=frozenset({"BACKUP_ARCHIVE"}),
    log_events=frozenset(
        {
            "restore_candidate_evaluated",
            "restore_authorization_completed",
            "restore_policy_read_completed",
        }
    ),
    existing_state=_existing_state,
)
