import asyncio
from pathlib import Path

import httpx2 as httpx
import openai
import pytest
from pydantic import BaseModel

from ghost_audit.llm import Completion, LLMError, StructuredLLM
from ghost_audit.usage import UsageTracker


class Answer(BaseModel):
    """A structured response used by LLM tests."""

    answer: bool


class ScriptedTransport:
    """Return scripted completions or raise scripted errors."""

    def __init__(self, responses: list[Completion | Exception]) -> None:
        self.responses = iter(responses)
        self.calls = 0

    async def complete(
        self,
        model: str,
        system_prompt: str,
        user_message: str,
        schema_name: str,
        schema: dict[str, object],
    ) -> Completion:
        self.calls += 1
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def test_parse_uses_disk_cache_and_cache_key_inputs(tmp_path: Path) -> None:
    transport = ScriptedTransport(
        [
            Completion('{"answer": true}', 1, 2),
            Completion('{"answer": false}', 3, 4),
            Completion('{"answer": true}', 5, 6),
        ]
    )
    usage = UsageTracker()
    llm = StructuredLLM(transport, usage, tmp_path)

    assert asyncio.run(llm.parse("test/one", "prompt", "message", Answer)).answer
    repeat_run_llm = StructuredLLM(transport, usage, tmp_path)
    assert asyncio.run(repeat_run_llm.parse("test/one", "prompt", "message", Answer)).answer
    assert not asyncio.run(llm.parse("test/two", "prompt", "message", Answer)).answer
    assert asyncio.run(llm.parse("test/one", "other prompt", "message", Answer)).answer

    assert transport.calls == 3
    usage_path = tmp_path / "usage.json"
    usage.write(usage_path)
    assert usage_path.read_text(encoding="utf-8") == (
        '{"models": [{"provider": "test", "model": "one", "calls": 2, '
        '"input_tokens": 6, "output_tokens": 8}, {"provider": "test", "model": "two", '
        '"calls": 1, "input_tokens": 3, "output_tokens": 4}]}'
    )


def test_parse_retries_transient_failures(tmp_path: Path) -> None:
    transport = ScriptedTransport(
        [
            openai.APIConnectionError(request=httpx.Request("POST", "https://example.test")),
            Completion('{"answer": true}', 1, 2),
        ]
    )
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)

    llm = StructuredLLM(transport, UsageTracker(), tmp_path, sleep=sleep)

    assert asyncio.run(llm.parse("test/one", "prompt", "message", Answer)).answer
    assert transport.calls == 2
    assert delays == [1]


def test_parse_retries_invalid_json_and_records_its_usage(tmp_path: Path) -> None:
    transport = ScriptedTransport(
        [Completion("invalid", 2, 3), Completion('{"answer": true}', 5, 7)]
    )
    usage = UsageTracker()

    async def sleep(delay: float) -> None:
        return None

    llm = StructuredLLM(transport, usage, tmp_path, sleep=sleep)

    assert asyncio.run(llm.parse("test/one", "prompt", "message", Answer)).answer
    usage_path = tmp_path / "usage.json"
    usage.write(usage_path)
    assert usage_path.read_text(encoding="utf-8") == (
        '{"models": [{"provider": "test", "model": "one", "calls": 2, '
        '"input_tokens": 7, "output_tokens": 10}]}'
    )


def test_parse_does_not_retry_non_transient_errors(tmp_path: Path) -> None:
    response = httpx.Response(400, request=httpx.Request("POST", "https://example.test"))
    transport = ScriptedTransport(
        [openai.BadRequestError("bad request", response=response, body=None)]
    )
    llm = StructuredLLM(transport, UsageTracker(), tmp_path)

    with pytest.raises(LLMError):
        asyncio.run(llm.parse("test/one", "prompt", "message", Answer))

    assert transport.calls == 1


def test_parse_raises_after_transient_attempts_are_exhausted(tmp_path: Path) -> None:
    error = openai.APIConnectionError(request=httpx.Request("POST", "https://example.test"))
    transport = ScriptedTransport([error, error])

    async def sleep(delay: float) -> None:
        return None

    llm = StructuredLLM(transport, UsageTracker(), tmp_path, max_attempts=2, sleep=sleep)

    with pytest.raises(LLMError):
        asyncio.run(llm.parse("test/one", "prompt", "message", Answer))

    assert transport.calls == 2


def test_parse_treats_invalid_cache_entry_as_miss(tmp_path: Path) -> None:
    transport = ScriptedTransport([Completion('{"answer": true}', 1, 2)] * 2)
    llm = StructuredLLM(transport, UsageTracker(), tmp_path)
    asyncio.run(llm.parse("test/one", "prompt", "message", Answer))
    (cache_path,) = tmp_path.glob("*.json")
    cache_path.write_text("corrupt", encoding="utf-8")

    assert asyncio.run(llm.parse("test/one", "prompt", "message", Answer)).answer
    assert transport.calls == 2
