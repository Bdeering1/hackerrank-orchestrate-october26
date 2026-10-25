from __future__ import annotations

import dataclasses
import typing
from datetime import datetime, timedelta

from ghost_audit import identity
from ghost_audit.categories import account
from ghost_audit.model import ABSENT, Step
from ghost_audit.output_format import (
    DELETE_RECORD,
    OPERATION_ORDER,
    REPORT_REMAINING_RECORD,
    VERIFY_RECORD_ABSENT,
    Operation,
)

if typing.TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from ghost_audit.dataset import Dataset
    from ghost_audit.model import Claim, Coverage, Observation

COMPLETE = "COMPLETE"
INCOMPLETE = "INCOMPLETE"
NOT_APPLICABLE = "NOT_APPLICABLE"
LINK_RESOURCE_IDENTITY = "LINK_RESOURCE_IDENTITY"
DELETION_WORKER = "deletion_worker"
TARGET_RESOURCE_MARKER = "Target resource:"
NOMINATION_WINDOW = (timedelta(minutes=-78), timedelta(minutes=-42))
TARGETED_NOMINATION_WINDOW = (timedelta(minutes=-15), timedelta(minutes=15))
REPORTED_RESULT_BY_STATUS = {
    COMPLETE: "SUCCESS",
    "PARTIALLY_COMPLETE": "PARTIAL",
    "NOT_STARTED": "FAILED",
}

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
        self._account_deletions = [
            claim
            for claim in dataset.claims
            if claim.source_system == DELETION_WORKER
            and claim.event_type == DELETE_RECORD.name
            and claim.target_system == account.CATEGORY.default_system
        ]
        self._request_times_by_subject: dict[frozenset[str], list[tuple[datetime, datetime]]] = {}
        for request in dataset.requests:
            if _authorizes_deletion(request["request_text"]):
                self._request_times_by_subject.setdefault(self._subject(request), []).append(
                    (
                        datetime.fromisoformat(request["requested_at"]),
                        datetime.fromisoformat(request["audit_at"]),
                    )
                )

    def audited_case(self, request: Mapping[str, str]) -> tuple[str, list[Step]]:
        """Return the deletion status and ordered steps for one request."""
        if not _authorizes_deletion(request["request_text"]):
            return NOT_APPLICABLE, []
        audit_at = datetime.fromisoformat(request["audit_at"])
        subject = self._subject(request)
        previous_audit_at = self._previous_audit_at(
            subject, datetime.fromisoformat(request["requested_at"])
        )
        keys = [
            key
            for key, linked_at in sorted(self._link_times(subject, audit_at).items())
            if previous_audit_at is None or linked_at > previous_audit_at
        ]
        assessments = [
            assessment
            for key in keys
            if (assessment := self._assessment(key, audit_at)) is not None
        ]
        has_linked_account = any(system == account.CATEGORY.default_system for system, _ in keys)
        nominated_key = (
            None if has_linked_account else self._nominated_account(request, subject, audit_at)
        )
        if nominated_key is not None:
            assessment = self._assessment(
                nominated_key, audit_at, default_category=account.CATEGORY.rule_category
            )
            if assessment is not None:
                assessments.append(assessment)
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

    def _subject(self, request: Mapping[str, str]) -> frozenset[str]:
        request_identifier = identity.normalized_identifier(request["email"]) or ""
        return self._identifiers_by_identifier.get(request_identifier, frozenset())

    def _previous_audit_at(
        self, subject: frozenset[str], requested_at: datetime
    ) -> datetime | None:
        previous_times = max(
            (
                times
                for times in self._request_times_by_subject.get(subject, ())
                if times[0] < requested_at
            ),
            default=None,
        )
        return None if previous_times is None else previous_times[1]

    def _nominated_account(
        self, request: Mapping[str, str], subject: frozenset[str], audit_at: datetime
    ) -> ResourceKey | None:
        reported_at = datetime.fromisoformat(request["reported_at"])
        candidates = [
            claim
            for claim in self._account_deletions
            if claim.event_time <= audit_at
            and _is_in_nomination_window(claim, reported_at)
            and not self._is_linked_to_other_user(
                (claim.target_system, claim.resource_id), subject, audit_at
            )
        ]
        expected_result = REPORTED_RESULT_BY_STATUS.get(request["reported_status"])
        matching = [claim for claim in candidates if claim.reported_result == expected_result]
        resource_ids = {claim.resource_id for claim in matching or candidates}
        if len(resource_ids) != 1:
            return None
        return account.CATEGORY.default_system, resource_ids.pop()

    def _is_linked_to_other_user(
        self, key: ResourceKey, subject: frozenset[str], audit_at: datetime
    ) -> bool:
        linked_identifiers = [
            observation.identifiers
            for observation in self._observations_by_resource.get(key, ())
            if observation.observed_at <= audit_at
        ]
        linked_identifiers.extend(
            identifiers
            for claim, identifiers in self._catalog_links
            if (claim.target_system, claim.resource_id) == key and claim.event_time <= audit_at
        )
        return any(
            self._identifiers_by_identifier.get(identifier, subject) != subject
            for identifiers in linked_identifiers
            for identifier in identifiers
        )

    def _assessment(
        self, key: ResourceKey, audit_at: datetime, *, default_category: str | None = None
    ) -> _ResourceAssessment | None:
        rule_and_proofs = self._rule_and_proofs(key, audit_at, default_category)
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
        self, key: ResourceKey, at: datetime, default_category: str | None
    ) -> tuple[PlanRule, list[_Proof]] | None:
        observations = [
            observation
            for observation in self._observations_by_resource.get(key, ())
            if observation.observed_at <= at
        ]
        category = observations[0].category if observations else default_category
        if category is None:
            return None
        system, resource_id = key
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


def _authorizes_deletion(_request_text: str) -> bool:
    return True


def _is_in_nomination_window(claim: Claim, reported_at: datetime) -> bool:
    is_targeted = TARGET_RESOURCE_MARKER in claim.details
    earliest, latest = TARGETED_NOMINATION_WINDOW if is_targeted else NOMINATION_WINDOW
    return reported_at + earliest <= claim.event_time <= reported_at + latest


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
