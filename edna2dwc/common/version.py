from __future__ import annotations

from importlib.metadata import PackageNotFoundError, distribution
from importlib.metadata import version as _pkg_version
import json
from pathlib import Path
import subprocess
from urllib.parse import urlparse
from urllib.request import url2pathname

DISTRIBUTION_NAME = "edna2dwc"
UNKNOWN_VERSION = "0+unknown"


def installed_version() -> str:
    try:
        return _pkg_version(DISTRIBUTION_NAME)
    except PackageNotFoundError:
        return UNKNOWN_VERSION


def installed_commit() -> str:
    try:
        direct_url = distribution(DISTRIBUTION_NAME).read_text("direct_url.json")
    except PackageNotFoundError:
        return ""
    return commit_from_direct_url(json.loads(direct_url)) if direct_url else ""


def commit_from_direct_url(direct_url: dict) -> str:
    if commit := direct_url.get("vcs_info", {}).get("commit_id"):
        return commit
    if direct_url.get("dir_info", {}).get("editable"):
        return _git_commit(Path(url2pathname(urlparse(direct_url["url"]).path)))
    return ""


def _git(source_dir: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(source_dir), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def _git_commit(source_dir: Path) -> str:
    try:
        head = _git(source_dir, "rev-parse", "HEAD")
        changes = _git(source_dir, "status", "--porcelain", "--untracked-files=no")
    except (OSError, subprocess.CalledProcessError):
        return ""
    return f"{head}-dirty" if changes else head
