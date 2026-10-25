from __future__ import annotations

from ghost_audit.categories import Category, always_present_state, is_always_met

CATEGORY = Category(
    rule_category="SECURITY_AUDIT_LOG",
    default_system="security_service",
    table_names=frozenset({"security_audit_records"}),
    collection_names=frozenset({"audit_records", "security_audit_events"}),
    record_types=frozenset({"SECURITY_AUDIT_LOG"}),
    log_events=frozenset({"audit_record_read_completed"}),
    existing_state=always_present_state,
    is_condition_met=is_always_met,
    retention_end_field="retention_until",
)
