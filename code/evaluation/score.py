from __future__ import annotations

import json
import typing
from collections import Counter, defaultdict
from dataclasses import dataclass

from evaluation.validate import Step, data_rows
from ghost_audit.output_format import case_number

if typing.TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable
    from pathlib import Path

COMPARED_FIELDS: typing.Final = ("operation", "state", "evidence_id")


@dataclass(frozen=True)
class Ratio:
    numerator: int
    denominator: int

    @property
    def value(self) -> float:
        """Return the ratio, or 1.0 when there is nothing to compare."""
        return self.numerator / self.denominator if self.denominator else 1.0

    def __add__(self, other: Ratio) -> Ratio:
        return Ratio(self.numerator + other.numerator, self.denominator + other.denominator)


@dataclass(frozen=True)
class MetricDefinition:
    label: str
    weight: float
    definition: str
    ratio: Callable[[CaseScore], Ratio]


METRICS = (
    MetricDefinition(
        "Status",
        0.25,
        "Exact deletion-status match, averaged over cases.",
        lambda score: score.status_match,
    ),
    MetricDefinition(
        "Step",
        0.35,
        "Multiset F1 over all steps pooled across cases, ignoring step_no.",
        lambda score: score.step_f1,
    ),
    MetricDefinition(
        "Field",
        0.30,
        "Operation, state, and evidence agreement over all steps pooled across cases, "
        "aligned by phase, system, and resource.",
        lambda score: score.field_accuracy,
    ),
    MetricDefinition(
        "Sequence",
        0.10,
        "1 minus the summed step edit distances, divided by the summed longer step-list lengths.",
        lambda score: score.sequence_similarity,
    ),
)


@dataclass(frozen=True)
class CaseScore:
    case_id: str
    expected_status: str
    predicted_status: str | None
    status_match: Ratio
    step_f1: Ratio
    field_accuracy: Ratio
    sequence_similarity: Ratio

    @property
    def composite(self) -> float:
        """Weighted 0-100 composite of this case's metrics."""
        return 100 * sum(metric.weight * metric.ratio(self).value for metric in METRICS)


def case_scores(predictions_path: Path, labels_path: Path) -> list[CaseScore]:
    """Return weighted scores for every labelled case in numeric case order.

    Predictions must already pass validation.
    """
    predictions = _rows_by_case(predictions_path)
    labels = _rows_by_case(labels_path)
    scores: list[CaseScore] = []
    for case_id, (expected_status, expected_steps) in labels.items():
        predicted = predictions.get(case_id)
        if predicted is None:
            step_count = max(1, len(expected_steps))
            missing_step_ratios = (
                Ratio(0, step_count),
                Ratio(0, len(COMPARED_FIELDS) * step_count),
                Ratio(0, step_count),
            )
            scores.append(
                CaseScore(case_id, expected_status, None, Ratio(0, 1), *missing_step_ratios)
            )
            continue
        predicted_status, predicted_steps = predicted
        scores.append(
            CaseScore(
                case_id,
                expected_status,
                predicted_status,
                Ratio(int(predicted_status == expected_status), 1),
                _step_f1(predicted_steps, expected_steps),
                _field_score(predicted_steps, expected_steps),
                _sequence_score(predicted_steps, expected_steps),
            )
        )
    return sorted(scores, key=lambda score: case_number(score.case_id))


def pooled_composite(scores: Collection[CaseScore]) -> float:
    """Weighted 0-100 composite of each metric pooled across cases."""
    return 100 * sum(metric.weight * _pooled_ratio(metric, scores).value for metric in METRICS)


