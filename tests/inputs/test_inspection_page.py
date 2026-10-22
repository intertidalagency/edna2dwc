from __future__ import annotations

from pathlib import Path

import pytest

from edna2dwc.inputs import inspection_page
from edna2dwc.inputs.inspect import inspect_path
from edna2dwc.terms.term_table import load_term_table
from tests.paths import INPUT_FIXTURES


@pytest.fixture(scope="module")
def term_table() -> dict:
    return load_term_table()


def _assess(term_table, *names):
    return inspection_page.assess([inspect_path(INPUT_FIXTURES / n) for n in names], term_table)


def test_a_workbook_supplies_terms_by_column_name_sheet_by_sheet(term_table):
    result = _assess(term_table, "multisheet.xlsx")

    found = {(c.term, c.table, c.column) for c in result.found}
    assert found == {
        ("materialSampleID", "Samples", "Sample Name"),
        ("locationID", "Samples", "Site"),
        ("minimumDepthInMeters", "Samples", "Depth (m)"),
    }
    assert result.feature_tables == [f"{INPUT_FIXTURES / 'multisheet.xlsx'} / Counts"]
    assert result.taxonomy_sources == [f"{INPUT_FIXTURES / 'multisheet.xlsx'} / Taxonomy"]


def test_terms_are_found_derived_or_missing_and_derivation_depends_on_what_was_found(term_table):
    result = _assess(term_table, "multisheet.xlsx")

    status = {t.term: t.status for t in result.terms}
    assert status["materialSampleID"] == "found"
    assert status["scientificName"] == "derived"
    assert status["occurrenceID"] == "derived"
    assert status["countryCode"] == "missing"
    assert status["decimalLatitude"] == "missing"
    assert status["eventDate"] == "missing"
    assert [t.tier for t in result.terms[:12]] == ["required"] * 12


def test_a_feature_table_without_taxonomy_cannot_have_names_derived(term_table):
    result = _assess(term_table, "table.qza")

    assert result.feature_tables == [str(INPUT_FIXTURES / "table.qza")]
    assert result.taxonomy_sources == []
    status = {t.term: t.status for t in result.terms}
    assert status["scientificName"] == "missing"
    assert status["occurrenceID"] == "derived"


def test_biom_and_phyloseq_inputs_count_as_feature_tables_with_taxonomy(term_table):
    result = _assess(term_table, "sample_v2.biom", "sample_phyloseq.rds")

    assert len(result.feature_tables) == 2
    assert result.taxonomy_sources == [str(INPUT_FIXTURES / "sample_v2.biom")]


def test_documentation_and_unrecognized_files_are_named_for_what_they_are(term_table, tmp_path):
    (tmp_path / "methods.md").write_text("# Methods\n\nPrimers: ...\n", encoding="utf-8")
    reports = [
        inspect_path(tmp_path / "methods.md"),
        inspect_path(INPUT_FIXTURES / "custom_export.lims"),
    ]

    result = inspection_page.assess(reports, term_table)

    roles = {Path(f.path).name: f.role for f in result.files}
    assert roles["methods.md"] == "documentation"
    assert roles["custom_export.lims"] == "unrecognized"
    assert any("methods.md" in d for d in result.decisions)
    assert any(d.startswith("**Which reading of a layout") for d in result.decisions)


def test_the_page_leads_with_the_summary_then_how_the_conversion_goes(term_table):
    result = _assess(term_table, "multisheet.xlsx")

    page = inspection_page.render_markdown(result, inputs=["data/"])

    assert not {c.term for c in result.found} & set(inspection_page.COORDINATE_TERMS)
    assert "| `decimalLatitude` | required |" in page
    headings = [line for line in page.splitlines() if line.startswith("## ")]
    assert headings[:2] == ["## How this conversion goes", "## Questions you will be asked"]
    assert "1. **Inspect**: " in page
    assert "5. **Check**: " in page


def test_a_column_name_with_a_line_break_stays_in_one_table_row():
    found = inspection_page.FoundColumn(
        "minimumDepthInMeters", "samples.xlsx", "Samples", "Depth\n(m)"
    )
    readiness = inspection_page.Readiness([], [], [], [found], [])

    page = inspection_page.render_markdown(readiness, inputs=["data/"])

    assert "| `minimumDepthInMeters` | `samples.xlsx` | Samples | `Depth (m)` |" in page
