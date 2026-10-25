from __future__ import annotations

import dataclasses
import importlib
import pkgutil
import typing

from ghost_audit.model import ACTIVE

if typing.TYPE_CHECKING:
    from collections.abc import Callable, Mapping


TRUE_TEXT = frozenset({"1", "true"})
FALSE_TEXT = frozenset({"0", "false"})


def has_truthy_value(record: Mapping[str, object], field_name: str) -> bool:
    """Return whether a record field represents true."""
    return str(record.get(field_name)).casefold() in TRUE_TEXT


def has_falsey_value(record: Mapping[str, object], field_name: str) -> bool:
    """Return whether a record field represents false."""
    return str(record.get(field_name)).casefold() in FALSE_TEXT


def state_from_result(record: Mapping[str, object], compliant_state: str) -> str:
    """Return a ledger result state, treating malformed values as active."""
    result = str(record.get("result", "")).upper()
    return compliant_state if result == compliant_state else ACTIVE


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