def render_markdown(scores: Collection[CaseScore]) -> str:
    """Render scores as the evaluation report's Markdown section."""
    status_match_count = sum(score.status_match.numerator for score in scores)
    lines = [
        "## Summary",
        "",
        "| Metric | Weight | Definition | Score |",
        "| --- | ---: | --- | ---: |",
    ]
    lines.extend(
        f"| {metric.label} | {metric.weight:.0%} | {metric.definition} | "
        f"{_pooled_ratio(metric, scores).value:.1%} |"
        for metric in METRICS
    )
    lines.extend(
        [
            "",
            f"Composite: {pooled_composite(scores):.1f}%",
            f"Status matches: {status_match_count}/{len(scores)}",
            "",
            "## Per-case scores",
            "",
            "| Case ID | Expected status | Predicted status | Step | Field | Sequence | Composite |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    lines.extend(
        f"| {score.case_id} | {score.expected_status} | {score.predicted_status or ''} | "
        f"{score.step_f1.value:.1%} | {score.field_accuracy.value:.1%} | "
        f"{score.sequence_similarity.value:.1%} | {score.composite:.1f}% |"
        for score in scores
    )
    return "\n".join(lines) + "\n"


def _rows_by_case(path: Path) -> dict[str, tuple[str, list[Step]]]:
    return {row[0]: (row[1], _steps(row[2])) for row in data_rows(path)}


def _steps(steps_json: str) -> list[Step]:
    parsed = typing.cast("object", json.loads(steps_json))
    if not isinstance(parsed, list):
        raise TypeError("steps_json is not a JSON array")
    return [typing.cast("Step", step) for step in typing.cast("list[object]", parsed)]


def _pooled_ratio(metric: MetricDefinition, scores: Iterable[CaseScore]) -> Ratio:
    return sum((metric.ratio(score) for score in scores), Ratio(0, 0))


def _step_f1(predicted_steps: list[Step], expected_steps: list[Step]) -> Ratio:
    predicted_counts = Counter(_step_content(step) for step in predicted_steps)
    expected_counts = Counter(_step_content(step) for step in expected_steps)
    matched_steps = sum((predicted_counts & expected_counts).values())
    return Ratio(2 * matched_steps, len(predicted_steps) + len(expected_steps))


def _field_score(predicted_steps: list[Step], expected_steps: list[Step]) -> Ratio:
    predicted_by_key = _steps_by_key(predicted_steps)
    expected_by_key = _steps_by_key(expected_steps)
    aligned_pairs = [
        aligned_pair
        for key in predicted_by_key.keys() & expected_by_key.keys()
        for aligned_pair in zip(predicted_by_key[key], expected_by_key[key], strict=False)
    ]
    matching_fields = sum(
        predicted_step[field] == expected_step[field]
        for predicted_step, expected_step in aligned_pairs
        for field in COMPARED_FIELDS
    )
    unaligned_count = len(predicted_steps) + len(expected_steps) - 2 * len(aligned_pairs)
    return Ratio(matching_fields, len(COMPARED_FIELDS) * (len(aligned_pairs) + unaligned_count))


def _sequence_score(predicted_steps: list[Step], expected_steps: list[Step]) -> Ratio:
    edit_distance = _edit_distance(
        [_step_content(step) for step in predicted_steps],
        [_step_content(step) for step in expected_steps],
    )
    longer_step_count = max(len(predicted_steps), len(expected_steps))
    return Ratio(longer_step_count - edit_distance, longer_step_count)


def _edit_distance[T](predicted_items: list[T], expected_items: list[T]) -> int:
    previous_row = list(range(len(expected_items) + 1))
    for row_index, predicted_item in enumerate(predicted_items, start=1):
        current_row = [row_index]
        for column_index, expected_item in enumerate(expected_items, start=1):
            current_row.append(
                min(
                    previous_row[column_index] + 1,
                    current_row[column_index - 1] + 1,
                    previous_row[column_index - 1] + (predicted_item != expected_item),
                )
            )
        previous_row = current_row
    return previous_row[-1]


def _step_content(step: Step) -> tuple[str, str, str, str, str, str]:
    return (
        step["phase"],
        step["system_id"],
        step["resource_id"],
        step["operation"],
        step["state"],
        step["evidence_id"],
    )


def _steps_by_key(steps: list[Step]) -> dict[tuple[str, str, str], list[Step]]:
    steps_by_key: defaultdict[tuple[str, str, str], list[Step]] = defaultdict(list)
    for step in steps:
        steps_by_key[(step["phase"], step["system_id"], step["resource_id"])].append(step)
    return steps_by_key
