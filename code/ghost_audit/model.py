from __future__ import annotations

import dataclasses
import typing

if typing.TYPE_CHECKING:
    from datetime import datetime

PRESENT = "PRESENT"
ABSENT = "ABSENT"
REDACTED = "REDACTED"
ANONYMIZED = "ANONYMIZED"
PRIMARY_COPY = "primary"


@dataclasses.dataclass(frozen=True, slots=True)
class Observation:
    """One record state seen in one evidence item."""

    system: str
    resource_id: str
    copy: str
    category: str
    state: str
    is_condition_met: bool
    identifiers: frozenset[str]
    observed_at: datetime
    evidence_id: str
    retention_end: datetime | None


@dataclasses.dataclass(frozen=True, slots=True)
class Coverage:
    """A snapshot listing records of one category in one system copy.

    A partial snapshot is an extract that need not list every record.
    """

    system: str
    category: str
    copy: str
    resource_ids: frozenset[str]
    observed_at: datetime
    evidence_id: str
    is_partial: bool


@dataclasses.dataclass(frozen=True, slots=True)
class Claim:
    """One system activity row; its reported result never proves a state."""

    activity_id: str
    event_time: datetime
    event_type: str
    source_system: str
    target_system: str
    resource_id: str
    reported_result: str
    details: str

    @property
    def resource_key(self) -> tuple[str, str]:
        return self.target_system, self.resource_id


@dataclasses.dataclass(frozen=True, slots=True)
class Step:
    """One output step before numbering."""

    phase: str
    system_id: str
    resource_id: str
    operation: str
    state: str
    evidence_id: str
