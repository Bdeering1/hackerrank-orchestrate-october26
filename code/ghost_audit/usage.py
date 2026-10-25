from __future__ import annotations

import json
import typing

if typing.TYPE_CHECKING:
    import pathlib


class UsageTracker:
    """Collect model-token usage for one agent run."""

    def __init__(self) -> None:
        self._models: dict[tuple[str, str], _ModelUsage] = {}

    def record(self, provider: str, model: str, input_tokens: int, output_tokens: int) -> None:
        """Record one model call."""
        usage = self._models.setdefault(
            (provider, model),
            {
                "provider": provider,
                "model": model,
                "calls": 0,
                "input_tokens": 0,
                "output_tokens": 0,
            },
        )
        usage["calls"] += 1
        usage["input_tokens"] += input_tokens
        usage["output_tokens"] += output_tokens

    def write(self, usage_path: pathlib.Path) -> None:
        """Write deterministic usage JSON to a path."""
        models = [self._models[key] for key in sorted(self._models)]
        usage_path.write_text(json.dumps({"models": models}), encoding="utf-8")


class _ModelUsage(typing.TypedDict):
    provider: str
    model: str
    calls: int
    input_tokens: int
    output_tokens: int
