from __future__ import annotations

import json
from pathlib import Path

import pytest

from edna2dwc.common.tsv import write_tsv
from edna2dwc.dwca import writer
from tests import manifests

TERM_TABLE = {
    "occurrenceID": {"uri": "http://rs.tdwg.org/dwc/terms/occurrenceID"},
    "scientificName": {"uri": "http://rs.tdwg.org/dwc/terms/scientificName"},
    "basisOfRecord": {"uri": "http://rs.tdwg.org/dwc/terms/basisOfRecord"},
}


@pytest.fixture
def terms_table_path(tmp_path) -> Path:
    path = tmp_path / "dwc_terms.json"
    path.write_text(json.dumps(TERM_TABLE), encoding="utf-8")
    return path


@pytest.fixture
def archive_dir(tmp_path) -> Path:
    core_path = tmp_path / "occurrence.tsv"
    write_tsv(
        [{"occurrenceID": "ds1_s1_f1", "scientificName": "A", "basisOfRecord": "MaterialSample"}],
        core_path,
        columns=["occurrenceID", "scientificName", "basisOfRecord"],
    )
    m = manifests.required_manifest()
    out_dir = tmp_path / "archive"
    writer.write_archive(
        core_path=core_path,
        extensions={},
        manifest=m,
        dataset_id="ds",
        generated_at="2024-06-01T00:00:00Z",
        term_table=TERM_TABLE,
        out_dir=out_dir,
    )
    return out_dir


def test_validate_exits_zero_on_a_clean_archive(run_cli, archive_dir, terms_table_path):
    result = run_cli(
        ["validate", str(archive_dir), "--terms-table", str(terms_table_path), "--json"]
    )
    assert result.exit_code == 0, result.render()
    assert json.loads(result.render())["status"] == "ok"
    assert result.text == "Archive is valid."


@pytest.mark.parametrize(
    ("missing", "extra", "messages"),
    [
        ("eml.xml", [], ["eml.xml is missing"]),
        (
            "occurrence.txt",
            ["--obis"],
            [
                "occurrence.txt is declared in meta.xml but missing",
                "cannot run --obis: could not resolve the archive's core table from meta.xml",
            ],
        ),
    ],
)
def test_validate_exits_nonzero_on_an_archive_missing_a_file(
    run_cli, archive_dir, terms_table_path, missing, extra, messages
):
    (archive_dir / missing).unlink()
    result = run_cli(
        ["validate", str(archive_dir), "--terms-table", str(terms_table_path), *extra]
    )
    assert result.exit_code == 1
    assert [(f["code"], f["message"]) for f in result.findings] == [
        ("ARCHIVE_INVALID", message) for message in messages
    ]


def _rename_core_file(archive_dir: Path, new_name: str) -> None:
    (archive_dir / "occurrence.txt").rename(archive_dir / new_name)
    meta_path = archive_dir / "meta.xml"
    meta_path.write_text(
        meta_path.read_text(encoding="utf-8").replace(
            "<location>occurrence.txt</location>", f"<location>{new_name}</location>"
        ),
        encoding="utf-8",
    )


def test_validate_obis_runs_against_a_core_table_not_named_occurrence_txt(
    run_cli, archive_dir, terms_table_path
):
    _rename_core_file(archive_dir, "samples.txt")
    result = run_cli(
        ["validate", str(archive_dir), "--terms-table", str(terms_table_path), "--obis"]
    )
    assert result.exit_code == 0, result.render()
    assert [f["code"] for f in result.findings] == ["OBIS_VALIDATOR_ISSUE", "OBIS_VALIDATOR_ISSUE"]


def test_validate_gbif_without_credentials_warns_but_exits_zero(
    run_cli, archive_dir, terms_table_path
):
    result = run_cli(
        ["validate", str(archive_dir), "--terms-table", str(terms_table_path), "--gbif"]
    )
    assert result.exit_code == 0, result.render()
    assert [f["code"] for f in result.findings] == ["GBIF_CREDENTIALS_MISSING"]
