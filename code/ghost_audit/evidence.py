from __future__ import annotations

import dataclasses
import json
import re
import sqlite3
import typing
from datetime import datetime

from ghost_audit import identity
from ghost_audit.model import ABSENT, PRIMARY_COPY, Coverage, Observation

if typing.TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence
    from pathlib import Path

    from ghost_audit.categories import Category

type Record = Mapping[str, object]

CAPTURED_AT_PATTERN = re.compile(r"^-- Captured at: (\S+)", re.MULTILINE)
KEY_VALUE_PATTERN = re.compile(r'(\w+)=("(?:[^"\\]|\\.)*"|\S+)')
LOG_PREFIX_PATTERNS = (
    re.compile(r"\[\w+\] \[(?P<service>[\w-]+)\] \[(?P<trace_id>[\w-]+)\] (?P<event>\w+):"),
    re.compile(r"\| \w+ \| (?P<service>[\w-]+) \| (?P<trace_id>[\w-]+) \| (?P<event>\w+) \|"),
    re.compile(r"<\d+>\d+ \S+ (?P<service>\S+) (?P<trace_id>\S+) - -"),
)
TEXT_RECORD_PREFIX = "- "
TEXT_RECORD_SEPARATOR = " | "
TEXT_RECORD_FIELDS = (
    "recorded_at",
    "system",
    "resource_id",
    "record_type",
    "result",
    "subject_reference",
)
ABSENT_MARKERS = {"result": "NOT_FOUND", "rows": "0", "http_status": "404", "status_code": "404"}
NULL_TEXT = "null"
TRACE_ID = "trace_id"
RESOURCE_ID = "resource_id"
RECORD_TYPE = "record_type"


@dataclasses.dataclass(frozen=True, slots=True)
class Evidence:
    """Every Observation and Coverage extracted from the evidence files."""

    observations: tuple[Observation, ...]
    coverages: tuple[Coverage, ...]


@dataclasses.dataclass(frozen=True, slots=True)
class _CategoryLookup:
    by_table: Mapping[str, Category]
    by_collection: Mapping[str, Category]
    by_record_type: Mapping[str, Category]
    by_log_event: Mapping[str, Category]


def read_evidence(paths_by_id: Mapping[str, Path], categories: Sequence[Category]) -> Evidence:
    """Convert every structured evidence file into Observations and Coverages."""
    lookup = _CategoryLookup(
        by_table=_categories_by_name(categories, lambda category: category.table_names),
        by_collection=_categories_by_name(categories, lambda category: category.collection_names),
        by_record_type=_categories_by_name(categories, lambda category: category.record_types),
        by_log_event=_categories_by_name(categories, lambda category: category.log_events),
    )
    observations: list[Observation] = []
    coverages: list[Coverage] = []
    for evidence_id, path in paths_by_id.items():
        reader = _EvidenceReader(lookup, evidence_id)
        reader.read(path)
        observations.extend(reader.observations)
        coverages.extend(reader.coverages)
    return Evidence(tuple(observations), tuple(coverages))


def _categories_by_name(
    categories: Iterable[Category], names_of: Callable[[Category], frozenset[str]]
) -> dict[str, Category]:
    categories_by_name: dict[str, Category] = {}
    for category in categories:
        for name in names_of(category):
            claimant = categories_by_name.setdefault(name, category)
            if claimant is not category:
                message = (
                    f"{name} is claimed by {claimant.rule_category} and {category.rule_category}"
                )
                raise ValueError(message)
    return categories_by_name


