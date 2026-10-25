import asyncio
import json
from pathlib import Path

import httpx2 as httpx
import openai
import pytest
from pydantic import BaseModel

from ghost_audit.llm import CONCURRENCY_LIMIT, Completion, LLMError, StructuredLLM
from ghost_audit.usage import UsageTracker
from tests.fakes import REQUEST, FakeTransport, scripted


class Answer(BaseModel):
    answer: bool


def test_parse_uses_disk_cache_and_cache_key_inputs(tmp_path: Path) -> None:
    transport = FakeTransport(
        scripted(
            [
                Completion('{"answer": true}', 1, 2),
                Completion('{"answer": false}', 3, 4),
                Completion('{"answer": true}', 5, 6),
            ]
        )
    )
    usage = UsageTracker()
    llm = StructuredLLM(transport, usage, tmp_path)

    assert asyncio.run(llm.parse("test/one", "prompt", "message", Answer)).answer
    repeat_run_llm = StructuredLLM(transport, usage, tmp_path)
    assert asyncio.run(repeat_run_llm.parse("test/one", "prompt", "message", Answer)).answer
    assert not asyncio.run(llm.parse("test/two", "prompt", "message", Answer)).answer
    assert asyncio.run(llm.parse("test/one", "other prompt", "message", Answer)).answer

    assert len(transport.requests) == 3
    usage_path = tmp_path / "usage.json"
    usage.write(usage_path)
    assert json.loads(usage_path.read_text(encoding="utf-8")) == {
        "models": [
            {"provider": "test", "model": "one", "calls": 2, "input_tokens": 6, "output_tokens": 8},
            {"provider": "test", "model": "two", "calls": 1, "input_tokens": 3, "output_tokens": 4},
        ]
    }


@pytest.mark.parametrize(
    "error",
    [
        openai.APIConnectionError(request=REQUEST),
        openai.APITimeoutError(request=REQUEST),
        openai.RateLimitError(
            "rate limited", response=httpx.Response(429, request=REQUEST), body=None
        ),
        openai.InternalServerError(
            "server error", response=httpx.Response(500, request=REQUEST), body=None
        ),
    ],
)
def test_parse_retries_transient_failures(tmp_path: Path, error: Exception) -> None:
    transport = FakeTransport(scripted([error, Completion('{"answer": true}', 1, 2)]))

    async def sleep(delay: float) -> None:
        return None

    llm = StructuredLLM(transport, UsageTracker(), tmp_path, sleep=sleep)

    assert asyncio.run(llm.parse("test/one", "prompt", "message", Answer)).answer
    assert len(transport.requests) == 2


def test_parse_retries_invalid_json_and_records_its_usage(tmp_path: Path) -> None:
    transport = FakeTransport(
        scripted([Completion("invalid", 2, 3), Completion('{"answer": true}', 5, 7)])
    )
    usage = UsageTracker()

    async def sleep(delay: float) -> None:
        return None

    llm = StructuredLLM(transport, usage, tmp_path, sleep=sleep)

    assert asyncio.run(llm.parse("test/one", "prompt", "message", Answer)).answer
    usage_path = tmp_path / "usage.json"
    usage.write(usage_path)
    assert json.loads(usage_path.read_text(encoding="utf-8")) == {
        "models": [
            {"provider": "test", "model": "one", "calls": 2, "input_tokens": 7, "output_tokens": 10}
        ]
    }


def test_parse_does_not_retry_non_transient_errors(tmp_path: Path) -> None:
    response = httpx.Response(400, request=REQUEST)
    transport = FakeTransport(
        scripted([openai.BadRequestError("bad request", response=response, body=None)])
    )
    llm = StructuredLLM(transport, UsageTracker(), tmp_path)

    with pytest.raises(LLMError):
        asyncio.run(llm.parse("test/one", "prompt", "message", Answer))

    assert len(transport.requests) == 1


def test_parse_raises_after_transient_attempts_are_exhausted(tmp_path: Path) -> None:
    error = openai.APIConnectionError(request=REQUEST)
    transport = FakeTransport(scripted([error, error]))

    async def sleep(delay: float) -> None:
        return None

    llm = StructuredLLM(transport, UsageTracker(), tmp_path, max_attempts=2, sleep=sleep)

    with pytest.raises(LLMError):
        asyncio.run(llm.parse("test/one", "prompt", "message", Answer))

    assert len(transport.requests) == 2


def test_parse_treats_invalid_cache_entry_as_miss(tmp_path: Path) -> None:
    transport = FakeTransport(scripted([Completion('{"answer": true}', 1, 2)] * 2))
    llm = StructuredLLM(transport, UsageTracker(), tmp_path)
    asyncio.run(llm.parse("test/one", "prompt", "message", Answer))
    (cache_path,) = tmp_path.glob("*.json")
    cache_path.write_text("corrupt", encoding="utf-8")

    assert asyncio.run(llm.parse("test/one", "prompt", "message", Answer)).answer
    assert len(transport.requests) == 2


def test_parse_limits_concurrency_across_event_loops(tmp_path: Path) -> None:
    transport = FakeTransport(lambda _request: Completion('{"answer": true}', 1, 2))
    llm = StructuredLLM(transport, UsageTracker(), tmp_path)

    async def parse_concurrently(run: int) -> None:
        messages = [f"run {run} message {index}" for index in range(CONCURRENCY_LIMIT + 1)]
        await asyncio.gather(*(llm.parse("test/one", "prompt", m, Answer) for m in messages))

    asyncio.run(parse_concurrently(1))
    asyncio.run(parse_concurrently(2))

    assert len(transport.requests) == 2 * (CONCURRENCY_LIMIT + 1)
