from __future__ import annotations

from pathlib import Path
from typing import Any

from lodex_core.management import worktrees
from lodex_core.management.store import Registry


def register(registry: Registry, repo: Path) -> dict[str, Any]:
    worktrees.project_add(registry, "fixture", repo, None)
    return worktrees.attach(registry, "fixture", repo)
