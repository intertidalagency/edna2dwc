from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version
import os
from pathlib import Path
import subprocess

import pytest

from edna2dwc.common.version import DISTRIBUTION_NAME, commit_from_direct_url, installed_version


def test_installed_version_matches_the_distribution_metadata():
    assert installed_version() == pkg_version(DISTRIBUTION_NAME)


def test_installed_version_falls_back_when_the_distribution_is_not_installed(monkeypatch):
    monkeypatch.setattr("edna2dwc.common.version._pkg_version", _raise_not_found)
    assert installed_version() == "0+unknown"


def _raise_not_found(_name: str) -> str:
    raise PackageNotFoundError


@pytest.fixture(autouse=True)
def _no_inherited_git_environment(monkeypatch):
    for name in [name for name in os.environ if name.startswith("GIT_")]:
        monkeypatch.delenv(name)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path) -> Path:
    _git(tmp_path, "init", "-q")
    (tmp_path / "a.txt").write_text("a\n")
    _git(tmp_path, "add", "a.txt")
    _git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "a")
    return tmp_path


def test_a_git_url_install_reports_the_commit_it_recorded():
    direct_url = {"url": "https://github.com/x/y", "vcs_info": {"vcs": "git", "commit_id": "abc"}}
    assert commit_from_direct_url(direct_url) == "abc"


def test_an_editable_install_reports_its_source_trees_commit(repo):
    direct_url = {"url": repo.as_uri(), "dir_info": {"editable": True}}
    assert commit_from_direct_url(direct_url) == _git(repo, "rev-parse", "HEAD")


def test_an_editable_install_with_uncommitted_changes_says_so(repo):
    (repo / "a.txt").write_text("changed\n")
    direct_url = {"url": repo.as_uri(), "dir_info": {"editable": True}}
    assert commit_from_direct_url(direct_url) == _git(repo, "rev-parse", "HEAD") + "-dirty"


def test_an_untracked_file_does_not_make_the_tree_dirty(repo):
    (repo / "scratch.txt").write_text("notes\n")
    direct_url = {"url": repo.as_uri(), "dir_info": {"editable": True}}
    assert not commit_from_direct_url(direct_url).endswith("-dirty")


def test_an_install_from_a_plain_directory_reports_no_commit(repo):
    assert commit_from_direct_url({"url": repo.as_uri(), "dir_info": {}}) == ""


def test_an_editable_install_outside_git_reports_no_commit(tmp_path):
    direct_url = {"url": tmp_path.as_uri(), "dir_info": {"editable": True}}
    assert commit_from_direct_url(direct_url) == ""
