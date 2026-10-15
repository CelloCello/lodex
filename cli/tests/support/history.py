from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from lodex_core.history import queries

from . import FIXTURES
from .fakes import FakeEmbedder


def configure_cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[FakeEmbedder, Path]:
    codex_home = tmp_path / "codex"
    sessions = codex_home / "sessions"
    sessions.mkdir(parents=True)
    shutil.copy2(FIXTURES / "completed.jsonl", sessions / "completed.jsonl")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setenv("LODEX_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("LODEX_EMBEDDING_DIMENSION", "3")
    monkeypatch.setenv("LODEX_OLLAMA_MODEL", "test-model")
    fake = FakeEmbedder(
        dimension=3,
        provider="ollama",
        model="test-model",
        digest="sha256:test",
    )
    monkeypatch.setattr(queries, "OllamaEmbedder", lambda **_: fake)
    return fake, sessions
