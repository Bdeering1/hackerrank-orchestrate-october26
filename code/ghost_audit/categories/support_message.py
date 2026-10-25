from __future__ import annotations

import typing

from ghost_audit.categories import Category, state_from_result
from ghost_audit.model import PRESENT, REDACTED

if typing.TYPE_CHECKING:
    from collections.abc import Mapping


REDACTED_MESSAGE = "[REDACTED]"
CONTACT_QUERY_COMPLETED = "contact_query_completed"
REQUESTER_IDENTIFIER_FIELDS = (
    "requester_name",
    "requester_email",
    "requester_phone",
    "matched_value",
)


def _existing_state(record: Mapping[str, object]) -> str:
    if record.get("event") == CONTACT_QUERY_COMPLETED:
        return PRESENT
    if (result_state := state_from_result(record)) is not None:
        return result_state
    if any(record.get(field) is not None for field in REQUESTER_IDENTIFIER_FIELDS):
        return PRESENT
    return PRESENT if record.get("message_text") not in (None, REDACTED_MESSAGE) else REDACTED


def _is_condition_met(record: Mapping[str, object]) -> bool:
    return record.get("event") != CONTACT_QUERY_COMPLETED


CATEGORY = Category(
    rule_category="SUPPORT_MESSAGE",
    default_system="support_platform",
    table_names=frozenset({"support_records"}),
    collection_names=frozenset({"tickets", "support_conversations"}),
    record_types=frozenset({"SUPPORT_MESSAGE"}),
    log_events=frozenset(
        {"support_ticket_read_completed", "message_pii_scan", CONTACT_QUERY_COMPLETED}
    ),
    existing_state=_existing_state,
    is_condition_met=_is_condition_met,
)
