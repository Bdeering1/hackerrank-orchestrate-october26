from __future__ import annotations

import typing

from ghost_audit.categories import Category
from ghost_audit.model import PRESENT, REDACTED

if typing.TYPE_CHECKING:
    from collections.abc import Mapping

_DIRECT_IDENTIFIERS = ("name", "email", "phone", "email_hash")


def _existing_state(record: Mapping[str, object]) -> str:
    if all(record.get(field) is None for field in _DIRECT_IDENTIFIERS):
        return REDACTED
    return PRESENT


CATEGORY = Category(
    rule_category="ACCOUNT_TOMBSTONE",
    default_system="identity_service",
    table_names=frozenset(),
    collection_names=frozenset({"deleted_customer_references"}),
    record_types=frozenset(),
    log_events=frozenset(),
    existing_state=_existing_state,
)
