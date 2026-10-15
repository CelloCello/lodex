"""Configuration loading with environment overrides for local Lodex commands."""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lodex_core.history.embedding import (
    DEFAULT_DIMENSION,
    DEFAULT_MODEL,
    DEFAULT_OLLAMA_HOST,
)


class ConfigurationError(ValueError):
    """A configuration file or environment override is invalid."""


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Resolved filesystem and embedding configuration."""

    codex_home: Path
    data_dir: Path
    db_path: Path
    ollama_host: str
    ollama_model: str
    embedding_dimension: int


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _string(value: object, *, key: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{key} must be a non-empty string")
    return value.strip()


def _positive_int(value: object, *, key: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ConfigurationError(f"{key} must be a positive integer")
    return value


def _expand_path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def load_config(environment: Mapping[str, str] | None = None) -> AppConfig:
    """Load optional TOML configuration, then apply environment overrides."""

    env = os.environ if environment is None else environment
    config_path = _expand_path(env.get("LODEX_CONFIG", "~/.config/lodex/config.toml"))
    raw: Mapping[str, Any] = {}
    if config_path.exists():
        try:
            with config_path.open("rb") as source:
                loaded = tomllib.load(source)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ConfigurationError(f"Cannot read {config_path}: {exc}") from exc
        raw = loaded

    paths = _mapping(raw.get("paths"))
    embedding = _mapping(raw.get("embedding"))

    codex_home_value = (
        env.get("CODEX_HOME")
        or _string(paths.get("codex_home"), key="paths.codex_home")
        or "~/.codex"
    )
    data_dir_value = (
        env.get("LODEX_DATA_DIR")
        or _string(paths.get("data_dir"), key="paths.data_dir")
        or "~/.local/share/lodex"
    )
    data_dir = _expand_path(data_dir_value)
    db_path_value = env.get("LODEX_DB_PATH") or _string(paths.get("db_path"), key="paths.db_path")
    dimension_value = env.get("LODEX_EMBEDDING_DIMENSION")
    if dimension_value is not None:
        try:
            dimension = int(dimension_value)
        except ValueError as exc:
            raise ConfigurationError("LODEX_EMBEDDING_DIMENSION must be an integer") from exc
        if dimension <= 0:
            raise ConfigurationError("LODEX_EMBEDDING_DIMENSION must be positive")
    else:
        dimension = (
            _positive_int(embedding.get("dimension"), key="embedding.dimension")
            or DEFAULT_DIMENSION
        )

    return AppConfig(
        codex_home=_expand_path(codex_home_value),
        data_dir=data_dir,
        db_path=_expand_path(db_path_value) if db_path_value else data_dir / "lodex.db",
        ollama_host=env.get("OLLAMA_HOST")
        or _string(embedding.get("host"), key="embedding.host")
        or DEFAULT_OLLAMA_HOST,
        ollama_model=env.get("LODEX_OLLAMA_MODEL")
        or _string(embedding.get("model"), key="embedding.model")
        or DEFAULT_MODEL,
        embedding_dimension=dimension,
    )
