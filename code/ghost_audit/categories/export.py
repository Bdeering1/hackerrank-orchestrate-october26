from __future__ import annotations

from ghost_audit.categories import Category, present_state

CATEGORY = Category(
    rule_category="USER_EXPORT",
    default_system="export_service",
    table_names=frozenset({"customer_exports"}),
    collection_names=frozenset({"customer_export_jobs", "exports"}),
    record_types=frozenset({"USER_EXPORT"}),
    log_events=frozenset({"export_metadata_read_completed", "export_download_check_completed"}),
    existing_state=present_state,
)
