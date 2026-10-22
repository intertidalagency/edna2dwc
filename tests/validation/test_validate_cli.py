from __future__ import annotations

import json
from pathlib import Path

import pytest


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
    out_dir = tmp_path / "archive"
        core_path=core_path,
        extensions={},
        manifest=m,
        dataset_id="ds",
        generated_at="2024-06-01T00:00:00Z",
        term_table=TERM_TABLE,
        out_dir=out_dir,
    )
    return out_dir


    )


):
    )
    assert result.exit_code == 1


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
):
    _rename_core_file(archive_dir, "samples.txt")
    )


def test_validate_gbif_without_credentials_warns_but_exits_zero(
):
    )
