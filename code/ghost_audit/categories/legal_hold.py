from __future__ import annotations

from ghost_audit.categories import Category, always_present_state, is_always_met

CATEGORY = Category(
    rule_category="LEGAL_HOLD_RECORD",
    default_system="legal_service",
    table_names=frozenset(),
    collection_names=frozenset({"retained_order_records"}),
    record_types=frozenset({"LEGAL_HOLD_RECORD"}),
    log_events=frozenset(),
    existing_state=always_present_state,
    is_condition_met=is_always_met,
    retention_end_field="retained_until",
)
