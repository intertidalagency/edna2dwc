from __future__ import annotations

from pathlib import Path
import re

from tests.cli_commands import ALWAYS_ACCEPTED, flags_by_command

REPO_ROOT = Path(__file__).resolve().parent.parent
PROSE = [
    REPO_ROOT / "README.md",
    *sorted((REPO_ROOT / "skills").rglob("*.md")),
    *sorted((REPO_ROOT / "docs").rglob("*.md")),
]
SOURCE = sorted((REPO_ROOT / "edna2dwc").rglob("*.py"))
CODE_SPAN = re.compile(r"`edna2dwc ([^`\n]+)`")
CODE_BLOCK = re.compile(r"```[a-z]*\n(.*?)```", flags=re.DOTALL)
COMMAND_LINE = re.compile(r"^\s*(?:[!$]\s*)?edna2dwc (.+)$", flags=re.MULTILINE)
BARE_COMMAND_SPAN = re.compile(r"`([a-z][a-z0-9]*(?:-[a-z0-9]+)+(?: --[a-z][^`\n]*)?)`")


def _mentions(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    found = CODE_SPAN.findall(text)
    if path.suffix == ".py":
        found += BARE_COMMAND_SPAN.findall(text)
    if path.suffix == ".md":
        for block in CODE_BLOCK.findall(text):
            found += COMMAND_LINE.findall(block)
    return found


def _problem(mention: str, commands: dict[str, set[str]]) -> str | None:
    words = mention.split()
    if not words or not re.fullmatch(r"[a-z][a-z0-9-]*", words[0]):
        return None
    two_words = " ".join(words[:2])
    command = two_words if two_words in commands else words[0]
    if command not in commands:
        return f"no command {command!r}"
    accepted = commands[command] | ALWAYS_ACCEPTED
    unknown = [
        word.split("=")[0]
        for word in words
        if word.startswith("--") and word.split("=")[0] not in accepted
    ]
    return f"{command} has no {', '.join(unknown)}" if unknown else None


FLAG = re.compile(r"(?<![\w-])--[a-z][a-z0-9]*(?:-[a-z0-9]+)*")
NAMES_WHAT_IT_REPLACED = {
    REPO_ROOT / "docs" / "dev" / name for name in ("vocabulary.md", "decisions.md")
}
OTHER_TOOLS_FLAGS = {
    "--force-reinstall",
    "--python",
    "--with",
    "--porcelain",
    "--untracked-files",
    "--persona",
    "--gh-token",
}
REMOVED_FILES = re.compile(r"decisions\.yaml|manifest\.json|reviewed/|proposals/")


def test_every_flag_the_skill_docs_and_messages_name_exists():
    known = set().union(*flags_by_command().values()) | ALWAYS_ACCEPTED | OTHER_TOOLS_FLAGS
    problems = [
        f"{path.relative_to(REPO_ROOT)}: {flag}"
        for path in [*PROSE, *SOURCE]
        if path not in NAMES_WHAT_IT_REPLACED
        for flag in FLAG.findall(path.read_text(encoding="utf-8"))
        if flag not in known
    ]
    assert problems == []


def test_no_file_the_tool_stopped_writing_is_named_outside_the_vocabulary():
    problems = [
        f"{path.relative_to(REPO_ROOT)}: {name}"
        for path in [*PROSE, *SOURCE]
        if path not in NAMES_WHAT_IT_REPLACED
        for name in REMOVED_FILES.findall(path.read_text(encoding="utf-8"))
    ]
    assert problems == []


def test_every_command_and_flag_the_skill_docs_and_messages_name_exists():
    commands = flags_by_command()
    problems = [
        f"{path.relative_to(REPO_ROOT)}: `edna2dwc {mention}`: {problem}"
        for path in [*PROSE, *SOURCE]
        for mention in _mentions(path)
        if (problem := _problem(mention, commands))
    ]
    assert problems == []
