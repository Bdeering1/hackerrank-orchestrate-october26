"""Structured gateway LLM access with caching, retries, and usage tracking."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import pathlib
import random
import typing
import uuid
import weakref
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
CONCURRENCY_LIMIT = 8
JITTER = random.SystemRandom()

Sleep = Callable[[float], Awaitable[None]]


class LLMError(Exception):
    """Raised when a structured LLM request cannot complete."""


@dataclass(frozen=True)
class Completion:
    """A completed LLM response and its billed token counts."""

    text: str
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class StructuredRequest:
    """One prompt and the JSON schema its response must match."""

    model: str
    system_prompt: str
    user_message: str
    schema_name: str
    schema: dict[str, object]


class Transport(typing.Protocol):
    """Send one structured request to an LLM provider."""

    async def complete(self, request: StructuredRequest) -> Completion:
        """Return a structured completion."""
        ...


class GatewayTransport:
    """Use Vercel AI Gateway through the OpenAI SDK."""

    def __init__(self) -> None:
        self._client: openai.AsyncOpenAI | None = None

    async def complete(self, request: StructuredRequest) -> Completion:
        """Request a JSON-schema constrained completion."""
        response_format = typing.cast(
            "ResponseFormatJSONSchema",
            {
                "type": "json_schema",
                "json_schema": {
                    "name": request.schema_name,
                    "schema": request.schema,
                    "strict": True,
                },
            },
        )
        response = await self._connected_client().chat.completions.create(
            model=request.model,
            messages=[
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_message},
            ],
            response_format=response_format,
            temperature=0,
        )
        usage = response.usage
        return Completion(
            text=(response.choices[0].message.content or "") if response.choices else "",
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
        )

    def _connected_client(self) -> openai.AsyncOpenAI:
        if self._client is not None:
            return self._client
        api_key = os.environ.get(API_KEY_ENV)
        if api_key is None:
            message = f"{API_KEY_ENV} is not set; export it or run with `uv run --env-file ../.env`"
            raise LLMError(message)
        self._client = openai.AsyncOpenAI(
            base_url=GATEWAY_BASE_URL,
            api_key=api_key,
            max_retries=0,
            timeout=60.0,
        )
        return self._client


class StructuredLLM:
    """Parse cached or gateway-backed responses into Pydantic models."""

    def __init__(
        self,
        transport: Transport,
        usage_tracker: UsageTracker,
        cache_dir: pathlib.Path,
        max_attempts: int = 4,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._transport = transport
        self._usage_tracker = usage_tracker
        self._cache_dir = cache_dir
        self._semaphores: weakref.WeakKeyDictionary[
            asyncio.AbstractEventLoop, asyncio.Semaphore
        ] = weakref.WeakKeyDictionary()
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
        request = StructuredRequest(
            model=model,
            system_prompt=system_prompt,
            user_message=user_message,
            schema_name=response_type.__name__,
            schema=typing.cast("dict[str, object]", response_type.model_json_schema()),
        )
        cache_path = self._cache_path(request)
        if cache_path.exists():
            try:
                return response_type.model_validate_json(cache_path.read_text(encoding="utf-8"))
            except ValidationError:
                pass

        provider, model_name = model.split("/", maxsplit=1)
        last_error: Exception | None = None
        for attempt in range(self._max_attempts):
            try:
                async with self._loop_semaphore():
                    completion = await self._transport.complete(request)
                self._usage_tracker.record(
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
            except openai.APIError as error:
                message = f"LLM request failed: {error!r}"
                raise LLMError(message) from error
            else:
                self._write_cache(cache_path, completion.text)
                return result

            if attempt + 1 < self._max_attempts:
                await self._sleep(_retry_delay(attempt, last_error))

        message = f"LLM request failed after retries: {last_error!r}"
        raise LLMError(message) from last_error

    def _loop_semaphore(self) -> asyncio.Semaphore:
        """Return this event loop's semaphore, since an asyncio semaphore is bound to one loop."""
        return self._semaphores.setdefault(
            asyncio.get_running_loop(), asyncio.Semaphore(CONCURRENCY_LIMIT)
        )

    def _cache_path(self, request: StructuredRequest) -> pathlib.Path:
        cache_input = json.dumps(
            {
                "model": request.model,
                "system_prompt": request.system_prompt,
                "schema": request.schema,
                "user_message": request.user_message,
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


def _retry_delay(attempt: int, error: Exception) -> float:
    """Back off exponentially with jitter, waiting at least as long as a 429 asks."""
    delay = (1 << attempt) * JITTER.uniform(1.0, 1.5)
    if isinstance(error, openai.RateLimitError):
        retry_after = error.response.headers.get("retry-after", "")
        if retry_after.isdecimal():
            delay = max(delay, float(retry_after))
    return delay


def connect(usage_tracker: UsageTracker) -> StructuredLLM:
    """Create the production LLM client."""
    return StructuredLLM(GatewayTransport(), usage_tracker, DEFAULT_CACHE_DIR)
