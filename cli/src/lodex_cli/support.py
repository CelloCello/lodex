"""Shared CLI options and the boundary for output and exit codes."""

from __future__ import annotations

import json
import sqlite3
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Any

import typer
from typer._click.core import Context

# Typer 0.26 vendors Click; catch parser errors from that same implementation.
from typer._click.exceptions import UsageError
from typer.core import TyperGroup

from lodex_core.management.common import ManagementError

Json = Annotated[bool, typer.Option("--json", help="Write one JSON result to stdout.")]


def default_target(value: str | None) -> str:
    if value is not None:
        return value
    try:
        return str(Path.cwd())
    except OSError as exc:
        raise ManagementError(
            "missing_cwd",
            "Current directory unavailable; pass --target ID or an absolute checkout path",
        ) from exc


Target = Annotated[
    str | None,
    typer.Option(callback=default_target, help="Taskenv ID or absolute checkout directory."),
]
Config = Annotated[Path | None, typer.Option(help="Source recipe for missing project.toml.")]
Yes = Annotated[bool, typer.Option("--yes", help="Confirm the requested destructive action.")]
MANAGEMENT_COMMANDS = frozenset(
    {
        "project",
        "worktree",
        "context",
        "service",
        "env",
        "secret",
        "port",
        "prepare",
        "run",
        "cleanup",
        "operation",
    }
)


class CommandError(Exception):
    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def wants_json(ctx: typer.Context, as_json: bool) -> bool:
    current: Context | None = ctx
    while current is not None:
        if current.params.get("as_json", False):
            return True
        current = current.parent
    return as_json


def management_result(ctx: typer.Context, result: Any, as_json: bool, *, ok: bool = True) -> int:
    print(
        json.dumps(
            {"ok": ok, "result": result},
            ensure_ascii=False,
            indent=None if wants_json(ctx, as_json) else 2,
        )
    )
    return 0 if ok else 1


def management_options(as_json: Json = False) -> None:
    """Options shared by commands in this group."""


def management_group(help: str) -> typer.Typer:
    return typer.Typer(callback=management_options, help=help, no_args_is_help=False)


class LodexGroup(TyperGroup):
    """Keep error/exit contracts identical in console entry points and CliRunner."""

    def main(
        self,
        args: Sequence[str] | None = None,
        prog_name: str | None = None,
        complete_var: str | None = None,
        standalone_mode: bool = True,
        windows_expand_args: bool = True,
        **extra: Any,
    ) -> Any:
        raw = list(sys.argv[1:] if args is None else args)
        try:
            result = super().main(
                args=raw.copy(),
                prog_name=prog_name,
                complete_var=complete_var,
                standalone_mode=False,
                windows_expand_args=windows_expand_args,
                **extra,
            )
            code = 0 if result is None else int(result)
        except (UsageError, ManagementError, CommandError, OSError, sqlite3.Error) as exc:
            code = self._error(raw, exc)
        except typer.Abort:
            print("Aborted!", file=sys.stderr)
            code = 1
        if standalone_mode:
            raise SystemExit(code)
        return code

    @staticmethod
    def _error(raw: list[str], exc: Exception) -> int:
        command = raw[0] if raw else "lodex"
        error_code = "usage" if isinstance(exc, UsageError) else "io_error"
        if isinstance(exc, ManagementError):
            error_code = exc.code
        code = (
            exc.exit_code if isinstance(exc, CommandError) else (2 if error_code == "usage" else 1)
        )
        message = exc.format_message() if isinstance(exc, UsageError) else str(exc)
        if command in MANAGEMENT_COMMANDS:
            if "--json" in raw:
                print(json.dumps({"ok": False, "error": {"code": error_code, "message": message}}))
            else:
                print(f"lodex: {error_code}: {message}", file=sys.stderr)
        elif command == "skill":
            print(f"lodex skill: {message}", file=sys.stderr)
        elif "--json" in raw:
            print(
                json.dumps(
                    {"command": command, "error": message, "ok": False},
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        else:
            print(f"lodex {command}: {message}", file=sys.stderr)
        return code
