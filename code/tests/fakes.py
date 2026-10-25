import json
from collections.abc import Callable, Iterable

import httpx2 as httpx
import openai

from ghost_audit.intent import USER_MESSAGE_PREFIX
from ghost_audit.llm import Completion, StructuredRequest

REQUEST = httpx.Request("POST", "https://example.test")
NO_DELETE_MARKER = "NO_DELETE"


class FakeTransport:
    """Record each request and answer it with `respond`."""

    def __init__(self, respond: Callable[[StructuredRequest], Completion]) -> None:
        self.requests: list[StructuredRequest] = []
        self._respond = respond

    async def complete(self, request: StructuredRequest) -> Completion:
        self.requests.append(request)
        return self._respond(request)


def decide_intent(request: StructuredRequest) -> Completion:
    """Authorize deletion unless the request text contains the no-delete marker."""
    request_text = json.loads(request.user_message.removeprefix(USER_MESSAGE_PREFIX))
    decision = {
        "reasoning": "The marker determines this offline test decision.",
        "authorizes_deletion": NO_DELETE_MARKER not in request_text,
    }
    return Completion(text=json.dumps(decision), input_tokens=3, output_tokens=5)


def scripted(
    responses: Iterable[Completion | Exception],
) -> Callable[[StructuredRequest], Completion]:
    """Return each scripted completion in turn, raising scripted errors."""
    remaining = iter(responses)

    def respond(_request: StructuredRequest) -> Completion:
        response = next(remaining)
        if isinstance(response, Exception):
            raise response
        return response

    return respond


def fail_to_connect(_request: StructuredRequest) -> Completion:
    raise openai.APIConnectionError(request=REQUEST)
