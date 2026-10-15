"""Build frontend assets in the workspace; preserve them in standalone sdists."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        if version == "editable":
            return
        root = Path(self.root)
        frontend = root.parent / "f2e"
        if (frontend / "package.json").is_file():
            if not (frontend / "node_modules").is_dir():
                raise RuntimeError(
                    "Run pnpm --dir console/f2e install --frozen-lockfile before building Lodex"
                )
            subprocess.run(["pnpm", "--dir", str(frontend), "run", "build"], check=True)
        assets = root / "src/lodex_console/static"
        if not (assets / "index.html").is_file() or not list((assets / "assets").glob("*.js")):
            raise RuntimeError("Console distribution is missing compiled frontend assets")
