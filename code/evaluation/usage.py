from __future__ import annotations

import dataclasses
import json
import typing

if typing.TYPE_CHECKING:
    import pathlib

MODEL_PRICES = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}


@dataclasses.dataclass(frozen=True)
class ModelCost:
    """Usage and estimated cost for a model."""

    provider: str
    model: str
    calls: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    average_tokens_per_request: float
    estimated_cost_usd: float
    cost_per_request_usd: float


@dataclasses.dataclass(frozen=True)
class UsageSummary:
    """Per-model and overall usage totals."""

    models: tuple[ModelCost, ...]
    overall: UsageTotals


@dataclasses.dataclass(frozen=True)
class UsageTotals:
    """Aggregate usage and estimated cost across all models."""

    calls: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    average_tokens_per_request: float
    estimated_cost_usd: float
    cost_per_request_usd: float


def usage_summary(usage_path: pathlib.Path, request_count: int) -> UsageSummary:
    """Return priced model usage for a run."""
    model_costs = tuple(_model_cost(record, request_count) for record in _usage_records(usage_path))
    return UsageSummary(models=model_costs, overall=_overall_cost(model_costs, request_count))


def format_usage_summary(summary: UsageSummary) -> str:
    """Format a compact plain-text usage table."""
    rows = [
        "usage:",
        "provider | model | calls | input | output | total | avg/request | cost | cost/request",
    ]
    rows.extend(_format_cost(cost) for cost in summary.models)
    rows.append(_format_totals(summary.overall))
    return "\n".join(rows)


def _usage_records(usage_path: pathlib.Path) -> list[_UsageRecord]:
    decoded_usage = typing.cast("object", json.loads(usage_path.read_text(encoding="utf-8")))
    if not isinstance(decoded_usage, dict):
        raise TypeError("usage JSON must be an object")
    raw_usage = typing.cast("dict[str, object]", decoded_usage)
    raw_models = raw_usage.get("models")
    if not isinstance(raw_models, list):
        raise TypeError("usage JSON must contain models")
    model_values = typing.cast("list[object]", raw_models)
    return [_usage_record(raw_model) for raw_model in model_values]


def _usage_record(raw_model: object) -> _UsageRecord:
    if not isinstance(raw_model, dict):
        raise TypeError("usage model must be an object")
    model_values = typing.cast("dict[str, object]", raw_model)
    provider = model_values.get("provider")
    model = model_values.get("model")
    calls = model_values.get("calls")
    input_tokens = model_values.get("input_tokens")
    output_tokens = model_values.get("output_tokens")
    if not isinstance(provider, str) or not isinstance(model, str):
        raise TypeError("usage model must name a provider and model")
    if (
        not isinstance(calls, int)
        or not isinstance(input_tokens, int)
        or not isinstance(output_tokens, int)
    ):
        raise TypeError("usage model token counts must be integers")
    return _UsageRecord(
        provider=provider,
        model=model,
        calls=calls,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def _model_cost(record: _UsageRecord, request_count: int) -> ModelCost:
    try:
        input_rate, output_rate = MODEL_PRICES[record.model]
    except KeyError as error:
        raise ValueError(f"missing price for model: {record.model}") from error
    total_tokens = record.input_tokens + record.output_tokens
    estimated_cost = (
        record.input_tokens * input_rate + record.output_tokens * output_rate
    ) / 1_000_000
    return ModelCost(
        provider=record.provider,
        model=record.model,
        calls=record.calls,
        input_tokens=record.input_tokens,
        output_tokens=record.output_tokens,
        total_tokens=total_tokens,
        average_tokens_per_request=total_tokens / request_count,
        estimated_cost_usd=estimated_cost,
        cost_per_request_usd=estimated_cost / request_count,
    )


def _overall_cost(model_costs: tuple[ModelCost, ...], request_count: int) -> UsageTotals:
    calls = sum(model_cost.calls for model_cost in model_costs)
    input_tokens = sum(model_cost.input_tokens for model_cost in model_costs)
    output_tokens = sum(model_cost.output_tokens for model_cost in model_costs)
    total_tokens = input_tokens + output_tokens
    estimated_cost = sum(model_cost.estimated_cost_usd for model_cost in model_costs)
    return UsageTotals(
        calls=calls,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        average_tokens_per_request=total_tokens / request_count,
        estimated_cost_usd=estimated_cost,
        cost_per_request_usd=estimated_cost / request_count,
    )


def _format_cost(cost: ModelCost) -> str:
    return (
        f"{cost.provider} | {cost.model} | {cost.calls} | {cost.input_tokens} | "
        f"{cost.output_tokens} | {cost.total_tokens} | {cost.average_tokens_per_request:.2f} | "
        f"${cost.estimated_cost_usd:.6f} | ${cost.cost_per_request_usd:.6f}"
    )


def _format_totals(totals: UsageTotals) -> str:
    return (
        f"overall | all models | {totals.calls} | {totals.input_tokens} | "
        f"{totals.output_tokens} | {totals.total_tokens} | "
        f"{totals.average_tokens_per_request:.2f} | ${totals.estimated_cost_usd:.6f} | "
        f"${totals.cost_per_request_usd:.6f}"
    )


@dataclasses.dataclass(frozen=True)
class _UsageRecord:
    provider: str
    model: str
    calls: int
    input_tokens: int
    output_tokens: int
