from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def conversion_dir(tmp_path, monkeypatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _stage_and_next(result) -> str:
    return "\n".join(result.render().splitlines()[-2:])


def test_doctor_points_to_inspect(run_cli):
    assert _stage_and_next(run_cli(["doctor"])).startswith(
        "Stage 1 of 5: Inspect\nNext: `edna2dwc inspect"
    )


def test_inspect_points_to_init(run_cli, conversion_dir):
    (conversion_dir / "counts.csv").write_text("featureID,S1\nasv1,3\n", encoding="utf-8")
    assert _stage_and_next(run_cli(["inspect", "counts.csv"])).startswith(
        "Stage 1 of 5: Inspect\nNext: `edna2dwc init"
    )


def test_init_points_to_the_answers_and_says_the_reader_script_starts_read(run_cli):
    stage_and_next = _stage_and_next(run_cli(["init", "--dataset-id", "kelp-2024"]))
    assert stage_and_next.startswith("Stage 2 of 5: Describe\nNext: answer")
    assert "Stage 3, Read: write the reader script" in stage_and_next


def test_assemble_points_to_resolve_taxonomy(run_cli, conversion_dir):
    run_cli(["init", "--dataset-id", "kelp-2024"])
    (conversion_dir / "tables").mkdir()
    (conversion_dir / "tables" / "counts.csv").write_text(
        "featureID,S1\nasv1,3\n", encoding="utf-8"
    )
    (conversion_dir / "tables" / "taxonomy.csv").write_text(
        "featureID,taxonomy\nasv1,Animalia\n", encoding="utf-8"
    )
    result = run_cli(
        ["assemble", "--counts", "tables/counts.csv", "--features", "tables/taxonomy.csv"]
    )
    assert _stage_and_next(result) == "Stage 3 of 5: Read\nNext: `edna2dwc resolve-taxonomy`"
