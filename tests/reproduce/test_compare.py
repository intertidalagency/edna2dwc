from __future__ import annotations

import json
from pathlib import Path
import zipfile

import pytest

from edna2dwc.common.tsv import write_tsv
from edna2dwc.conversion import artifacts
from edna2dwc.dwca import writer
from edna2dwc.reproduce import compare
from tests import manifests

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
    extensions: dict | None = None,
    term_table: dict | None = None,
) -> Path:
    core_path = tmp_path / f"{name}_occurrence.tsv"
    write_tsv(rows, core_path, columns=["occurrenceID", "scientificName", "basisOfRecord"])
    m = manifests.required_manifest()
    out_dir = tmp_path / name
    writer.write_archive(
        core_path=core_path,
        extensions=extensions or {},
        manifest=m,
        dataset_id=dataset_id,
        generated_at=generated_at,
        term_table=term_table or TERM_TABLE,
        out_dir=out_dir,
    )
    return out_dir / artifacts.ZIP_NAME


_BASE_ROWS = [
    {"occurrenceID": "ds_s1_f1", "scientificName": "A", "basisOfRecord": "MaterialSample"},
    {"occurrenceID": "ds_s1_f2", "scientificName": "B", "basisOfRecord": "MaterialSample"},
]


def test_compare_archives_reports_no_divergence_for_identical_content(tmp_path):
    old_zip = _build_archive(tmp_path, "old", _BASE_ROWS)
    new_zip = _build_archive(tmp_path, "new", _BASE_ROWS)

    result = compare.compare_archives(old_zip, new_zip)

    assert result.diverged is False
    assert result.eml_differs is False


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ({"dataset_id": "ds-old"}, {"dataset_id": "ds-new"}),
        ({"generated_at": "2024-01-01T00:00:00Z"}, {"generated_at": "2024-12-31T23:59:59Z"}),
    ],
    ids=["packageId", "dateStamp"],
)
def test_compare_archives_reports_an_eml_that_differs_only_in_answers_yaml_values(
    tmp_path, old, new
):
    old_zip = _build_archive(tmp_path, "old", _BASE_ROWS, **old)
    new_zip = _build_archive(tmp_path, "new", _BASE_ROWS, **new)

    assert compare.compare_archives(old_zip, new_zip).eml_differs is True


def test_compare_archives_detects_a_value_difference(tmp_path):
    old_zip = _build_archive(tmp_path, "old", _BASE_ROWS)
    changed_rows = [dict(r) for r in _BASE_ROWS]
    changed_rows[0]["scientificName"] = "Changed"
    new_zip = _build_archive(tmp_path, "new", changed_rows)

    result = compare.compare_archives(old_zip, new_zip)

    assert result.diverged is True
    table_diff = result.tables[0]
    assert table_diff.value_diff_counts == {"scientificName": 1}
    assert table_diff.value_examples[0]["old"] == "A"
    assert table_diff.value_examples[0]["new"] == "Changed"


def test_compare_archives_reports_a_row_present_on_one_side_under_that_side(tmp_path):
    full_zip = _build_archive(tmp_path, "full", _BASE_ROWS)
    short_zip = _build_archive(tmp_path, "short", _BASE_ROWS[:1])

    gained = compare.compare_archives(short_zip, full_zip).tables[0]
    assert (gained.only_in_new, gained.only_in_old) == (["ds_s1_f2"], [])

    lost = compare.compare_archives(full_zip, short_zip).tables[0]
    assert (lost.only_in_old, lost.only_in_new) == (["ds_s1_f2"], [])


def test_compare_archives_names_the_first_rows_on_one_side_and_counts_the_rest(tmp_path):
    rows = [
        {
            "occurrenceID": f"ds_s1_f{n:02}",
            "scientificName": "A",
            "basisOfRecord": "MaterialSample",
        }
        for n in range(compare.LISTED + 5)
    ]
    short_zip = _build_archive(tmp_path, "short", rows[:1])
    full_zip = _build_archive(tmp_path, "full", rows)

    gained = compare.compare_archives(short_zip, full_zip).tables[0]

    assert gained.rows_only_in_new == compare.LISTED + 4
    assert gained.only_in_new == [row["occurrenceID"] for row in rows[1 : compare.LISTED + 1]]


