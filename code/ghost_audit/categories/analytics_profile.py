from __future__ import annotations

import typing

from ghost_audit.categories import Category, has_any_field, is_always_met, state_from_result
from ghost_audit.model import ANONYMIZED, PRESENT

if typing.TYPE_CHECKING:
    from collections.abc import Mapping


ATTRIBUTION_FIELDS = (
    "user_id",
    "customer_reference",
    "email",
    "phone",
    "email_hash",
    "matched_value",
)


def _existing_state(record: Mapping[str, object]) -> str:
    if (result_state := state_from_result(record)) is not None:
        return result_state
    return PRESENT if has_any_field(record, ATTRIBUTION_FIELDS) else ANONYMIZED


CATEGORY = Category(
    rule_category="ANALYTICS_PROFILE",
    default_system="analytics_platform",
    table_names=frozenset({"customer_analytics_profiles"}),
    collection_names=frozenset({"profiles", "customer_analytics_reports"}),
    record_types=frozenset({"ANALYTICS_PROFILE"}),
    log_events=frozenset(
        {"analytics_profile_read_completed", "analytics_identity_scan", "analytics_profile_read"}
    ),
    existing_state=_existing_state,
    is_condition_met=is_always_met,
)
