from __future__ import annotations

import dataclasses
import typing
from datetime import datetime

from ghost_audit import identity
from ghost_audit.model import ABSENT, PRESENT, Step
from ghost_audit.output_format import (
    FINDING_PHASE,
    OPERATION_ORDER,
    REMEDIATION_PHASE,
    VERIFICATION_PHASE,
)

if typing.TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from ghost_audit.dataset import Dataset
    from ghost_audit.model import Coverage, Observation

COMPLETE = "COMPLETE"
INCOMPLETE = "INCOMPLETE"
NOT_APPLICABLE = "NOT_APPLICABLE"
LINK_RESOURCE_IDENTITY = "LINK_RESOURCE_IDENTITY"

type ResourceKey = tuple[str, str]


@dataclasses.dataclass(frozen=True, slots=True)
class PlanRule:
    """The end state a rule action requires and the steps that reach and check it."""

    end_state: str
    finding: tuple[str, str]
    remediation: tuple[str, str]
    verification: tuple[str, str]


PLAN_RULES = {
    "DELETE": PlanRule(
        ABSENT,
        ("REPORT_REMAINING_RECORD", PRESENT),
        ("DELETE_RECORD", ABSENT),
        ("VERIFY_RECORD_ABSENT", ABSENT),
    ),
}


@dataclasses.dataclass(frozen=True, slots=True)
class _Proof:
    state: str
    observed_at: datetime
    evidence_id: str
    is_observation: bool


@dataclasses.dataclass(frozen=True, slots=True)
class _CopyState:
    state: str
    citation: _Proof | None


@dataclasses.dataclass(frozen=True, slots=True)
class _ResourceAssessment:
    system: str
    resource_id: str
    rule: PlanRule
    has_gap: bool
    evidence_id: str


class Auditor:
    """Audit deletion requests against a dataset indexed once."""

    def __init__(self, dataset: Dataset) -> None:
        self._dataset = dataset
        self._observations_by_identifier: dict[str, list[Observation]] = {}
        self._observations_by_resource: dict[ResourceKey, list[Observation]] = {}
        for observation in dataset.evidence.observations:
            key = (observation.system, observation.resource_id)
            self._observations_by_resource.setdefault(key, []).append(observation)
            for identifier in observation.identifiers:
                self._observations_by_identifier.setdefault(identifier, []).append(observation)
        self._coverages_by_scope: dict[tuple[str, str], list[Coverage]] = {}
        for coverage in dataset.evidence.coverages:
            scope = (coverage.system, coverage.category)
            self._coverages_by_scope.setdefault(scope, []).append(coverage)
        self._catalog_links = [
            (claim, identity.identifiers_in_text(claim.details))
            for claim in dataset.claims
            if claim.event_type == LINK_RESOURCE_IDENTITY
        ]

    def audited_case(self, request: Mapping[str, str]) -> tuple[str, list[Step]]:
        """Return the deletion status and ordered steps for one request."""
        if not _authorizes_deletion(request["request_text"]):
            return NOT_APPLICABLE, []
        audit_at = datetime.fromisoformat(request["audit_at"])
        subject = identity.subject_identifiers(
            request["email"], self._dataset.identities, self._dataset.audit_log
        )
        assessments = [
            assessment
            for key in sorted(self._linked_resources(subject, audit_at))
            if (assessment := self._assessment(key, audit_at)) is not None
        ]
        # evaluation.validate rejects COMPLETE and INCOMPLETE rows without steps.
        if not assessments:
            return NOT_APPLICABLE, []
        is_complete = not any(assessment.has_gap for assessment in assessments)
        steps = _planned_steps(assessments, is_complete=is_complete)
        return (COMPLETE if is_complete else INCOMPLETE), steps

    def _linked_resources(self, subject: frozenset[str], audit_at: datetime) -> set[ResourceKey]:
        linked = {
            (observation.system, observation.resource_id)
            for identifier in subject
            for observation in self._observations_by_identifier.get(identifier, ())
            if observation.observed_at <= audit_at
        }
        linked.update(
            (claim.target_system, claim.resource_id)
            for claim, identifiers in self._catalog_links
            if claim.event_time <= audit_at and identifiers & subject
        )
        return linked

    def _assessment(self, key: ResourceKey, audit_at: datetime) -> _ResourceAssessment | None:
        observations = [
            observation
            for observation in self._observations_by_resource.get(key, ())
            if observation.observed_at <= audit_at
        ]
        if not observations:
            return None
        system, resource_id = key
        category = observations[0].category
        rule = PLAN_RULES[self._dataset.required_actions[category]]

        proofs_by_copy: dict[str, list[_Proof]] = {}
        for observation in observations:
            proofs_by_copy.setdefault(observation.copy, []).append(
                _Proof(
                    observation.state,
                    observation.observed_at,
                    observation.evidence_id,
                    is_observation=True,
                )
            )
        for coverage in self._coverages_by_scope.get((system, category), ()):
            if coverage.observed_at <= audit_at and resource_id not in coverage.resource_ids:
                proofs_by_copy.setdefault(coverage.copy, []).append(
                    _Proof(ABSENT, coverage.observed_at, coverage.evidence_id, is_observation=False)
                )

        copy_states = [self._copy_state(proofs, audit_at) for proofs in proofs_by_copy.values()]
        gap_states = [copy for copy in copy_states if copy.state != rule.end_state]
        # A gap copy known only from uncitable files cites the resource's latest citable proof.
        citation = _preferred_citation(gap_states) or _preferred_citation(copy_states)
        if citation is None:
            return None
        return _ResourceAssessment(
            system, resource_id, rule, bool(gap_states), citation.evidence_id
        )

    def _copy_state(self, proofs: list[_Proof], audit_at: datetime) -> _CopyState:
        latest = max(proofs, key=lambda proof: (proof.observed_at, proof.is_observation))
        citable = [
            proof
            for proof in proofs
            if self._dataset.captured_at_by_evidence[proof.evidence_id] <= audit_at
        ]
        citation = max(
            citable,
            key=lambda proof: (
                proof.state == latest.state,
                proof.is_observation,
                proof.observed_at,
            ),
            default=None,
        )
        return _CopyState(latest.state, citation)


def _authorizes_deletion(_request_text: str) -> bool:
    return True


def _preferred_citation(copy_states: Iterable[_CopyState]) -> _Proof | None:
    citations = [copy.citation for copy in copy_states if copy.citation is not None]
    return max(citations, key=lambda proof: (proof.is_observation, proof.observed_at), default=None)


def _planned_steps(assessments: Iterable[_ResourceAssessment], *, is_complete: bool) -> list[Step]:
    steps: list[Step] = []
    for assessment in assessments:
        rule = assessment.rule
        if assessment.has_gap:
            steps.append(_step(FINDING_PHASE, assessment, rule.finding, assessment.evidence_id))
            steps.append(_step(REMEDIATION_PHASE, assessment, rule.remediation, ""))
        verification_evidence = assessment.evidence_id if is_complete else ""
        steps.append(
            _step(VERIFICATION_PHASE, assessment, rule.verification, verification_evidence)
        )
    return sorted(
        steps,
        key=lambda step: (
            OPERATION_ORDER[(step.phase, step.operation, step.state)],
            step.system_id,
            step.resource_id,
        ),
    )


def _step(
    phase: str, assessment: _ResourceAssessment, operation: tuple[str, str], evidence_id: str
) -> Step:
    return Step(
        phase=phase,
        system_id=assessment.system,
        resource_id=assessment.resource_id,
        operation=operation[0],
        state=operation[1],
        evidence_id=evidence_id,
    )
