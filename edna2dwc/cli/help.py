from __future__ import annotations

import io
import textwrap
from typing import TYPE_CHECKING, Any

from rich.console import Console
from rich.text import Text

if TYPE_CHECKING:
    from cyclopts.help import HelpEntry, HelpPanel
    from rich.console import ConsoleOptions

INDENT = "  "
GUTTER = "  "
WIDEST_NAME_COLUMN = 24


def as_plain_text(renderable: Any, console: Console) -> str:
    if renderable is None:
        return ""
    if isinstance(renderable, str):
        return renderable.rstrip()
    if isinstance(renderable, Text):
        return renderable.plain.rstrip()
    plain_console = Console(
        file=io.StringIO(),
        width=console.width,
        force_terminal=False,
        no_color=True,
        highlight=False,
        markup=False,
        emoji=False,
    )
    with plain_console.capture() as capture:
        plain_console.print(renderable, end="")
    return "\n".join(line.rstrip() for line in capture.get().splitlines()).strip("\n")


def _entry_names(entry: HelpEntry) -> str:
    return ", ".join(
        entry.positive_shorts + entry.positive_names + entry.negative_shorts + entry.negative_names
    )


def _entry_description(entry: HelpEntry, console: Console) -> str:
    parts = []
    description = " ".join(as_plain_text(entry.description, console).split())
    if description:
        parts.append(description)
    if entry.choices:
        parts.append(f"[choices: {', '.join(entry.choices)}]")
    if entry.env_var:
        parts.append(f"[env var: {', '.join(entry.env_var)}]")
    if entry.default is not None and entry.type is not bool:
        parts.append(f"[default: {entry.default}]")
    if entry.required:
        parts.append("[required]")
    return " ".join(parts)


class FlatFormatter:
    def render_usage(self, console: Console, options: ConsoleOptions, usage: Any) -> None:
        if usage:
            text = as_plain_text(usage, console)
            if not text.startswith("Usage:"):
                text = f"Usage: {text}"
            console.print(Text(text))

    def render_description(
        self, console: Console, options: ConsoleOptions, description: Any
    ) -> None:
        text = as_plain_text(description, console)
        if text:
            console.print()
            console.print(Text(text))

    def __call__(self, console: Console, options: ConsoleOptions, panel: HelpPanel) -> None:
        if not panel.entries:
            return
        console.print()
        console.print(Text(as_plain_text(panel.title, console) + ":", style="bold"))
        self._print_table(console, panel)

    def _print_table(self, console: Console, panel: HelpPanel) -> None:
        names = [_entry_names(entry) for entry in panel.entries]
        column = min(max(len(name) for name in names), WIDEST_NAME_COLUMN)
        description_indent = " " * (len(INDENT) + column + len(GUTTER))
        description_width = max(console.width - len(description_indent), 20)
        for name, entry in zip(names, panel.entries, strict=True):
            description = _entry_description(entry, console)
            lines = textwrap.wrap(description, width=description_width, break_on_hyphens=False)
            if not lines:
                console.print(Text(INDENT + name))
                continue
            if len(name) > column:
                console.print(Text(INDENT + name))
            else:
                first = lines.pop(0)
                console.print(Text(f"{INDENT}{name:<{column}}{GUTTER}{first}"))
            for line in lines:
                console.print(Text(description_indent + line))
