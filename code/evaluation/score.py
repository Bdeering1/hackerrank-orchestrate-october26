from __future__ import annotations

import json
import typing
from collections import Counter
from dataclasses import dataclass

from evaluation.validate import Step, data_rows

if typing.TYPE_CHECKING:
    from collections.abc import Collection, Iterable
    from pathlib import Path


@dataclass(frozen=True)
class MetricDefinition:
    label: str
    weight: float
    definition: str
    attribute: str


METRICS = (
    MetricDefinition("Status", 0.40, "Exact deletion-status match.", "status"),
    MetricDefinition("Step", 0.30, "Multiset F1 over steps, ignoring step_no.", "step"),
    MetricDefinition(
        "Field",
        0.15,
        "Operation, state, and evidence agreement for steps aligned by phase, system, and resource.",
        "field",
    ),
    MetricDefinition(
        "Sequence",
        0.15,
        "Exact positional step matches over the longer step list.",
        "sequence",
    ),
)


@dataclass(frozen=True)
class CaseScore:
    case_id: str
    expected_status: str
    predicted_status: str | None
    status: float
    step: float
    field: float
    sequence: float
    composite: float


def case_scores(predictions_path: Path, labels_path: Path) -> list[CaseScore]:
    """Return weighted scores for every labelled case in numeric case order."""
    predictions = _rows_by_case(predictions_path)
    labels = _rows_by_case(labels_path)
    scores: list[CaseScore] = []
    for case_id, (expected_status, expected_steps) in labels.items():
        predicted = predictions.get(case_id)
        if predicted is None:
            predicted_status: str | None = None
            status = step = field = sequence = 0.0
        else:
            predicted_status, predicted_steps = predicted
            status = float(predicted_status == expected_status)
            step = _step_f1(predicted_steps, expected_steps)
            field = _field_score(predicted_steps, expected_steps)
            sequence = _sequence_score(predicted_steps, expected_steps)
        composite = 100 * sum(
            metric.weight * _metric_value(metric.attribute, status, step, field, sequence)
            for metric in METRICS
        )
        scores.append(
            CaseScore(
                case_id,
                expected_status,
                predicted_status,
                status,
                step,
                field,
                sequence,
                composite,
            )
        )
    return sorted(scores, key=lambda score: _case_number(score.case_id))


def render_markdown(scores: Collection[CaseScore]) -> str:
    """Render scores as the evaluation report's Markdown section."""
    score_list = list(scores)
    metric_means = {
        metric.attribute: _mean(
            _metric_value(metric.attribute, score.status, score.step, score.field, score.sequence)
            for score in score_list
        )
        for metric in METRICS
    }
    average_composite = _mean(score.composite for score in score_list)
    status_match_count = sum(score.status == 1 for score in score_list)
    lines = [
        "## Summary",
        "",
        "| Metric | Weight | Definition | Mean |",
        "| --- | ---: | --- | ---: |",
    ]
    lines.extend(
        f"| {metric.label} | {metric.weight:.0%} | {metric.definition} | {metric_means[metric.attribute]:.1%} |"
        for metric in METRICS
    )
    lines.extend(
        [
            "",
            f"Average composite: {average_composite:.1f}%",
            f"Status matches: {status_match_count}/{len(score_list)}",
            "",
            "## Per-case scores",
            "",
            "| Case ID | Expected status | Predicted status | Step | Field | Sequence | Composite |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    lines.extend(
        f"| {score.case_id} | {score.expected_status} | {score.predicted_status or ''} | {score.step:.1%} | {score.field:.1%} | {score.sequence:.1%} | {score.composite:.1f}% |"
        for score in score_list
    )
    return "\n".join(lines) + "\n"


def _metric_value(
    attribute: str, status: float, step: float, field: float, sequence: float
) -> float:
    return {"status": status, "step": step, "field": field, "sequence": sequence}[attribute]


def _rows_by_case(path: Path) -> dict[str, tuple[str, list[Step]]]:
    return {row[0]: (row[1], _steps(row[2])) for row in data_rows(path)}


def _steps(steps_json: str) -> list[Step]:
    parsed = typing.cast("object", json.loads(steps_json))
    if not isinstance(parsed, list):
        raise TypeError("steps_json is not a JSON array")
    return [typing.cast("Step", step) for step in typing.cast("list[object]", parsed)]


def _step_f1(predicted_steps: list[Step], expected_steps: list[Step]) -> float:
    if not predicted_steps and not expected_steps:
        return 1.0
    predicted_counts = Counter(_step_content(step) for step in predicted_steps)
    expected_counts = Counter(_step_content(step) for step in expected_steps)
    matched_steps = sum((predicted_counts & expected_counts).values())
    return 2 * matched_steps / (len(predicted_steps) + len(expected_steps))


def _field_score(predicted_steps: list[Step], expected_steps: list[Step]) -> float:
    if not predicted_steps and not expected_steps:
        return 1.0
    predicted_by_key = _first_steps_by_key(predicted_steps)
    expected_by_key = _first_steps_by_key(expected_steps)
    aligned_keys = predicted_by_key.keys() & expected_by_key.keys()
    matching_fields = sum(
        predicted_by_key[key][field] == expected_by_key[key][field]
        for key in aligned_keys
        for field in ("operation", "state", "evidence_id")
    )
    denominator = 3 * (
        len(aligned_keys)
        + len(expected_by_key.keys() - predicted_by_key.keys())
        + len(predicted_by_key.keys() - expected_by_key.keys())
    )
    return matching_fields / denominator


def _sequence_score(predicted_steps: list[Step], expected_steps: list[Step]) -> float:
    if not predicted_steps and not expected_steps:
        return 1.0
    matching_steps = sum(
        _all_fields_match(predicted_step, expected_step)
        for predicted_step, expected_step in zip(predicted_steps, expected_steps, strict=False)
    )
    return matching_steps / max(len(predicted_steps), len(expected_steps))


def _step_content(step: Step) -> tuple[str, str, str, str, str, str]:
    return (
        step["phase"],
        step["system_id"],
        step["resource_id"],
        step["operation"],
        step["state"],
        step["evidence_id"],
    )


def _first_steps_by_key(steps: list[Step]) -> dict[tuple[str, str, str], Step]:
    first_steps: dict[tuple[str, str, str], Step] = {}
    for step in steps:
        key = (step["phase"], step["system_id"], step["resource_id"])
        first_steps.setdefault(key, step)
    return first_steps


def _all_fields_match(predicted_step: Step, expected_step: Step) -> bool:
    return predicted_step["step_no"] == expected_step["step_no"] and _step_content(
        predicted_step
    ) == _step_content(expected_step)


def _case_number(case_id: str) -> int:
    return int(case_id.removeprefix("case_"))


def _mean(values: Iterable[float]) -> float:
    value_list = list(values)
    return sum(value_list) / len(value_list) if value_list else 0.0
