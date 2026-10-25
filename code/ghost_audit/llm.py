"""Structured gateway LLM access with caching, retries, and usage tracking."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import pathlib
import typing
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import openai
from pydantic import BaseModel, ValidationError

if typing.TYPE_CHECKING:
    from openai.types.shared_params.response_format_json_schema import ResponseFormatJSONSchema

    from ghost_audit.usage import UsageTracker

GATEWAY_BASE_URL = "https://ai-gateway.vercel.sh/v1"
API_KEY_ENV = "AI_GATEWAY_API_KEY"
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_CACHE_DIR = REPO_ROOT / ".cache" / "llm"

Sleep = Callable[[float], Awaitable[None]]


class LLMError(Exception):
    """Raised when a structured LLM request cannot complete."""


@dataclass(frozen=True)
class Completion:
    """A completed LLM response and its billed token counts."""

    text: str
    input_tokens: int
    output_tokens: int


class Transport(typing.Protocol):
    """Send one structured request to an LLM provider."""

    async def complete(
        self,
        model: str,
        system_prompt: str,
        user_message: str,
        schema_name: str,
        schema: dict[str, object],
    ) -> Completion:
        """Return a structured completion."""
        ...


class GatewayTransport:
    """Use Vercel AI Gateway through the OpenAI SDK."""

    def __init__(self) -> None:
        api_key = os.environ.get(API_KEY_ENV)
        if api_key is None:
            message = f"{API_KEY_ENV} is not set"
            raise LLMError(message)
        self._client = openai.AsyncOpenAI(
            base_url=GATEWAY_BASE_URL,
            api_key=api_key,
            max_retries=0,
            timeout=60.0,
        )

    async def complete(
        self,
        model: str,
        system_prompt: str,
        user_message: str,
        schema_name: str,
        schema: dict[str, object],
    ) -> Completion:
        """Request a JSON-schema constrained completion."""
        response_format = typing.cast(
            "ResponseFormatJSONSchema",
            {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "schema": schema,
                    "strict": True,
                },
            },
        )
        response = await self._client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            response_format=response_format,
        )
        content = response.choices[0].message.content
        if content is None:
            raise LLMError("gateway returned an empty completion")
        usage = response.usage
        if usage is None:
            raise LLMError("gateway response did not include usage")
        return Completion(
            text=content,
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
        )


class StructuredLLM:
    """Parse cached or gateway-backed responses into Pydantic models."""

    def __init__(
        self,
        transport: Transport,
        usage: UsageTracker,
        cache_dir: pathlib.Path,
        concurrency_limit: int = 8,
        max_attempts: int = 4,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._transport = transport
        self._usage = usage
        self._cache_dir = cache_dir
        self._semaphore = asyncio.Semaphore(concurrency_limit)
        self._max_attempts = max_attempts
        self._sleep = sleep

    async def parse[T: BaseModel](
        self,
        model: str,
        system_prompt: str,
        user_message: str,
        response_type: type[T],
    ) -> T:
        """Return a validated structured response."""
        schema = typing.cast("dict[str, object]", response_type.model_json_schema())
        cache_path = self._cache_path(model, system_prompt, user_message, schema)
        if cache_path.exists():
            return response_type.model_validate_json(cache_path.read_text(encoding="utf-8"))

        provider, model_name = model.split("/", maxsplit=1)
        last_error: Exception | None = None
        for attempt in range(self._max_attempts):
            try:
                async with self._semaphore:
                    completion = await self._transport.complete(
                        model,
                        system_prompt,
                        user_message,
                        response_type.__name__,
                        schema,
                    )
                self._usage.record(
                    provider,
                    model_name,
                    completion.input_tokens,
                    completion.output_tokens,
                )
                result = response_type.model_validate_json(completion.text)
            except (
                openai.APIConnectionError,
                openai.RateLimitError,
                openai.InternalServerError,
            ) as error:
                last_error = error
            except ValidationError as error:
                last_error = error
            except Exception as error:
                message = "LLM request failed"
                raise LLMError(message) from error
            else:
                self._write_cache(cache_path, completion.text)
                return result

            if attempt + 1 < self._max_attempts:
                await self._sleep(float(1 << attempt))

        message = "LLM request failed after retries"
        raise LLMError(message) from last_error

    def _cache_path(
        self,
        model: str,
        system_prompt: str,
        user_message: str,
        schema: dict[str, object],
    ) -> pathlib.Path:
        cache_input = json.dumps(
            {
                "model": model,
                "system_prompt": system_prompt,
                "schema": schema,
                "user_message": user_message,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        cache_key = hashlib.sha256(cache_input.encode()).hexdigest()
        return self._cache_dir / f"{cache_key}.json"

    def _write_cache(self, cache_path: pathlib.Path, text: str) -> None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = cache_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        temporary_path.write_text(text, encoding="utf-8")
        temporary_path.replace(cache_path)


def connect(usage: UsageTracker) -> StructuredLLM:
    """Create the production LLM client."""
    return StructuredLLM(GatewayTransport(), usage, DEFAULT_CACHE_DIR)
