import os
from pathlib import Path

import pytest

import ghost_audit.llm
from ghost_audit.llm import StructuredLLM
from ghost_audit.usage import UsageTracker
from tests.fakes import FakeTransport, decide_intent


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
) -> None:
    def connect(usage_tracker: UsageTracker) -> StructuredLLM:
        return StructuredLLM(FakeTransport(decide_intent), usage_tracker, tmp_path / "llm-cache")

    monkeypatch.setattr(ghost_audit.llm, "connect", connect)
