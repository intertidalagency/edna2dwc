from __future__ import annotations

import json

import pytest

from edna2dwc.cli.common import CommandFailed, UsageError
from tests.archives import write_one_occurrence_archive


def test_replay_compare_of_identical_archives_succeeds_and_writes_its_summary(run_cli, tmp_path):
    old_zip = write_one_occurrence_archive(tmp_path / "old")
    new_zip = write_one_occurrence_archive(tmp_path / "new")
    summary = tmp_path / "out.md"

    result = run_cli(
        ["replay", "--compare", str(old_zip), str(new_zip), "-o", str(summary), "--json"]
    )

    assert result.exit_code == 0
    assert json.loads(result.render())["diverged"] is False
    assert summary.read_text(encoding="utf-8") == "# Archive comparison\n\nNo differences.\n"
    assert (
        json.loads(summary.with_suffix(".json").read_text(encoding="utf-8"))["diverged"] is False
    )


def test_replay_compare_fails_on_a_real_difference(run_cli, capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    old_zip = write_one_occurrence_archive(tmp_path / "old")
    new_zip = write_one_occurrence_archive(tmp_path / "new", scientific_name="B")

    with pytest.raises(CommandFailed) as error:
        run_cli(["replay", "--compare", str(old_zip), str(new_zip)])

    assert str(error.value) == "Archives diverge: see comparison_summary.md."
    assert "scientificName" in capsys.readouterr().out


def test_replay_compare_requires_exactly_two_archives(run_cli, tmp_path):
    zip_path = write_one_occurrence_archive(tmp_path / "only")
    with pytest.raises(UsageError) as error:
        run_cli(["replay", "--compare", str(zip_path)])
    assert str(error.value) == "--compare requires exactly two archives: OLD.zip NEW.zip"


def test_replay_check_and_compare_are_mutually_exclusive(run_cli, tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    with pytest.raises(UsageError) as error:
        run_cli(["replay", str(tmp_path / "a"), str(tmp_path / "b"), "--check", "--compare"])
    assert str(error.value) == "--compare and --check are mutually exclusive"
