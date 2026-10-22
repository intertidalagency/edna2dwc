from __future__ import annotations

from typing import Any

from cyclopts import Group

VERBS = Group("What you do", sort_key=10)
SETUP = Group("Set up", sort_key=20)
INGEST = Group("Read inputs into one table", sort_key=30)
REVIEW = Group("Review and reproduce a conversion", sort_key=50)
PACKAGE = Group("Assemble an archive from tables already in Darwin Core terms", sort_key=55)
MAINTENANCE = Group("Maintenance", sort_key=70)
OPTIONS = Group("Options", sort_key=80)
COMMANDS = Group("Commands")

PIPELINE: dict[Group, tuple[str, ...]] = {
    VERBS: ("inspect", "resolve-taxonomy", "build", "evaluate"),
    SETUP: ("doctor", "credentials", "init"),
    INGEST: ("text", "detect-redundant", "record-step", "assemble", "validate-intermediate"),
    REVIEW: ("validate", "audit", "findings", "replay"),
    PACKAGE: ("package",),
    MAINTENANCE: ("terms",),
}

_SUBCOMMAND_ONLY: dict[str, Any] = {
    "help_prologue": "",
    "help_epilogue": "",
    "help_format": "markdown",
    "group_commands": COMMANDS,
}

_PLACEMENTS = {
    command: {"name": command, "group": group, "sort_key": position, **_SUBCOMMAND_ONLY}
    for group, commands in PIPELINE.items()
    for position, command in enumerate(commands)
}


def stage(command: str) -> dict[str, Any]:
    return _PLACEMENTS[command]