def test_compare_archives_detects_an_extension_table_added_on_one_side(tmp_path):
    old_zip = _build_archive(tmp_path, "old", _BASE_ROWS)
    dna_path = tmp_path / "dna.tsv"
    write_tsv(
        [{"occurrenceID": "ds_s1_f1", "DNA_sequence": "ACGT", "target_gene": "18S"}],
        dna_path,
        columns=["occurrenceID", "DNA_sequence", "target_gene"],
    )
    extended_terms = {
        **TERM_TABLE,
        "DNA_sequence": {"uri": "http://gensc.org/ns/mixs/DNA_sequence"},
        "target_gene": {"uri": "http://gensc.org/ns/mixs/target_gene"},
    }
    new_zip = _build_archive(
        tmp_path,
        "new",
        _BASE_ROWS,
        extensions={"dnaderiveddata": dna_path},
        term_table=extended_terms,
    )

    result = compare.compare_archives(old_zip, new_zip)

    assert result.diverged
    assert result.tables_added == ["dnaderiveddata.txt"]
    assert result.tables_removed == []
    assert "dnaderiveddata.txt" in compare.render_summary_markdown(result)

    reversed_result = compare.compare_archives(new_zip, old_zip)
    assert reversed_result.diverged
    assert reversed_result.tables_removed == ["dnaderiveddata.txt"]


def test_compare_archives_detects_reordered_rows_with_the_same_id_set(tmp_path):
    old_zip = _build_archive(tmp_path, "old", _BASE_ROWS)
    new_zip = _build_archive(tmp_path, "new", list(reversed(_BASE_ROWS)))

    result = compare.compare_archives(old_zip, new_zip)

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
    m = manifests.required_manifest()
    old_out_dir = tmp_path / "old"
    writer.write_archive(
        core_path=core_path,
        extensions={},
        manifest=m,
        dataset_id="ds",
        generated_at="2024-06-01T00:00:00Z",
        term_table=TERM_TABLE,
        out_dir=old_out_dir,
    )
    old_zip = old_out_dir / artifacts.ZIP_NAME

    core_path = tmp_path / "new_occurrence.tsv"
    write_tsv(_BASE_ROWS, core_path, columns=["occurrenceID", "scientificName", "basisOfRecord"])
    m = manifests.required_manifest()
    out_dir = tmp_path / "new"
    writer.write_archive(
        core_path=core_path,
        extensions={},
        manifest=m,
        dataset_id="ds",
        generated_at="2024-06-01T00:00:00Z",
        term_table=TERM_TABLE,
        out_dir=out_dir,
    )
    new_zip = out_dir / artifacts.ZIP_NAME

    result = compare.compare_archives(old_zip, new_zip)

    table_diff = result.tables[0]
    assert "eventDate" in table_diff.columns_removed


def test_compare_archives_reports_a_table_meta_xml_does_not_declare(tmp_path):
    old_zip = _build_archive(tmp_path, "old", _BASE_ROWS)
    new_zip = _build_archive(tmp_path, "new", _BASE_ROWS)
    with zipfile.ZipFile(old_zip, "a") as stale:
        stale.writestr("extendedmeasurementorfact.txt", "occurrenceID\n")

    result = compare.compare_archives(old_zip, new_zip)

    assert result.diverged
    assert result.undeclared_in_old == ["extendedmeasurementorfact.txt"]
    assert "extendedmeasurementorfact.txt" in compare.render_summary_markdown(result)


def test_render_summary_markdown_reports_clean_when_nothing_diverged():
    result = compare.ComparisonResult()
    assert "No differences" in compare.render_summary_markdown(result)


def test_render_summary_markdown_reports_counts_before_examples(tmp_path):
    old_zip = _build_archive(tmp_path, "old", _BASE_ROWS)
    changed_rows = [dict(r) for r in _BASE_ROWS]
    changed_rows[0]["scientificName"] = "Changed"
    new_zip = _build_archive(tmp_path, "new", changed_rows)
    result = compare.compare_archives(old_zip, new_zip)

    assert result.tables[0].value_diff_counts == {"scientificName": 1}
    summary = compare.render_summary_markdown(result)
    assert "`scientificName`" in summary
    assert "Changed" in summary


def test_write_comparison_writes_both_markdown_and_json(tmp_path):
    result = compare.ComparisonResult()
    out_path = tmp_path / "comparison_summary.md"

    compare.write_comparison(result, out_path)

    assert out_path.exists()
    json_path = tmp_path / "comparison_summary.json"
    assert json.loads(json_path.read_text())["diverged"] is False