class _EvidenceReader:
    def __init__(self, lookup: _CategoryLookup, evidence_id: str) -> None:
        self._lookup = lookup
        self._evidence_id = evidence_id
        self.observations: list[Observation] = []
        self.coverages: list[Coverage] = []

    def read(self, path: Path) -> None:
        match path.suffix:
            case ".sql":
                self._read_sql(path.read_text(encoding="utf-8"))
            case ".json":
                document = _parsed_json(path.read_text(encoding="utf-8"))
                self._read_json(document)
            case ".log":
                self._read_log(path.read_text(encoding="utf-8").splitlines())
            case ".txt":
                self._read_text_records(path.read_text(encoding="utf-8").splitlines())
            case _:
                pass

    def _observe(
        self,
        category: Category,
        system: str,
        copy: str,
        record: Record,
        observed_at: datetime,
        identifiers: frozenset[str] | None = None,
    ) -> None:
        state = ABSENT if _is_absent(record) else category.existing_state(record)
        self.observations.append(
            Observation(
                system=system,
                resource_id=str(record[RESOURCE_ID]),
                copy=copy,
                category=category.rule_category,
                state=state,
                is_condition_met=category.is_condition_met(record),
                identifiers=_identifiers(record) if identifiers is None else identifiers,
                observed_at=observed_at,
                evidence_id=self._evidence_id,
            )
        )

    def _read_snapshot(
        self,
        category: Category,
        system: str,
        copy: str,
        records: Sequence[Record],
        observed_at: datetime,
        *,
        is_partial: bool = False,
    ) -> None:
        for record in records:
            self._observe(category, system, copy, record, observed_at)
        self.coverages.append(
            Coverage(
                system=system,
                category=category.rule_category,
                copy=copy,
                resource_ids=frozenset(str(record[RESOURCE_ID]) for record in records),
                observed_at=observed_at,
                evidence_id=self._evidence_id,
                is_partial=is_partial,
            )
        )

    def _read_ledger_item(self, record: Record, observed_at: datetime) -> None:
        category = self._lookup.by_record_type.get(str(record[RECORD_TYPE]))
        if category is not None:
            self._observe(category, str(record["system"]), PRIMARY_COPY, record, observed_at)

    def _read_sql(self, script: str) -> None:
        rows_by_table = _sql_rows_by_table(script)
        header = CAPTURED_AT_PATTERN.search(script)
        if header is None:
            self._read_inventory(rows_by_table)
        else:
            self._read_topology(rows_by_table, _time(header[1]))

    def _read_inventory(self, rows_by_table: Mapping[str, list[Record]]) -> None:
        captured_at_by_system = {
            str(row["origin_system"]): _time(row["captured_at"])
            for row in rows_by_table["snapshot_scope"]
        }
        for table, rows in rows_by_table.items():
            category = self._lookup.by_table.get(table)
            if category is None:
                continue
            observed_at = captured_at_by_system.get(category.default_system)
            if observed_at is not None:
                self._read_snapshot(
                    category, category.default_system, PRIMARY_COPY, rows, observed_at
                )

    def _read_topology(
        self, rows_by_table: Mapping[str, list[Record]], observed_at: datetime
    ) -> None:
        primary_suffix = f"_{PRIMARY_COPY}"
        prefixes = [
            table.removesuffix(PRIMARY_COPY)
            for table in rows_by_table
            if table.endswith(primary_suffix)
        ]
        records_by_copy: dict[str, dict[tuple[str, Category], list[Record]]] = {}
        for table, rows in rows_by_table.items():
            prefix = max(
                (prefix for prefix in prefixes if table.startswith(prefix)), key=len, default=None
            )
            if prefix is None:
                continue
            records_by_source = records_by_copy.setdefault(table.removeprefix(prefix), {})
            for row in rows:
                source = self._topology_source(row, prefix.removesuffix("_"))
                if source is not None:
                    system, category, record = source
                    records_by_source.setdefault((system, category), []).append(record)

        # Each copy table covers every system the snapshot holds, so drift shows as absence.
        sources = {
            source for records_by_source in records_by_copy.values() for source in records_by_source
        }
        for copy, records_by_source in records_by_copy.items():
            for system, category in sorted(
                sources, key=lambda source: (source[0], source[1].rule_category)
            ):
                records = records_by_source.get((system, category), [])
                self._read_snapshot(category, system, copy, records, observed_at)

    def _topology_source(self, row: Record, base_table: str) -> tuple[str, Category, Record] | None:
        if "record_json" not in row:
            category = self._lookup.by_table.get(base_table)
            return None if category is None else (category.default_system, category, row)
        category = self._lookup.by_collection.get(str(row["collection_name"]))
        record = _as_record(_parsed_json(str(row["record_json"])))
        if category is None or record is None:
            return None
        return str(row["origin_system"]), category, record

    def _read_json(self, document: object) -> None:
        root = _as_record(document)
        exports = None if root is None else _as_record(root.get("service_exports"))
        if exports is None:
            self._walk_json(document)
            return
        for system, collections in exports.items():
            for collection, items in (_as_record(collections) or {}).items():
                category = self._lookup.by_collection.get(collection)
                if category is None:
                    continue
                for item in _as_list(items):
                    record = _as_record(item)
                    if record is not None:
                        self._observe(
                            category, system, PRIMARY_COPY, record, _time(record["observed_at"])
                        )

    def _walk_json(self, node: object) -> None:
        record = _as_record(node)
        if record is None:
            for item in _as_list(node):
                self._walk_json(item)
            return
        if RECORD_TYPE in record and RESOURCE_ID in record:
            self._read_ledger_item(record, _time(record["recorded_at"]))
            return
        category = self._lookup.by_collection.get(str(record.get("collection")))
        if category is not None and "captured_at" in record:
            system = str(record.get("data_store", category.default_system))
            records = [
                item for item in map(_as_record, _as_list(record["records"])) if item is not None
            ]
            # Bundle snapshots are extracts of selected customers, not whole collections.
            self._read_snapshot(
                category,
                system,
                PRIMARY_COPY,
                records,
                _time(record["captured_at"]),
                is_partial=True,
            )
            return
        for value in record.values():
            self._walk_json(value)

    def _read_log(self, lines: Iterable[str]) -> None:
        events = [event for line in lines if (event := _log_event(line)) is not None]
        identifiers_by_trace: dict[str, set[str]] = {}
        for event in events:
            if TRACE_ID in event:
                identifiers_by_trace.setdefault(event[TRACE_ID], set()).update(_identifiers(event))
        for event in events:
            if RECORD_TYPE in event:
                self._read_ledger_item(event, _time(event["timestamp"]))
                continue
            category = self._lookup.by_log_event.get(event.get("event", ""))
            if category is None or RESOURCE_ID not in event:
                continue
            observed_at = _time(event["timestamp"])
            trace_identifiers = identifiers_by_trace.get(event.get(TRACE_ID, ""))
            identifiers = None if trace_identifiers is None else frozenset(trace_identifiers)
            self._observe(
                category, category.default_system, PRIMARY_COPY, event, observed_at, identifiers
            )

    def _read_text_records(self, lines: Iterable[str]) -> None:
        for line in lines:
            values = line.removeprefix(TEXT_RECORD_PREFIX).split(TEXT_RECORD_SEPARATOR)
            if line.startswith(TEXT_RECORD_PREFIX) and len(values) == len(TEXT_RECORD_FIELDS):
                record: dict[str, object] = dict(zip(TEXT_RECORD_FIELDS, values, strict=True))
                self._read_ledger_item(record, _time(record["recorded_at"]))


