from __future__ import annotations

from ghost_audit.categories import Category, present_state

CATEGORY = Category(
    rule_category="LEGAL_HOLD_RECORD",
    default_system="legal_service",
    table_names=frozenset(),
    collection_names=frozenset({"retained_order_records"}),
    record_types=frozenset({"LEGAL_HOLD_RECORD"}),
    log_events=frozenset(),
    existing_state=present_state,
    retention_end_field="retained_until",
)
