from ghost_audit.categories import Category, always_present_state, is_always_met

CATEGORY = Category(
    rule_category="MARKETING_PROFILE",
    default_system="analytics_platform",
    table_names=frozenset(),
    collection_names=frozenset(),
    record_types=frozenset({"MARKETING_PROFILE"}),
    log_events=frozenset({"contact_lookup_completed"}),
    existing_state=always_present_state,
    is_condition_met=is_always_met,
)
