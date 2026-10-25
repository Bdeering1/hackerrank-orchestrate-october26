import json
import os
from pathlib import Path

import pytest

import ghost_audit.llm
from ghost_audit.intent import USER_MESSAGE_PREFIX
from ghost_audit.llm import Completion, StructuredLLM
from ghost_audit.usage import UsageTracker


class FakeIntentTransport:
    """Return deterministic intent decisions without a network call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, str, dict[str, object]]] = []

    async def complete(
        self,
        model: str,
        system_prompt: str,
        user_message: str,
        schema_name: str,
        schema: dict[str, object],
    ) -> Completion:
        self.calls.append((model, system_prompt, user_message, schema_name, schema))
        request_text = json.loads(user_message.removeprefix(USER_MESSAGE_PREFIX))
        decision = {
            "reasoning": "The marker determines this offline test decision.",
            "authorizes_deletion": "NO_DELETE" not in request_text,
        }
        return Completion(text=json.dumps(decision), input_tokens=3, output_tokens=5)


@pytest.fixture
def intent_transports() -> list[FakeIntentTransport]:
    """Collect intent transports created during a test."""
    return []


@pytest.fixture(autouse=True)
def isolated_home(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path_factory.mktemp("home")
    xdg_dirs = {
        "XDG_CONFIG_HOME": home / ".config",
        "XDG_DATA_HOME": home / ".local/share",
        "XDG_CACHE_HOME": home / ".cache",
        "XDG_STATE_HOME": home / ".local/state",
    }
    for env_var in tuple(os.environ):
        if env_var.startswith("XDG_") and env_var not in xdg_dirs:
            monkeypatch.delenv(env_var)
    monkeypatch.setenv("HOME", str(home))
    for env_var, xdg_dir in xdg_dirs.items():
        monkeypatch.setenv(env_var, str(xdg_dir))


@pytest.fixture(autouse=True)
def fake_llm_connection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    intent_transports: list[FakeIntentTransport],
) -> None:
    def connect(usage: UsageTracker) -> StructuredLLM:
        transport = FakeIntentTransport()
        intent_transports.append(transport)
        return StructuredLLM(transport, usage, tmp_path / "llm-cache")

    monkeypatch.setattr(ghost_audit.llm, "connect", connect)
