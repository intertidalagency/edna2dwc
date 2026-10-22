from __future__ import annotations

from cyclopts import App

from edna2dwc.cli import app

ALWAYS_ACCEPTED = frozenset({"--help", "-h", "--version", "--quiet"})


def _walk(command: App, path: str) -> dict[str, set[str]]:
    found = {path: set()} if path else {}
    if command.default_command is not None and path:
        found[path] = {
            name for argument in command.assemble_argument_collection() for name in argument.names
        }
    for name in command:
        subcommand = command[name]
        if not hasattr(subcommand.default_command, "__self__"):
            found.update(_walk(subcommand, f"{path} {name}".strip()))
    return found


def flags_by_command() -> dict[str, set[str]]:
    return _walk(app, "")
