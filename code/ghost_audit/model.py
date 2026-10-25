from __future__ import annotations

import dataclasses
import typing

if typing.TYPE_CHECKING:
    from datetime import datetime

PRESENT = "PRESENT"
ABSENT = "ABSENT"
PRIMARY_COPY = "primary"


@dataclasses.dataclass(frozen=True, slots=True)
class Observation:
    """One record state seen in one evidence item."""

    system: str
    resource_id: str
    copy: str
    category: str
    state: str
    identifiers: frozenset[str]
    observed_at: datetime
    evidence_id: str


@dataclasses.dataclass(frozen=True, slots=True)
class Coverage:
    """A snapshot listing every record of one category in one system copy."""

    system: str
    category: str
    copy: str
    resource_ids: frozenset[str]
    observed_at: datetime
    evidence_id: str


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
