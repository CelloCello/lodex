from __future__ import annotations

from pathlib import Path

import pytest

from lodex_core.history.config import ConfigurationError, load_config


def test_toml_configuration_with_environment_precedence(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[paths]
codex_home = "~/from-toml/codex"
data_dir = "~/from-toml/data"

[embedding]
host = "http://localhost:11434"
model = "toml-model"
dimension = 768
""".strip(),
        encoding="utf-8",
    )

    config = load_config(
        {
            "LODEX_CONFIG": str(config_path),
            "LODEX_DATA_DIR": str(tmp_path / "override-data"),
            "LODEX_OLLAMA_MODEL": "environment-model",
        }
    )

    assert config.codex_home == Path("~/from-toml/codex").expanduser().resolve()
    assert config.data_dir == (tmp_path / "override-data").resolve()
    assert config.db_path == config.data_dir / "lodex.db"
    assert config.ollama_host == "http://localhost:11434"
    assert config.ollama_model == "environment-model"
    assert config.embedding_dimension == 768


def test_invalid_configuration_is_actionable(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("[embedding]\ndimension = 0\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="positive integer"):
        load_config({"LODEX_CONFIG": str(config_path)})
