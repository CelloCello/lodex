from __future__ import annotations

from pathlib import Path

import pytest

from lodex_core.history.config import ConfigurationError, load_config


def test_history_defaults_to_lodex_home_without_creating_files(tmp_path: Path) -> None:
    home = tmp_path / "lodex"

    config = load_config({"LODEX_HOME": str(home)})

    assert config.data_dir == home / "history"
    assert config.db_path == home / "history/lodex.db"
    assert not home.exists()


def test_history_loads_configuration_from_lodex_home(tmp_path: Path) -> None:
    home = tmp_path / "lodex"
    history = home / "history"
    history.mkdir(parents=True)
    (history / "config.toml").write_text('[embedding]\nmodel = "home-model"\n')

    config = load_config({"LODEX_HOME": str(home)})

    assert config.ollama_model == "home-model"
    assert config.db_path == history / "lodex.db"


def test_explicit_configuration_preserves_home_based_data_default(tmp_path: Path) -> None:
    home = tmp_path / "lodex"
    config_path = tmp_path / "external.toml"
    config_path.write_text('[embedding]\nmodel = "external-model"\n')

    config = load_config({"LODEX_HOME": str(home), "LODEX_CONFIG": str(config_path)})

    assert config.ollama_model == "external-model"
    assert config.db_path == home / "history/lodex.db"


@pytest.mark.parametrize("override_database", [False, True])
def test_explicit_database_overrides_data_directory(
    tmp_path: Path, override_database: bool
) -> None:
    home = tmp_path / "lodex"
    history = home / "history"
    history.mkdir(parents=True)
    toml_database = tmp_path / "toml.db"
    environment_database = tmp_path / "environment.db"
    (history / "config.toml").write_text(f'[paths]\ndb_path = "{toml_database}"\n')
    environment = {"LODEX_HOME": str(home), "LODEX_DATA_DIR": str(tmp_path / "data")}
    if override_database:
        environment["LODEX_DB_PATH"] = str(environment_database)

    config = load_config(environment)

    assert config.data_dir == tmp_path / "data"
    assert config.db_path == (environment_database if override_database else toml_database)


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
