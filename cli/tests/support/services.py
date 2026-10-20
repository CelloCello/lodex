from __future__ import annotations

import json
import sys
from pathlib import Path

from lodex_core.management.project_config import CONFIG


def service_config(repo: Path) -> None:
    (repo / CONFIG).write_text(
        "schema_version=1\n[ports]\nPORT=0\n[services.http]\n"
        f'argv=[{json.dumps(sys.executable)},"-u","-m","http.server","${{PORT}}","--bind","127.0.0.1"]\n'
        'ready_port="PORT"\nurl="http://127.0.0.1:${PORT}"\nready_timeout=2\n'
        "[services.worker]\n"
        f'argv=[{json.dumps(sys.executable)},"-u","-c","import time; print(123); time.sleep(60)"]\n'
        "[services.bad]\n"
        f'argv=[{json.dumps(sys.executable)},"-c","raise SystemExit(4)"]\n'
    )
