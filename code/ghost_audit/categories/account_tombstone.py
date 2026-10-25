from __future__ import annotations

import typing

from ghost_audit.categories import Category, has_any_field, is_always_met
from ghost_audit.model import PRESENT, REDACTED

if typing.TYPE_CHECKING:
    from collections.abc import Mapping

_DIRECT_IDENTIFIERS = ("name", "email", "phone", "email_hash")


def _existing_state(record: Mapping[str, object]) -> str:
    return PRESENT if has_any_field(record, _DIRECT_IDENTIFIERS) else REDACTED


CATEGORY = Category(
    rule_category="ACCOUNT_TOMBSTONE",
    default_system="identity_service",
    table_names=frozenset(),
    collection_names=frozenset({"deleted_customer_references"}),
    record_types=frozenset(),
    log_events=frozenset(),
    existing_state=_existing_state,
    is_condition_met=is_always_met,
)
