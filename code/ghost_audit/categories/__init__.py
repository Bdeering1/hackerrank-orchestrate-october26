from __future__ import annotations

import dataclasses
import importlib
import pkgutil
import typing

from ghost_audit.model import PRESENT

if typing.TYPE_CHECKING:
    from collections.abc import Callable, Mapping


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


def present_state(_record: Mapping[str, object]) -> str:
    """Return PRESENT: every record that exists still holds data to delete."""
    return PRESENT


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
