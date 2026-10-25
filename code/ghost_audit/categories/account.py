from __future__ import annotations

from ghost_audit.categories import Category, present_state

CATEGORY = Category(
    rule_category="USER_PROFILE",
    default_system="account_service",
    table_names=frozenset({"customer_profiles"}),
    collection_names=frozenset({"customer_profiles", "profile_lookups"}),
    record_types=frozenset({"USER_PROFILE"}),
    log_events=frozenset({"profile_lookup_completed"}),
    existing_state=present_state,
)
