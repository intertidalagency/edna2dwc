from __future__ import annotations

import json
from pathlib import Path
import zipfile

import pytest


TERM_TABLE = {
    "occurrenceID": {"uri": "http://rs.tdwg.org/dwc/terms/occurrenceID"},
    "scientificName": {"uri": "http://rs.tdwg.org/dwc/terms/scientificName"},
    "basisOfRecord": {"uri": "http://rs.tdwg.org/dwc/terms/basisOfRecord"},
    "eventDate": {"uri": "http://rs.tdwg.org/dwc/terms/eventDate"},
}


def _build_archive(
    tmp_path: Path,
    name: str,
    rows: list[dict],
    *,
    dataset_id="ds",
    generated_at="2024-06-01T00:00:00Z",
) -> Path:
    core_path = tmp_path / f"{name}_occurrence.tsv"
    write_tsv(rows, core_path, columns=["occurrenceID", "scientificName", "basisOfRecord"])
    out_dir = tmp_path / name
        core_path=core_path,
        manifest=m,
        dataset_id=dataset_id,
        generated_at=generated_at,
        out_dir=out_dir,
    )


_BASE_ROWS = [
    {"occurrenceID": "ds_s1_f1", "scientificName": "A", "basisOfRecord": "MaterialSample"},
    {"occurrenceID": "ds_s1_f2", "scientificName": "B", "basisOfRecord": "MaterialSample"},
]


def test_compare_archives_reports_no_divergence_for_identical_content(tmp_path):
    old_zip = _build_archive(tmp_path, "old", _BASE_ROWS)
    new_zip = _build_archive(tmp_path, "new", _BASE_ROWS)


    assert result.diverged is False
    assert result.eml_differs is False





def test_compare_archives_detects_a_value_difference(tmp_path):
    old_zip = _build_archive(tmp_path, "old", _BASE_ROWS)
    changed_rows = [dict(r) for r in _BASE_ROWS]
    changed_rows[0]["scientificName"] = "Changed"
    new_zip = _build_archive(tmp_path, "new", changed_rows)


    assert result.diverged is True
    table_diff = result.tables[0]
    assert table_diff.value_diff_counts == {"scientificName": 1}
    assert table_diff.value_examples[0]["old"] == "A"
    assert table_diff.value_examples[0]["new"] == "Changed"






def test_compare_archives_detects_reordered_rows_with_the_same_id_set(tmp_path):
    old_zip = _build_archive(tmp_path, "old", _BASE_ROWS)
    new_zip = _build_archive(tmp_path, "new", list(reversed(_BASE_ROWS)))


    table_diff = result.tables[0]
    assert table_diff.row_order_matches is False
    assert table_diff.only_in_old == []
    assert table_diff.only_in_new == []
    assert result.diverged is True


def test_compare_archives_detects_a_removed_column(tmp_path):
    rows_with_date = [dict(r, eventDate="2021-06-01") for r in _BASE_ROWS]
    core_path = tmp_path / "old_occurrence.tsv"
    write_tsv(
        rows_with_date,
        core_path,
        columns=["occurrenceID", "scientificName", "basisOfRecord", "eventDate"],
    )
    old_out_dir = tmp_path / "old"
        core_path=core_path,
        extensions={},
        manifest=m,
        dataset_id="ds",
        generated_at="2024-06-01T00:00:00Z",
        term_table=TERM_TABLE,
        out_dir=old_out_dir,
    )

    core_path = tmp_path / "new_occurrence.tsv"
    write_tsv(_BASE_ROWS, core_path, columns=["occurrenceID", "scientificName", "basisOfRecord"])
    out_dir = tmp_path / "new"
        core_path=core_path,
        extensions={},
        manifest=m,
        dataset_id="ds",
        generated_at="2024-06-01T00:00:00Z",
        term_table=TERM_TABLE,
        out_dir=out_dir,
    )


    table_diff = result.tables[0]
    assert "eventDate" in table_diff.columns_removed


def test_render_summary_markdown_reports_clean_when_nothing_diverged():


def test_render_summary_markdown_reports_counts_before_examples(tmp_path):
    old_zip = _build_archive(tmp_path, "old", _BASE_ROWS)
    changed_rows = [dict(r) for r in _BASE_ROWS]
    changed_rows[0]["scientificName"] = "Changed"
    new_zip = _build_archive(tmp_path, "new", changed_rows)

    assert "Changed" in summary


def test_write_comparison_writes_both_markdown_and_json(tmp_path):
    out_path = tmp_path / "comparison_summary.md"


    assert out_path.exists()
    json_path = tmp_path / "comparison_summary.json"
    assert json.loads(json_path.read_text())["diverged"] is False


def test_extract_refuses_a_member_that_would_escape_the_destination(tmp_path):
    malicious_zip = tmp_path / "malicious.zip"
    with zipfile.ZipFile(malicious_zip, "w") as z:
        z.writestr("../../etc/evil.txt", "pwned")
    dest_dir = tmp_path / "extracted"

    assert not (tmp_path.parent.parent / "etc" / "evil.txt").exists()


def test_extract_allows_ordinary_nested_members(tmp_path):
    zip_path = tmp_path / "fine.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("occurrence.txt", "a\tb\n1\t2\n")
    dest_dir = tmp_path / "extracted"

    assert (result / "occurrence.txt").read_text() == "a\tb\n1\t2\n"
