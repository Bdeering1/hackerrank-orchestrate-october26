from __future__ import annotations

import dataclasses
import typing
from datetime import datetime

from ghost_audit import identity
from ghost_audit.model import ABSENT, BLOCKED, DISABLED, Step
from ghost_audit.output_format import (
    BLOCK_RESTORE,
    DELETE_RECORD,
    DISABLE_DATA_FLOW,
    OPERATION_ORDER,
    REPORT_ACTIVE_DATA_FLOW,
    REPORT_REMAINING_RECORD,
    REPORT_RESTORE_RISK,
    VERIFY_DATA_FLOW_DISABLED,
    VERIFY_RECORD_ABSENT,
    VERIFY_RESTORE_BLOCKED,
    Operation,
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
    finding: Operation
    remediation: Operation
    verification: Operation


PLAN_RULES = {
    "DELETE": PlanRule(ABSENT, REPORT_REMAINING_RECORD, DELETE_RECORD, VERIFY_RECORD_ABSENT),
}

CATEGORY_PLAN_RULES = {
    "DATA_FLOW": PlanRule(
        DISABLED,
        REPORT_ACTIVE_DATA_FLOW,
        DISABLE_DATA_FLOW,
        VERIFY_DATA_FLOW_DISABLED,
    ),
    "BACKUP_ARCHIVE": PlanRule(
        BLOCKED,
        REPORT_RESTORE_RISK,
        BLOCK_RESTORE,
        VERIFY_RESTORE_BLOCKED,
    ),
}


@dataclasses.dataclass(frozen=True, slots=True)
class _Proof:
    copy: str
    state: str
    observed_at: datetime
    evidence_id: str
    is_observation: bool


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
        self._identifiers_by_identifier = identity.identifiers_by_identifier(
            dataset.identities, dataset.audit_log
        )
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
        """Return the deletion status and ordered steps for one deletion request."""
        requested_at = datetime.fromisoformat(request["requested_at"])
        audit_at = datetime.fromisoformat(request["audit_at"])
        request_identifier = identity.normalized_identifier(request["email"]) or ""
        subject = self._identifiers_by_identifier.get(request_identifier, frozenset())
        # A record last tied to the subject and already compliant before the request
        # was handled by an earlier request.
        assessments = [
            assessment
            for key, linked_at in sorted(self._link_times(subject, audit_at).items())
            if not (linked_at < requested_at and self._is_compliant(key, requested_at))
            and (assessment := self._assessment(key, audit_at)) is not None
        ]
        # evaluation.validate rejects COMPLETE and INCOMPLETE rows without steps.
        if not assessments:
            return NOT_APPLICABLE, []
        is_complete = not any(assessment.has_gap for assessment in assessments)
        steps = _planned_steps(assessments, is_complete=is_complete)
        return (COMPLETE if is_complete else INCOMPLETE), steps

    def _link_times(
        self, subject: frozenset[str], audit_at: datetime
    ) -> dict[ResourceKey, datetime]:
        link_times: dict[ResourceKey, datetime] = {}
        links = [
            ((observation.system, observation.resource_id), observation.observed_at)
            for identifier in subject
            for observation in self._observations_by_identifier.get(identifier, ())
        ]
        links.extend(
            ((claim.target_system, claim.resource_id), claim.event_time)
            for claim, identifiers in self._catalog_links
            if identifiers & subject
        )
        for key, linked_at in links:
            if linked_at <= audit_at:
                link_times[key] = max(linked_at, link_times.get(key, linked_at))
        return link_times

    def _is_compliant(self, key: ResourceKey, at: datetime) -> bool:
        rule_and_proofs = self._rule_and_proofs(key, at)
        return rule_and_proofs is not None and not _gap_copies(*rule_and_proofs)

    def _assessment(self, key: ResourceKey, audit_at: datetime) -> _ResourceAssessment | None:
        rule_and_proofs = self._rule_and_proofs(key, audit_at)
        if rule_and_proofs is None:
            return None
        rule, proofs = rule_and_proofs
        gap_copies = _gap_copies(rule, proofs)
        has_gap = bool(gap_copies)
        citable = [
            proof
            for proof in proofs
            if self._dataset.captured_at_by_evidence[proof.evidence_id] <= audit_at
        ]
        citation = max(
            citable,
            key=lambda proof: (
                (proof.state != rule.end_state) == has_gap,
                proof.copy in gap_copies,
                proof.is_observation,
                proof.observed_at,
            ),
            default=None,
        )
        if citation is None:
            return None
        system, resource_id = key
        return _ResourceAssessment(system, resource_id, rule, has_gap, citation.evidence_id)

    def _rule_and_proofs(
        self, key: ResourceKey, at: datetime
    ) -> tuple[PlanRule, list[_Proof]] | None:
        observations = [
            observation
            for observation in self._observations_by_resource.get(key, ())
            if observation.observed_at <= at
        ]
        if not observations:
            return None
        system, resource_id = key
        category = observations[0].category
        proofs = [
            _Proof(
                observation.copy,
                observation.state,
                observation.observed_at,
                observation.evidence_id,
                is_observation=True,
            )
            for observation in observations
        ]
        category_rule = CATEGORY_PLAN_RULES.get(category)
        # A snapshot that leaves out a connector or backup does not prove it is disabled or blocked.
        if category_rule is not None:
            return category_rule, proofs
        proofs.extend(
            _Proof(
                coverage.copy,
                ABSENT,
                coverage.observed_at,
                coverage.evidence_id,
                is_observation=False,
            )
            for coverage in self._coverages_by_scope.get((system, category), ())
            if coverage.observed_at <= at and resource_id not in coverage.resource_ids
        )
        return PLAN_RULES[self._dataset.required_actions[category]], proofs


def _gap_copies(rule: PlanRule, proofs: Iterable[_Proof]) -> set[str]:
    latest_by_copy: dict[str, _Proof] = {}
    for proof in sorted(
        proofs, key=lambda proof: (proof.observed_at, proof.is_observation), reverse=True
    ):
        latest_by_copy.setdefault(proof.copy, proof)
    return {copy for copy, latest in latest_by_copy.items() if latest.state != rule.end_state}


def _planned_steps(assessments: Iterable[_ResourceAssessment], *, is_complete: bool) -> list[Step]:
    steps: list[Step] = []
    for assessment in assessments:
        rule = assessment.rule
        if assessment.has_gap:
            steps.append(_step(assessment, rule.finding, assessment.evidence_id))
            steps.append(_step(assessment, rule.remediation, ""))
        verification_evidence = assessment.evidence_id if is_complete else ""
        steps.append(_step(assessment, rule.verification, verification_evidence))
    return sorted(
        steps,
        key=lambda step: (
            OPERATION_ORDER[(step.phase, step.operation, step.state)],
            step.system_id,
            step.resource_id,
        ),
    )


def _step(assessment: _ResourceAssessment, operation: Operation, evidence_id: str) -> Step:
    return Step(
        phase=operation.phase,
        system_id=assessment.system,
        resource_id=assessment.resource_id,
        operation=operation.name,
        state=operation.state,
        evidence_id=evidence_id,
    )
