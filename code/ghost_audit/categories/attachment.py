from ghost_audit.categories import Category, always_present_state, is_always_met

CATEGORY = Category(
    rule_category="SUPPORT_ATTACHMENT",
    default_system="support_platform",
    table_names=frozenset(),
    collection_names=frozenset({"ticket_attachments"}),
    record_types=frozenset({"SUPPORT_ATTACHMENT"}),
    log_events=frozenset({"attachment_pii_scan"}),
    existing_state=always_present_state,
    is_condition_met=is_always_met,
)
