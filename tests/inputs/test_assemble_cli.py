from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from edna2dwc.cli.common import CommandLineError


@pytest.fixture(autouse=True)
def conversion_dir(tmp_path, monkeypatch) -> Path:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "conversion.yaml").write_text(yaml.safe_dump({"steps": []}), encoding="utf-8")
    (tmp_path / "tables").mkdir()
    (tmp_path / "tables" / "counts.csv").write_text(
        "featureID,S1,S2\nasv1,5,0\nasv2,1,3\n", encoding="utf-8"
    )
    (tmp_path / "tables" / "taxonomy.csv").write_text(
        "featureID,taxonomy\nasv1,Animalia;Chordata\nasv2,Bacteria\n", encoding="utf-8"
    )
    return tmp_path


def _assemble(run_cli, *extra: str):
    return run_cli(
        [
            "assemble",
            "--counts",
            "tables/counts.csv",
            "--features",
            "tables/taxonomy.csv",
            *extra,
        ]
    )


def test_assemble_writes_the_intermediate_table_and_checks_it(run_cli, conversion_dir):
    result = _assemble(run_cli)
    assert result.exit_code == 0, result.render()
    assert (
        (conversion_dir / "occurrence_long.tsv")
        .read_text()
        .startswith("sampleID\tfeatureID\tcount\ttaxonomy\n")
    )
    assert "3 row(s)" in result.text
    assert "satisfies the intermediate table's schema" in result.text


def test_assemble_records_itself_once_after_the_reader_scripts(run_cli, conversion_dir):
    config = conversion_dir / "conversion.yaml"
    config.write_text(
        yaml.safe_dump(
            {"steps": [{"n": 1, "command": "python scripts/read.py", "script": "scripts/read.py"}]}
        ),
        encoding="utf-8",
    )
    _assemble(run_cli)
    _assemble(run_cli)

    raw = yaml.safe_load(config.read_text())
    assert [step["command"] for step in raw["steps"]] == [
        "python scripts/read.py",
        "edna2dwc assemble --counts tables/counts.csv --features tables/taxonomy.csv",
    ]


def test_assemble_lists_none_of_the_tables_a_reader_script_wrote_as_raw_inputs(
    run_cli, conversion_dir
):
    _assemble(run_cli)
    raw = yaml.safe_load((conversion_dir / "conversion.yaml").read_text())
    assert not raw.get("raw_inputs")


def test_assemble_keeps_its_findings_for_the_report(run_cli, conversion_dir):
    _assemble(run_cli)
    record = json.loads((conversion_dir / "assembly.json").read_text())
    assert {f["code"] for f in record["findings"]} >= {"INPUT_TOTALS", "PRESENCE_ONLY_FILTERED"}


def test_assemble_refuses_a_table_it_cannot_read_as_counts(run_cli, conversion_dir):
    (conversion_dir / "tables" / "counts.csv").write_text("asv,S1\nasv1,5\n", encoding="utf-8")
    with pytest.raises(CommandLineError) as error:
        _assemble(run_cli)
    assert "featureID" in str(error.value)


def test_assemble_needs_a_conversion_directory(run_cli, conversion_dir):
    (conversion_dir / "conversion.yaml").unlink()
    with pytest.raises(CommandLineError) as error:
        _assemble(run_cli)
    assert "init" in str(error.value)


@pytest.mark.parametrize("outside", ["counts.csv", "tables/../counts.csv", "{root}/counts.csv"])
def test_assemble_refuses_a_table_outside_tables(run_cli, conversion_dir, outside):
    (conversion_dir / "counts.csv").write_text("featureID,S1\nasv1,5\n", encoding="utf-8")
    path = outside.format(root=conversion_dir.as_posix())
    with pytest.raises(CommandLineError) as error:
        run_cli(["assemble", "--counts", path, "--features", "tables/taxonomy.csv"])
    message = str(error.value)
    assert path in message
    assert "tables/" in message
    assert "record-step" in message
    assert not (conversion_dir / "occurrence_long.tsv").exists()


def test_assemble_refuses_a_link_in_tables_to_a_file_outside_it(run_cli, conversion_dir):
    source = conversion_dir / "counts.csv"
    source.write_text("featureID,S1\nasv1,5\n", encoding="utf-8")
    link = conversion_dir / "tables" / "linked.csv"
    try:
        link.symlink_to(source)
    except OSError:
        pytest.skip("this platform can't create symlinks")
    with pytest.raises(CommandLineError) as error:
        run_cli(["assemble", "--counts", "tables/linked.csv"])
    assert "tables/linked.csv" in str(error.value)


def test_assemble_reads_a_table_in_a_folder_under_tables(run_cli, conversion_dir):
    nested = conversion_dir / "tables" / "16S"
    nested.mkdir()
    (conversion_dir / "tables" / "counts.csv").rename(nested / "counts.csv")
    result = run_cli(
        ["assemble", "--counts", "tables/16S/counts.csv", "--features", "tables/taxonomy.csv"]
    )
    assert result.exit_code == 0, result.render()
