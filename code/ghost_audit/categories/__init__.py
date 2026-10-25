"""Data categories, one module each.

CACHE_ENTRY and EMAIL_DELIVERY_LOG have no module: their records appear only in activity
rows that carry no identifier, so none can be tied to a subject.
"""

from __future__ import annotations

import dataclasses
import importlib
import pkgutil
import typing

from ghost_audit.model import ANONYMIZED, PRESENT, REDACTED

if typing.TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping


@dataclasses.dataclass(frozen=True, slots=True)
class Category:
    """A data category: its rule, default system and the evidence names that identify it."""

    rule_category: str
    default_system: str
    table_names: frozenset[str]
    collection_names: frozenset[str]
    record_types: frozenset[str]
    log_events: frozenset[str]
    existing_state: Callable[[Mapping[str, object]], str]
    is_condition_met: Callable[[Mapping[str, object]], bool]
    retention_end_field: str | None = None


def always_present_state(_record: Mapping[str, object]) -> str:
    """Return PRESENT for any observed record."""
    return PRESENT


def is_always_met(_record: Mapping[str, object]) -> bool:
    """Return whether an unconditional rule applies."""
    return True


def state_from_result(record: Mapping[str, object]) -> str | None:
    """Return the observed state represented by a result field."""
    result = str(record.get("result", ""))
    if not result:
        return None
    return result if result in {REDACTED, ANONYMIZED} else PRESENT


def has_any_field(record: Mapping[str, object], fields: Iterable[str]) -> bool:
    """Return whether the record holds a value for any of the fields."""
    return any(record.get(field) is not None for field in fields)


def discovered_categories() -> tuple[Category, ...]:
    """Return the CATEGORY declared by every module in this package."""
    categories: list[Category] = []
    for module_info in sorted(pkgutil.iter_modules(__path__), key=lambda info: info.name):
        module = importlib.import_module(f"{__name__}.{module_info.name}")
        category = typing.cast("object", vars(module)["CATEGORY"])
        if not isinstance(category, Category):
            raise TypeError(f"{module.__name__}.CATEGORY is not a Category")
        categories.append(category)
    return tuple(categories)
