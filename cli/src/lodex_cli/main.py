"""Unified Typer entry point; command handlers load their own runtime dependencies."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import Annotated

import typer

from lodex_cli import __version__
from lodex_cli import history as history_cli
from lodex_cli import management as management_cli
from lodex_cli.skill_install import SKILL_NAME, SKILL_NAMES
from lodex_cli.support import LodexGroup

app = typer.Typer(
    cls=LodexGroup,
    help=(
        "Lodex: a local toolkit for developers working with coding agents.\n\n"
        "Set up task checkouts, run project commands and services, and recover "
        "context from earlier agent sessions."
    ),
    rich_markup_mode=None,
    add_completion=False,
    pretty_exceptions_enable=False,
    pretty_exceptions_show_locals=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)


@app.callback(invoke_without_command=True)
def root(
    ctx: typer.Context,
    version: Annotated[bool, typer.Option("--version", is_eager=True)] = False,
) -> None:
    if version:
        print(f"lodex {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        print(ctx.get_help())


management_cli.register(app)
history_cli.register(app)


@app.command()
def console(port: Annotated[int, typer.Option(min=0, max=65535)] = 0) -> int:
    """Open the local task environment console (install lodex[console]).

    Inspect and operate environments shared with your CLI and coding agent.
    Ctrl-C stops this server; managed services keep running.
    """
    try:
        from lodex_console.app import serve
    except ImportError as exc:
        raise typer.BadParameter("Install lodex[console] or run uv sync --all-packages") from exc
    serve(port)
    return 0


skill_app = typer.Typer(
    help="Install, update or remove bundled agent skills.", no_args_is_help=False
)
app.add_typer(skill_app, name="skill")


def valid_skill(value: str) -> str:
    if value not in SKILL_NAMES:
        raise typer.BadParameter(f"Choose one of: {', '.join(SKILL_NAMES)}")
    return value


SkillName = Annotated[str, typer.Argument(callback=valid_skill, help=", ".join(SKILL_NAMES))]
DryRun = Annotated[
    bool, typer.Option("--dry-run", help="Preview without changing installed files.")
]


def skill_action(name: str, *, remove: bool, dry_run: bool) -> int:
    from lodex_cli.skill_install import install_skill, remove_skill

    action = remove_skill if remove else install_skill
    result = action(dry_run=dry_run, skill_name=name)
    labels = {
        "would-install": "Would install",
        "would-update": "Would update",
        "would-remove": "Would remove",
        "installed": "Installed",
        "updated": "Updated",
        "removed": "Removed",
        "unchanged": "already up to date",
        "not-installed": "not installed",
    }
    print(f"{labels[result.state]} {name}: {result.path}")
    return 0


@skill_app.command("install")
def skill_install(name: SkillName = SKILL_NAME, dry_run: DryRun = False) -> int:
    """Install or update a managed copy of a bundled skill."""
    return skill_action(name, remove=False, dry_run=dry_run)


@skill_app.command("remove")
def skill_remove(name: SkillName = SKILL_NAME, dry_run: DryRun = False) -> int:
    """Remove an installed skill without deleting project or history data."""
    return skill_action(name, remove=True, dry_run=dry_run)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    return int(app(args=arguments, prog_name="lodex", standalone_mode=False))


if __name__ == "__main__":
    raise SystemExit(main())