def _sql_rows_by_table(script: str) -> dict[str, list[Record]]:
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(script)
        table_rows: list[tuple[str]] = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall()
        rows_by_table: dict[str, list[Record]] = {}
        for (table,) in table_rows:
            # Table names come from sqlite_master of the snapshot itself.
            quoted_table = table.replace('"', '""')
            cursor = connection.execute(f'SELECT * FROM "{quoted_table}"')  # noqa: S608
            columns = [str(column[0]) for column in cursor.description]
            rows: list[tuple[object, ...]] = cursor.fetchall()
            rows_by_table[table] = [dict(zip(columns, row, strict=True)) for row in rows]
        return rows_by_table
    finally:
        connection.close()


def _log_event(line: str) -> dict[str, str] | None:
    timestamp, _, body = line.strip().partition(" ")
    if not body:
        return None
    fields: dict[str, str] = {}
    if body.startswith("{"):
        document = _as_record(_parsed_json(body)) or {}
        fields.update((key, str(value)) for key, value in document.items())
    else:
        for pattern in LOG_PREFIX_PATTERNS:
            prefix = pattern.match(body)
            if prefix is not None:
                fields.update(prefix.groupdict())
                body = body[prefix.end() :]
                break
        fields.update(_key_values(body))
    if "requestId" in fields:
        fields.setdefault(TRACE_ID, fields["requestId"])
    fields["timestamp"] = timestamp
    return {key: value for key, value in fields.items() if value != NULL_TEXT}


def _key_values(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for match in KEY_VALUE_PATTERN.finditer(text):
        key, raw_value = match[1], match[2]
        value = raw_value[1:-1].replace('\\"', '"') if raw_value.startswith('"') else raw_value
        if '="' in value:
            fields.update(_key_values(value))
        else:
            fields[key] = value
    return fields


def _is_absent(record: Record) -> bool:
    return any(str(record.get(key)) == marker for key, marker in ABSENT_MARKERS.items())


def _identifiers(value: object) -> frozenset[str]:
    if isinstance(value, str):
        identifier = identity.normalized_identifier(value)
        return frozenset() if identifier is None else frozenset({identifier})
    record = _as_record(value)
    children = record.values() if record is not None else _as_list(value)
    return frozenset[str]().union(*(_identifiers(child) for child in children))


def _parsed_json(text: str) -> object:
    return typing.cast("object", json.loads(text))


def _as_record(value: object) -> Record | None:
    return typing.cast("Record", value) if isinstance(value, dict) else None


def _as_list(value: object) -> list[object]:
    return typing.cast("list[object]", value) if isinstance(value, list) else []


def _time(value: object) -> datetime:
    return datetime.fromisoformat(str(value))
