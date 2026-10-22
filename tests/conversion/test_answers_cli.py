from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import subprocess

import pytest
import yaml

from edna2dwc.cli.common import CommandLineError
from edna2dwc.conversion import answers

INIT = ["init", "--dataset-id", "my-dataset", "--created", "2026-01-01T00:00:00Z"]


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def test_init_writes_answers_that_load_with_its_arguments(run_cli):
    result = run_cli(INIT)
    assert result.exit_code == 0, result.render()
    loaded = answers.load(Path("answers.yaml"))
    assert loaded.dataset_id == "my-dataset"
    assert loaded.created == "2026-01-01T00:00:00Z"
    assert loaded.out_dir == Path("archive")


def test_init_starts_an_empty_steps_log_and_copies_the_justfile(run_cli):
    run_cli(INIT)
    assert yaml.safe_load(Path("conversion.yaml").read_text()) == {"steps": []}
    assert "edna2dwc build" in Path("justfile").read_text()


def test_init_leaves_an_existing_justfile_and_steps_log_alone(run_cli):
    Path("justfile").write_text("mine:\n    true\n")
    Path("conversion.yaml").write_text("steps: [{n: 1}]\n")
    result = run_cli(INIT)
    assert Path("justfile").read_text() == "mine:\n    true\n"
    assert Path("conversion.yaml").read_text() == "steps: [{n: 1}]\n"
    assert result.outputs["written"] == ["answers.yaml"]


def test_init_refuses_to_overwrite_answers(run_cli):
    Path("answers.yaml").write_text("dataset_id: already-here\n")
    with pytest.raises(CommandLineError, match="answers.yaml"):
        run_cli(INIT)
    assert Path("answers.yaml").read_text() == "dataset_id: already-here\n"


def test_init_harvests_metadata_from_an_eml_file_with_eml_tags(run_cli, tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "eml.xml").write_text(
        "<eml><dataset><title>Kelp forest eDNA</title></dataset></eml>"
    )
    run_cli([*INIT, "--scan", "docs"])
    loaded = answers.load(Path("answers.yaml"))
    assert loaded.metadata.values["title"] == "Kelp forest eDNA"
    assert loaded.metadata.provenance["title"] == "eml.xml title"


def test_init_names_every_eml_file_when_it_finds_several(run_cli, tmp_path):
    for name in ("a", "b"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "eml.xml").write_text("<eml><dataset><title>T</title></dataset></eml>")
    result = run_cli([*INIT, "--scan", "."])
    assert "2 eml.xml files" in result.render()


def test_init_stamps_created_from_the_clock_when_it_is_omitted(run_cli):
    before = datetime.now(UTC).replace(microsecond=0)
    run_cli(["init", "--dataset-id", "my-dataset"])
    stamped = datetime.fromisoformat(answers.load(Path("answers.yaml")).created)
    assert before <= stamped <= datetime.now(UTC)


def test_init_refuses_a_created_that_is_not_a_datetime(run_cli):
    with pytest.raises(CommandLineError, match="banana"):
        run_cli(["init", "--dataset-id", "my-dataset", "--created", "banana"])
    assert not Path("answers.yaml").exists()


def test_init_refuses_a_dataset_id_that_cannot_key_an_occurrence(run_cli):
    with pytest.raises(CommandLineError, match="colon"):
        run_cli(["init", "--dataset-id", "my:survey"])
    assert not Path("answers.yaml").exists()


def test_the_justfile_has_every_recipe_the_report_promises(run_cli, tmp_path):
    run_cli(INIT)
    for target in ("build", "replay", "check", "compare", "validate", "evaluate"):
        dry_run = subprocess.run(
            ["just", "--dry-run", target],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )
        assert dry_run.returncode == 0, f"recipe {target!r}: {dry_run.stderr}"
