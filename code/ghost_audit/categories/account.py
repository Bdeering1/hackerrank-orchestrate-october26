from __future__ import annotations

import typing

from ghost_audit.categories import Category
from ghost_audit.model import PRESENT

if typing.TYPE_CHECKING:
    from collections.abc import Mapping


def _existing_state(_record: Mapping[str, object]) -> str:
    return PRESENT


CATEGORY = Category(
    rule_category="USER_PROFILE",
    default_system="account_service",
    evidence_names=frozenset(
        {"customer_profiles", "profile_lookups", "USER_PROFILE", "profile_lookup_completed"}
    ),
    existing_state=_existing_state,
)
