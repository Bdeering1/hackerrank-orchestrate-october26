from __future__ import annotations

import csv
import dataclasses
import typing
from datetime import datetime

from ghost_audit import categories
from ghost_audit.evidence import Evidence, read_evidence
from ghost_audit.model import Claim

if typing.TYPE_CHECKING:
    from pathlib import Path


@dataclasses.dataclass(frozen=True, slots=True)
class Dataset:
    """Every participant-facing input the audit needs, loaded once per run."""

    identities: tuple[dict[str, str], ...]
    audit_log: tuple[dict[str, str], ...]
    claims: tuple[Claim, ...]
    required_actions: dict[str, str]
    captured_at_by_evidence: dict[str, datetime]
    evidence: Evidence


def loaded_dataset(dataset_dir: Path) -> Dataset:
    """Load identities, activity, rules and evidence from a dataset directory."""
    manifest = csv_records(dataset_dir / "evidence_files.csv")
    return Dataset(
        identities=tuple(csv_records(dataset_dir / "user_identities.csv")),
        audit_log=tuple(csv_records(dataset_dir / "user_audit_log.csv")),
        claims=tuple(
            Claim(
                activity_id=row["activity_id"],
                event_time=datetime.fromisoformat(row["event_time"]),
                event_type=row["event_type"],
                target_system=row["target_system"],
                resource_id=row["resource_id"],
                details=row["details"],
            )
            for row in csv_records(dataset_dir / "system_activity.csv")
        ),
        required_actions={
            row["data_category"]: row["required_action"]
            for row in csv_records(dataset_dir / "deletion_rules.csv")
        },
        captured_at_by_evidence={
            row["file_id"]: datetime.fromisoformat(row["captured_at"]) for row in manifest
        },
        evidence=read_evidence(
            {row["file_id"]: dataset_dir / row["file_path"] for row in manifest},
            categories.discovered_categories(),
        ),
    )


def csv_records(path: Path) -> list[dict[str, str]]:
    """Return a CSV file's rows keyed by header."""
    with path.open(encoding="utf-8", newline="") as csv_file:
        return list(csv.DictReader(csv_file))
