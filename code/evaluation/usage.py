from __future__ import annotations

import dataclasses
import json
import typing

if typing.TYPE_CHECKING:
    import pathlib

    from ghost_audit.usage import ModelUsage

MODEL_PRICES = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}


@dataclasses.dataclass(frozen=True)
class UsageTotals:
    """Usage and estimated cost for a model or for all models."""

    calls: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float

    @property
    def total_tokens(self) -> int:
        """Return input plus output tokens."""
        return self.input_tokens + self.output_tokens


@dataclasses.dataclass(frozen=True)
class ModelUsageSummary:
    """Usage and estimated cost for a model."""

    provider: str
    model: str
    totals: UsageTotals


@dataclasses.dataclass(frozen=True)
class UsageSummary:
    """Per-model and overall usage totals."""

    models: tuple[ModelUsageSummary, ...]
    overall: UsageTotals
    request_count: int

    def average_tokens_per_request(self, totals: UsageTotals) -> float:
        """Return total tokens divided by requests."""
        return totals.total_tokens / self.request_count

    def cost_per_request_usd(self, totals: UsageTotals) -> float:
        """Return estimated cost divided by requests."""
        return totals.estimated_cost_usd / self.request_count


def usage_summary(usage_path: pathlib.Path, request_count: int) -> UsageSummary:
    """Return priced model usage for a run."""
    usage = typing.cast(
        "dict[str, list[ModelUsage]]", json.loads(usage_path.read_text(encoding="utf-8"))
    )
    models = tuple(_model_usage_summary(model_usage) for model_usage in usage["models"])
    overall = UsageTotals(
        calls=sum(model.totals.calls for model in models),
        input_tokens=sum(model.totals.input_tokens for model in models),
        output_tokens=sum(model.totals.output_tokens for model in models),
        estimated_cost_usd=sum(model.totals.estimated_cost_usd for model in models),
    )
    return UsageSummary(models=models, overall=overall, request_count=request_count)


def format_usage_summary(summary: UsageSummary) -> str:
    """Format a compact plain-text usage table."""
    rows = [
        "usage:",
        "provider | model | calls | input | output | total | avg/request | cost | cost/request",
    ]
    rows.extend(
        _usage_row(summary, model.provider, model.model, model.totals) for model in summary.models
    )
    rows.append(_usage_row(summary, "overall", "all models", summary.overall))
    return "\n".join(rows)


def _model_usage_summary(model_usage: ModelUsage) -> ModelUsageSummary:
    model = model_usage["model"]
    try:
        input_rate, output_rate = MODEL_PRICES[model]
    except KeyError as error:
        raise ValueError(f"missing price for model: {model}") from error
    input_tokens = model_usage["input_tokens"]
    output_tokens = model_usage["output_tokens"]
    totals = UsageTotals(
        calls=model_usage["calls"],
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost_usd=(input_tokens * input_rate + output_tokens * output_rate) / 1_000_000,
    )
    return ModelUsageSummary(provider=model_usage["provider"], model=model, totals=totals)


def _usage_row(summary: UsageSummary, provider: str, model: str, totals: UsageTotals) -> str:
    return (
        f"{provider} | {model} | {totals.calls} | {totals.input_tokens} | "
        f"{totals.output_tokens} | {totals.total_tokens} | "
        f"{summary.average_tokens_per_request(totals):.2f} | ${totals.estimated_cost_usd:.6f} | "
        f"${summary.cost_per_request_usd(totals):.6f}"
    )
