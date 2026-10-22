from __future__ import annotations

import re
from typing import Any

import pytest

from edna2dwc.common.findings import CODES, meaning
from edna2dwc.review.report import (
    RECORDING_LOCATIONS,
    ConversionReport,
    build_report,
    render_markdown,
)
from tests.paths import PACKAGE_DIR

CODE_MEANING = meaning("TAXON_FUZZY_REJECTED").rstrip(".") + "."


def _base_report(**overrides) -> ConversionReport:
    kwargs: dict[str, Any] = {
        "dataset_title": "A test dataset",
        "archive_path": "out/ds-dwca.zip",
        "archive_filename": "dwca.zip",
        "core_type": "occurrence",
        "extension_types": ("dnaderiveddata",),
        "record_count": 10,
        "sample_count": 3,
        "findings": [],
        "open_sheets": 0,
        "ask_list": [],
        "audit_findings": [],
        "provenance": {"title": "title"},
        "term_state_counts": None,
    }
    kwargs.update(overrides)
    return build_report(**kwargs)


def _finding(code, message="something happened", severity="warning", count=1):
    return {"code": code, "message": message, "severity": severity, "count": count}


def test_action_items_flags_error_findings_open_proposals_and_ask_list():
    report = _base_report(
        findings=[_finding("ARCHIVE_INVALID", severity="error", count=2)],
        open_sheets=1,
        ask_list=["contacts"],
    )
    assert report.action_items == [
        "Resolve 2 error-level finding(s) (see What was transformed).",
        "Review 1 open proposal(s) (see REVIEW.md).",
        "Answer 1 unset metadata field(s): contacts.",
        "Upload dwca.zip to the target repository once the above are done.",
    ]


@pytest.mark.parametrize("audit_findings", [None, ["eml.xml: an invented vessel"]])
def test_the_audit_never_adds_an_action_item(audit_findings):
    report = _base_report(audit_findings=audit_findings)
    assert not any("audit" in item for item in report.action_items)


def test_transformations_groups_by_code_in_the_fixed_order_and_counts():
    report = _base_report(
        findings=[
            _finding("TAXON_UNRESOLVED", count=3),
            _finding("PRESENCE_ONLY_FILTERED", count=5, message="dropped 5 zero-count rows"),
            _finding("PRESENCE_ONLY_FILTERED", count=2, message="dropped 2 more"),
        ]
    )
    codes = [t.code for t in report.transformations]
    assert codes == ["PRESENCE_ONLY_FILTERED", "TAXON_UNRESOLVED"]
    presence = next(t for t in report.transformations if t.code == "PRESENCE_ONLY_FILTERED")
    assert presence.count == 7


def test_transformations_keeps_an_uncurated_error_out_of_its_own_section():
    report = _base_report(findings=[_finding("ARCHIVE_INVALID", severity="error")])
    assert report.transformations == []
    assert [q.code for q in report.open_questions] == ["ARCHIVE_INVALID"]


def test_open_questions_includes_a_proposal_accepted_unconfirmed():
    report = _base_report(
        findings=[_finding("PROPOSAL_ACCEPTED", message="samples used as written")]
    )
    assert [q.code for q in report.open_questions] == ["PROPOSAL_ACCEPTED"]


def test_recommendations_extracts_the_term_name_from_term_missing_priority():
    report = _base_report(
        findings=[
            _finding("TERM_MISSING_PRIORITY", message="'annealingTemp' is filled on 0 of 3 rows")
        ]
    )
    assert len(report.recommendations) == 1
    assert "annealingTemp" in report.recommendations[0]
    assert RECORDING_LOCATIONS["annealingTemp"] in report.recommendations[0]


def test_recommendations_name_a_missing_strongly_recommended_term_too():
    report = _base_report(
        findings=[
            _finding(
                "TERM_MISSING_RECOMMENDED", message="'institutionCode' is filled on 0 of 3 rows"
            )
        ]
    )
    assert report.recommendations
    assert "institutionCode" in report.recommendations[0]


def test_recommendations_falls_back_to_the_raw_message_for_an_unmapped_term():
    report = _base_report(
        findings=[
            _finding("TERM_MISSING_PRIORITY", message="'notInTheLookup' is filled on 0 of 3 rows")
        ]
    )
    assert "notInTheLookup" in report.recommendations[0]


def test_recommendations_falls_back_to_the_verbatim_message_when_the_shape_does_not_match():
    message = (
        "countryCode: (37.5, -122.1) falls outside every vendored land polygon "
        "(open water, or a disputed-status unit with no ISO code), left blank, not guessed"
    )
    report = _base_report(findings=[_finding("TERM_MISSING_PRIORITY", message=message)])
    assert len(report.recommendations) == 1
    assert message in report.recommendations[0]


def test_action_items_ask_to_set_each_blank_metadata_field():
    report = _base_report(blank_metadata=["title", "creators"])
    assert any("2 blank" in item and "title, creators" in item for item in report.action_items)


def test_action_items_ask_to_confirm_the_unconfirmed_answers():
    report = _base_report(unconfirmed=2)
    (item,) = [item for item in report.action_items if "confirm" in item.casefold()]
    assert "2 answer(s)" in item
    assert "REVIEW.md" in item
    assert "confirmed:" in item


