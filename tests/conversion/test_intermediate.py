import pytest

from edna2dwc.common.table import connect
from edna2dwc.conversion.intermediate import (
    IntermediateInvalid,
    require_valid,
    validate_intermediate,
)
from tests.make_fixtures import FIXTURES, FIXTURES_DIR


def codes(log):
    return [f.code for f in log.findings]


@pytest.mark.parametrize(("filename", "expected_codes"), [(f, c) for f, _content, c in FIXTURES])
def test_fixture_produces_its_designated_codes(filename, expected_codes):
    path = FIXTURES_DIR / filename
    log = validate_intermediate(path)
    if not expected_codes:
        assert log.findings == [], f"{filename} should be valid, got {codes(log)}"
    else:
        for code in expected_codes:
            assert code in codes(log), f"{filename} should produce {code}, got {codes(log)}"


def test_multiple_violations_all_accumulate_not_just_the_first(tmp_path):
    path = tmp_path / "occurrence_long.tsv"
    path.write_text("sampleID\tfeatureID\tcount\ttaxonomy\ns1\t\tNA\td__Bacteria\n")
    log = validate_intermediate(path)
    assert "CONTRACT_INVALID" in codes(log)
    assert "CONTRACT_TYPE_INVALID" in codes(log)
    assert len(log.findings) >= 2


def test_blank_sample_ids_are_one_finding_with_the_count_and_first_rows(tmp_path):
    path = tmp_path / "occurrence_long.tsv"
    rows = "".join(f"\tf{i}\t1\td__Bacteria\n" for i in range(8))
    path.write_text("sampleID\tfeatureID\tcount\ttaxonomy\n" + rows)
    log = validate_intermediate(path)
    blank = [f for f in log.findings if "sampleID" in f.message]
    assert len(blank) == 1
    assert blank[0].count == 8
    assert "rows 2, 3, 4, 5, 6 and 3 more" in blank[0].message
    assert "reader script" in blank[0].message


def test_a_table_where_no_row_has_a_lineage_warns_that_every_taxon_is_the_placeholder(tmp_path):
    path = tmp_path / "occurrence_long.tsv"
    path.write_text(
        "sampleID\tfeatureID\tcount\ttaxonomy\tgenus\ns1\tf1\t1\t\t\ns2\tf2\t1\tNA\t\n"
    )
    log = validate_intermediate(path)
    assert codes(log) == ["TAXONOMY_BLANK"]
    assert not log.has_errors()


def test_a_table_where_some_rows_have_a_lineage_does_not_warn(tmp_path):
    path = tmp_path / "occurrence_long.tsv"
    path.write_text("sampleID\tfeatureID\tcount\ttaxonomy\ns1\tf1\t1\t\ns2\tf2\t1\td__Bacteria\n")
    assert validate_intermediate(path).findings == []


def test_a_comma_separated_file_is_rejected_as_not_tab_separated(tmp_path):
    path = tmp_path / "occurrence_long.tsv"
    path.write_text("sampleID,featureID,count,taxonomy\ns1,f1,10,d__Bacteria\n")
    log = validate_intermediate(path)
    assert codes(log) == ["CONTRACT_INVALID"]
    assert str(path) in log.findings[0].message
    assert "tab-separated" in log.findings[0].message


def _validated(tmp_path, header: str, row: str):
    path = tmp_path / "occurrence_long.tsv"
    path.write_text(f"sampleID\tfeatureID\tcount\t{header}\ns1\tf1\t3\t{row}\n", encoding="utf-8")
    return validate_intermediate(path)


@pytest.mark.parametrize("column", ["species", "scientificName", "Genus"])
def test_any_column_resolve_taxonomy_reads_a_name_from_is_enough(tmp_path, column):
    assert codes(_validated(tmp_path, column, "Carcharhinus limbatus")) == []


@pytest.mark.parametrize("column", ["taxonConceptID", "scientificNameID", "taxonRank"])
def test_a_column_resolve_taxonomy_writes_is_refused_with_where_its_value_goes(tmp_path, column):
    log = _validated(tmp_path, f"species\t{column}", "Micromonas pusilla\tNCBI:txid38833")
    (finding,) = log.findings
    assert finding.code == "CONTRACT_COLUMN_RESERVED"
    assert all(word in finding.message for word in (column, "ncbi_taxid", "source_taxon_id"))


def test_require_valid_returns_the_table_it_checked_on_the_callers_connection(tmp_path):
    path = tmp_path / "occurrence_long.tsv"
    path.write_text(
        "sampleID\tfeatureID\tcount\ttaxonomy\ns1\tf1\t3\td__Bacteria\n", encoding="utf-8"
    )

    with connect() as con:
        table = require_valid(path, con)
        assert table.con is con
        assert table.rows(
            f"SELECT {table.get('sampleID')}, {table.get('count')} FROM {table.name}"
        ) == [("s1", "3")]


@pytest.mark.parametrize("count", ["NA", "NaN", "inf", "-Infinity"])
def test_a_count_that_is_not_finite_is_refused(tmp_path, count):
    path = tmp_path / "occurrence_long.tsv"
    path.write_text(
        f"sampleID\tfeatureID\tcount\ttaxonomy\ns1\tf1\t{count}\td__Bacteria\n", encoding="utf-8"
    )

    with connect() as con, pytest.raises(IntermediateInvalid, match="not a finite number"):
        require_valid(path, con)
