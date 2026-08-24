from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Mapping

import pytest


@pytest.mark.parametrize(
    ("host", "error_fragment"),
    [
        ("https://ollama.example.com", "Remote Ollama hosts are disabled"),
        ("http://127.0.0.1:bad", "port must be an integer"),
    ],
)
def test_status_json_reports_configuration_errors_without_traceback(
    host: str,
    error_fragment: str,
) -> None:
    environment: Mapping[str, str] = {**os.environ, "OLLAMA_HOST": host}

    result = subprocess.run(
        [sys.executable, "-m", "lodex.cli", "status", "--json"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 2
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["compatible"] is False
    assert error_fragment in payload["error"]