def test_the_provenance_section_says_which_fields_a_person_confirmed():
    report = _base_report(
        provenance={"title": "eml.xml title", "abstract": "methods.pdf p. 1"},
        confirmed={"title": "PI: yes"},
    )
    markdown = render_markdown(report)
    assert "title: eml.xml title; confirmed: PI: yes" in markdown
    assert "abstract: methods.pdf p. 1; not confirmed by a person" in markdown


@pytest.mark.parametrize(
    ("audit_findings", "summary"), [(None, "not recorded"), (["a", "b"], "2 finding(s) recorded")]
)
def test_audit_summary_counts_what_the_audit_recorded(audit_findings, summary):
    assert _base_report(audit_findings=audit_findings).audit_summary == summary


def test_the_report_carries_every_recorded_audit_finding():
    report = _base_report(
        audit_findings=[
            "eml.xml: the abstract names a survey vessel absent from every source file",
            "occurrence.txt row 4102: decimalLatitude has no verbatim counterpart",
            "manifest.json: contact is tagged eml:contact and eml.xml holds another name",
        ],
    )
    markdown = render_markdown(report)
    assert "survey vessel" in markdown
    assert "row 4102" in markdown
    assert "eml:contact" in markdown


def test_recommendations_state_a_term_once_however_many_rows_reported_it():
    findings = [
        _finding("TERM_MISSING_PRIORITY", "'annealingTemp' is filled on 0 of 3 rows")
        for _ in range(50)
    ]
    report = _base_report(findings=findings)
    assert len(report.recommendations) == 1


def test_render_markdown_includes_every_section_header():
    report = _base_report()
    markdown = render_markdown(report)
    for heading in (
        "## 1. What this is",
        "## 2. Action items",
        "## 3. What was transformed",
        "## 4. Open questions",
        "## 5. Recommendations for future datasets",
        "## 6. Provenance and audit",
        "## 7. How to reproduce",
    ):
        assert heading in markdown


@pytest.mark.parametrize(
    ("counts", "shown"), [({"Filled": 40, "Ask": 2}, ["Filled: 40", "Ask: 2"]), (None, [])]
)
def test_render_markdown_includes_the_term_state_summary_only_when_given(counts, shown):
    markdown = render_markdown(_base_report(term_state_counts=counts))
    assert [line for line in ("Filled: 40", "Ask: 2") if line in markdown] == shown
    assert ("Filled:" in markdown) is bool(shown)


def _template_justfile() -> str:
    return (PACKAGE_DIR / "templates" / "justfile").read_text(encoding="utf-8")


def _reproduce_command_lines() -> list[str]:
    lines = []
    for line in render_markdown(_base_report()).splitlines():
        stripped = line.strip()
        if stripped.startswith("just "):
            lines.append(stripped.split("#")[0].strip())
    return lines


def test_reproduce_lines_only_name_real_justfile_recipes():
    justfile = _template_justfile()
    for command in _reproduce_command_lines():
        recipe = command.split()[-1]
        assert f"\n{recipe}:" in justfile, f"{recipe!r} is not a real justfile recipe"


def test_reproduce_lines_only_set_variables_the_justfile_declares():
    justfile = _template_justfile()
    for command in _reproduce_command_lines():
        for name in re.findall(r"\b([a-z][a-z_]*)=", command):
            assert f"{name} :=" in justfile, f"{name!r} is not a justfile variable"


def test_reproduce_lines_run_from_where_the_justfile_actually_is():
    rendered = render_markdown(_base_report())
    assert "cd reproduce" in rendered
    assert "bundle_dir=reproduce" not in rendered


def test_the_reproduce_note_says_check_needs_the_shipped_zip_named():
    rendered = render_markdown(_base_report())
    assert "`just check`" in rendered
    assert "dwca.zip" in rendered


def test_every_finding_code_in_the_vocabulary_is_shown_in_the_rendered_report():
    unshown = []
    for code in sorted(CODES):
        message = f"sentinel detail for {code}"
        report = _base_report(findings=[_finding(code, message=message, severity="error")])
        if message not in render_markdown(report):
            unshown.append(code)
    assert unshown == []


def test_an_uncurated_info_finding_is_shown_as_a_transformation():
    report = _base_report(
        findings=[_finding("SAMPLE_SIZE_PER_MARKER", message="summed per marker", severity="info")]
    )
    assert [t.code for t in report.transformations] == ["SAMPLE_SIZE_PER_MARKER"]
    assert report.open_questions == []


def test_a_curated_code_keeps_its_own_section_and_order():
    report = _base_report(
        findings=[
            _finding("TERM_UNMAPPED", message="a term", severity="warning"),
            _finding("PRESENCE_ONLY_FILTERED", message="zero counts", severity="info"),
            _finding("CONTROL_AMBIGUOUS", message="a sample", severity="error"),
        ]
    )
    assert [t.code for t in report.transformations] == ["PRESENCE_ONLY_FILTERED", "TERM_UNMAPPED"]
    assert [q.code for q in report.open_questions] == ["CONTROL_AMBIGUOUS"]


def test_each_code_group_says_what_its_code_means():
    report = _base_report(findings=[_finding("TAXON_FUZZY_REJECTED", "3 matches refused")])
    text = render_markdown(report)
    (line,) = [line for line in text.splitlines() if "TAXON_FUZZY_REJECTED" in line]
    assert CODE_MEANING in line
    assert "3 matches refused" in line


def test_a_required_eml_element_left_out_is_an_action_item():
    report = _base_report(blank_metadata=["title"], missing_eml_elements=["title"])
    assert any("<title>" in item and "GBIF" in item for item in report.action_items)
