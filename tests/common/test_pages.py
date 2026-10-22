from __future__ import annotations

from edna2dwc.common import pages

PAGE = "# Inspection of data/\n\n| File | Format |\n| --- | --- |\n| a.xlsx | xlsx |\n\n- **Missing**: `eventDate`\n\n```\nedna2dwc build --automatic\n```\n"


def test_write_page_writes_the_markdown_and_an_html_twin_beside_it(tmp_path):
    written = pages.write_page(tmp_path / "INSPECTION.md", PAGE)

    assert written == (tmp_path / "INSPECTION.md", tmp_path / "INSPECTION.html")
    assert (tmp_path / "INSPECTION.md").read_text(encoding="utf-8") == PAGE
    html = (tmp_path / "INSPECTION.html").read_text(encoding="utf-8")
    assert html.startswith("<!DOCTYPE html>")
    assert "<title>Inspection of data/</title>" in html
    assert "<table>" in html and "<th>Format</th>" in html
    assert "<strong>Missing</strong>: <code>eventDate</code>" in html
    assert "<pre><code>edna2dwc build --automatic" in html


def test_html_is_self_contained_and_needs_no_network():
    html = pages.to_html("# T\n\nbody\n")
    assert "<style>" in html
    assert "http" not in html


def test_title_falls_back_to_the_file_name_when_the_page_has_no_heading():
    assert "<title>REVIEW</title>" in pages.to_html("no heading here\n", fallback_title="REVIEW")


def test_markup_in_values_is_escaped_not_rendered():
    html = pages.to_html("# T\n\n| a |\n| --- |\n| <script>x</script> |\n")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_a_table_cell_keeps_a_pipe_and_a_line_break_inside_its_row():
    assert pages.table(["Column"], [["a|b\nc"]]) == ["| Column |", "| --- |", "| a\\|b c |"]
