from __future__ import annotations

from pathlib import Path
import re

REPO_ROOT = Path(__file__).resolve().parent.parent

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


        return []


    for d in SCANNED_DIRS:
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


    failures = []
        failures.extend(check_path(rel, benchmark_names))
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        failures.extend(check_content(rel, text, benchmark_names))
    return failures




