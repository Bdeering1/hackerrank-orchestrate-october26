from ghost_audit.categories import Category, always_present_state, is_always_met

CATEGORY = Category(
    rule_category="SEARCH_INDEX_ENTRY",
    default_system="search_service",
    table_names=frozenset({"customer_search_documents", "search_documents"}),
    collection_names=frozenset({"customer_search_documents", "index_queries"}),
    record_types=frozenset({"SEARCH_INDEX_ENTRY"}),
    log_events=frozenset({"index_query_completed"}),
    existing_state=always_present_state,
    is_condition_met=is_always_met,
)
