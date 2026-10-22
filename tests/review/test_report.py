from __future__ import annotations




        "dataset_title": "A test dataset",
        "archive_path": "out/ds-dwca.zip",
        "archive_filename": "dwca.zip",
        "core_type": "occurrence",
        "extension_types": ("dnaderiveddata",),
        "record_count": 10,
        "sample_count": 3,
        "findings": [],
        "ask_list": [],
        "term_state_counts": None,
    }
    kwargs.update(overrides)


def _finding(code, message="something happened", severity="warning", count=1):
    return {"code": code, "message": message, "severity": severity, "count": count}


    report = _base_report(
        findings=[_finding("ARCHIVE_INVALID", severity="error", count=2)],
    )




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


    report = _base_report(findings=[_finding("ARCHIVE_INVALID", severity="error")])
    assert report.transformations == []




    report = _base_report(
        findings=[
        ]
    )
    assert len(report.recommendations) == 1
    assert "annealingTemp" in report.recommendations[0]


def test_recommendations_falls_back_to_the_raw_message_for_an_unmapped_term():
    report = _base_report(
        findings=[
        ]
    )
    assert "notInTheLookup" in report.recommendations[0]


def test_recommendations_falls_back_to_the_verbatim_message_when_the_shape_does_not_match():
    message = (
        "countryCode: (37.5, -122.1) falls outside every vendored land polygon "
    )






def test_render_markdown_includes_every_section_header():
    report = _base_report()
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




