from __future__ import annotations

import os
from pathlib import Path
import re

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCANNED_DIRS = ("edna2dwc", "skills")

PATH_PATTERNS = (
    re.compile(r"(^|/)dwca-", re.IGNORECASE),
    re.compile(r"ground.?truth", re.IGNORECASE),
    re.compile(r"(^|/)after/", re.IGNORECASE),
    re.compile(r"(^|/)examples?/", re.IGNORECASE),
)

_PATH_URL_TOKEN = re.compile(
    r"https?://[^\s\"'<>]+"
    r"|[A-Za-z]:\\[\w.\-\\]+"
    r"|~[\\/][\w.\-\\/]+"
    r"|\.{1,2}/[\w.\-/]+"
    r"|/[\w.\-/]+"
    r"|[\w.\-]+(?:/[\w.\-]+)+"
    r"|[\w.\-]+(?:\\[\w.\-]+)+"
)
FORBIDDEN_HOST_FRAGMENTS = ("downloads",)


def reference_archive_names() -> list[str]:
    names_file = os.environ.get("EDNA2DWC_REFERENCE_ARCHIVES")
    if not names_file:
        return []
    return [str(name) for name in yaml.safe_load(Path(names_file).read_text())["archives"]]


def iter_scanned_files(root: Path):
    for d in SCANNED_DIRS:
        base = root / d
        if base.exists():
            yield from (p for p in base.rglob("*") if p.is_file())


def check_path(rel_path: str, benchmark_names: list[str]) -> list[str]:
    failures = []
    for pattern in PATH_PATTERNS:
        if pattern.search(rel_path):
            failures.append(
                f"{rel_path}: path matches forbidden pattern {pattern.pattern!r} (rule a)"
            )
    lowered = rel_path.lower()
    for name in benchmark_names:
        if name.lower() in lowered:
            failures.append(f"{rel_path}: path names benchmark archive {name!r} (rule a)")
    return failures


def check_content(rel_path: str, text: str, benchmark_names: list[str]) -> list[str]:
    failures = []
    for token in _PATH_URL_TOKEN.findall(text):
        lowered = token.lower()
        if any(fragment in lowered for fragment in FORBIDDEN_HOST_FRAGMENTS):
            failures.append(f"{rel_path}: content contains forbidden path/URL {token!r} (rule b)")
            continue
        if any(name.lower() in lowered for name in benchmark_names):
            failures.append(
                f"{rel_path}: content contains a path/URL naming a benchmark archive {token!r} (rule b)"
            )

    if rel_path.startswith("skills/"):
        lowered_text = text.lower()
        for name in benchmark_names:
            if name.lower() in lowered_text:
                failures.append(
                    f"{rel_path}: agent-facing file names benchmark project {name!r} (rule c)"
                )
    return failures


def check_tree(root: Path = REPO_ROOT) -> list[str]:
    benchmark_names = reference_archive_names()
    failures = []
    for path in iter_scanned_files(root):
        rel = path.relative_to(root).as_posix()
        failures.extend(check_path(rel, benchmark_names))
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        failures.extend(check_content(rel, text, benchmark_names))
    return failures


def test_the_checked_out_tree_has_no_ground_truth_leak():
    assert check_tree() == []


@pytest.mark.parametrize(
    ("rel_path", "text", "names"),
    [
        ("edna2dwc/data/dwca-reference.zip", "", []),
        ("edna2dwc/data/Reference_Survey.tsv", "", ["reference_survey"]),
        ("edna2dwc/hints.py", "see ../downloads/after/occurrence.txt", []),
        (
            "edna2dwc/hints.py",
            "https://example.org/Reference_Survey/dwca.zip",
            ["Reference_Survey"],
        ),
        (
            "skills/convert-edna-to-dwc/SKILL.md",
            "compare with the reference survey",
            ["Reference Survey"],
        ),
    ],
)
def test_each_rule_flags_a_leak(rel_path, text, names):
    assert check_path(rel_path, names) + check_content(rel_path, text, names) != []


def test_check_tree_flags_a_leak_planted_under_skills(tmp_path, monkeypatch):
    names_file = tmp_path / "names.yaml"
    names_file.write_text("archives: [Reference Survey]\n", encoding="utf-8")
    monkeypatch.setenv("EDNA2DWC_REFERENCE_ARCHIVES", str(names_file))
    planted = tmp_path / "skills" / "notes.md"
    planted.parent.mkdir()
    planted.write_text("Copy the reference survey.\n", encoding="utf-8")

    assert check_tree(tmp_path) == [
        "skills/notes.md: agent-facing file names benchmark project 'Reference Survey' (rule c)"
    ]
