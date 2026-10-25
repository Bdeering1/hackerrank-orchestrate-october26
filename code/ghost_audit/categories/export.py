from ghost_audit.categories import Category, always_present_state, is_always_met

CATEGORY = Category(
    rule_category="USER_EXPORT",
    default_system="export_service",
    table_names=frozenset({"customer_exports"}),
    collection_names=frozenset({"customer_export_jobs", "exports"}),
    record_types=frozenset({"USER_EXPORT"}),
    log_events=frozenset({"export_metadata_read_completed", "export_download_check_completed"}),
    existing_state=always_present_state,
    is_condition_met=is_always_met,
)