def test_extract_refuses_a_member_that_would_escape_the_destination(tmp_path):
    malicious_zip = tmp_path / "malicious.zip"
    with zipfile.ZipFile(malicious_zip, "w") as z:
        z.writestr("../../etc/evil.txt", "pwned")
    dest_dir = tmp_path / "extracted"

    with pytest.raises(ValueError):
        compare._extract(malicious_zip, dest_dir)
    assert not (tmp_path.parent.parent / "etc" / "evil.txt").exists()


def test_extract_allows_ordinary_nested_members(tmp_path):
    zip_path = tmp_path / "fine.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("occurrence.txt", "a\tb\n1\t2\n")
    dest_dir = tmp_path / "extracted"

    result = compare._extract(zip_path, dest_dir)
    assert (result / "occurrence.txt").read_text() == "a\tb\n1\t2\n"


def test_an_extra_row_in_a_table_without_its_id_column_is_a_row_only_on_that_side(tmp_path):
    for side, rows in (("old", 1), ("new", 2)):
        (tmp_path / side).mkdir()
        (tmp_path / side / "occurrence.txt").write_text("a\n" + "x\n" * rows)
    diff = compare._compare_table(
        "occurrence", tmp_path / "old", tmp_path / "new", "occurrence.txt", "id"
    )
    assert (diff.rows_only_in_new, diff.diverged) == (1, True)


def _compare_measurements(tmp_path, old_rows, new_rows):
    for side, rows in (("old", old_rows), ("new", new_rows)):
        (tmp_path / side).mkdir()
        lines = ["coreid\tmeasurementType\tmeasurementValue", *rows]
        (tmp_path / side / "emof.txt").write_text("\n".join(lines) + "\n")
    return compare._compare_table("emof", tmp_path / "old", tmp_path / "new", "emof.txt", "coreid")


def test_a_changed_value_in_any_row_of_an_id_is_a_difference(tmp_path):
    diff = _compare_measurements(
        tmp_path,
        ["o1\ttemperature\t12", "o1\tdepth\t5"],
        ["o1\ttemperature\t13", "o1\tdepth\t5"],
    )

    assert diff.value_diff_counts == {"measurementValue": 1}
    assert diff.value_examples == [
        {"table": "emof", "id": "o1", "column": "measurementValue", "old": "12", "new": "13"}
    ]


def test_an_extra_row_for_an_id_is_a_row_only_on_that_side(tmp_path):
    diff = _compare_measurements(
        tmp_path,
        ["o1\ttemperature\t12", "o1\tdepth\t5"],
        ["o1\ttemperature\t12", "o1\tdepth\t5", "o1\tsalinity\t33"],
    )

    assert (diff.rows_only_in_new, diff.only_in_new) == (1, ["o1"])
    assert (diff.rows_only_in_old, diff.value_diff_counts) == (0, {})


def test_a_removed_row_is_the_only_difference_reported(tmp_path):
    diff = _compare_measurements(
        tmp_path,
        ["o1\ttemperature\t12", "o1\tdepth\t5", "o1\tsalinity\t33"],
        ["o1\ttemperature\t12", "o1\tsalinity\t33"],
    )

    assert (diff.rows_only_in_old, diff.only_in_old) == (1, ["o1"])
    assert (diff.value_diff_counts, diff.row_order_matches) == ({}, True)


def test_a_row_inserted_before_the_others_is_the_only_difference_reported(tmp_path):
    diff = _compare_measurements(
        tmp_path,
        ["o1\ttemperature\t12", "o1\tdepth\t5"],
        ["o1\tsalinity\t33", "o1\ttemperature\t12", "o1\tdepth\t5"],
    )

    assert diff.rows_only_in_new == 1
    assert (diff.value_diff_counts, diff.row_order_matches) == ({}, True)


def test_rows_reordered_within_an_id_are_a_change_of_order_not_of_values(tmp_path):
    diff = _compare_measurements(
        tmp_path,
        ["o1\ttemperature\t12", "o1\tdepth\t5"],
        ["o1\tdepth\t5", "o1\ttemperature\t12"],
    )

    assert (diff.row_order_matches, diff.value_diff_counts) == (False, {})
