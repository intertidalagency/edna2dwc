from __future__ import annotations

    classification_from_report_row,
    classify_sample,
    match_keywords,
    tokenize,
)


def test_tokenize_splits_on_case_and_digit_transitions():
    assert tokenize("FieldBlank02") == ["Field", "Blank", "02"]
    assert tokenize("NTC-3") == ["NTC", "3"]
    assert tokenize("PLANTC1") == ["PLANTC", "1"]


def test_unanchored_keywords_do_not_over_match_real_names():
    assert match_keywords("PLANTC1") == []
    assert match_keywords("SEDIMENTC3") == []
    assert match_keywords("ATLANTC") == []
    assert match_keywords("MockhornBay12") == []
    matches = match_keywords("BACI-Control-Site1")
    assert any(m.keyword == "control" for m in matches)


def test_multiword_keyword_beats_its_own_component_word():
    matches = match_keywords("ExtractionBlank01")
    assert {m.keyword for m in matches} == {"extraction blank", "blank"}
    assert classify_sample("ExtractionBlank01").matched_keyword == "extraction blank"


    classification = classify_sample("NC1")
    assert classification.is_control
    assert classification.is_ambiguous
    assert classification.matched_keyword == "nc"

    rows = [
        {"sampleID": f"NC{i}", "featureID": f"f{i}", "count": "1", "scientificName": "Aaptos"}
        for i in range(1, 7)
    ]
    result = filter_controls(rows)
    assert len(result.kept_rows) == 6
    assert result.excluded_rows == []


    rows = [
        {"sampleID": "ExtractionBlank01", "featureID": "f1", "count": "1"},
        {"sampleID": "RealSample01", "featureID": "f2", "count": "1"},
    ]
    result = filter_controls(rows)
    assert [r["sampleID"] for r in result.kept_rows] == ["RealSample01"]
    codes = [f.code for f in result.findings.findings]
    assert "CONTROL_EXCLUDED" in codes


    rows = [{"sampleID": "S1", "featureID": "f1", "count": "1"}]
    assert result.kept_rows == []
    assert result.excluded_rows[0]["sampleID"] == "S1"


def test_occurrence_type_col_tier_two_actually_has_an_effect():
    rows = [
        {"sampleID": "WeirdName1", "featureID": "f1", "count": "1", "occurrence_type": "blank"},
        {"sampleID": "WeirdName2", "featureID": "f2", "count": "1", "occurrence_type": "sample"},
    ]
    result = filter_controls(rows, occurrence_type_col="occurrence_type")
    kept_ids = {r["sampleID"] for r in result.kept_rows}
    assert kept_ids == {"WeirdName2"}
    excluded = result.excluded_rows[0]
    assert excluded["sampleID"] == "WeirdName1"
    assert excluded["exclusion_reason"] == "control:blank"


def test_leakage_check_matches_the_resolved_taxon_not_the_feature_id():
    rows = [
        {
            "sampleID": "PositiveControl1",
            "featureID": "asv_pc",
            "count": "10",
            "scientificName": "Macropus giganteus",
        },
        {
            "sampleID": "FieldSample1",
            "featureID": "asv_other",
            "count": "2",
            "scientificName": "Macropus giganteus",
        },
        {
            "sampleID": "FieldSample1",
            "featureID": "asv_native",
            "count": "40",
            "scientificName": "Aaptos",
        },
    ]
    result = filter_controls(rows)
    codes = [f.code for f in result.findings.findings]
    assert "CONTROL_TAXON_LEAKAGE" in codes
    leakage = next(f for f in result.findings.findings if f.code == "CONTROL_TAXON_LEAKAGE")
    assert "Macropus giganteus" in leakage.message
    assert "FieldSample1" in leakage.message
    kept_ids = {(r["sampleID"], r["featureID"]) for r in result.kept_rows}
    assert ("FieldSample1", "asv_other") in kept_ids
    assert ("PositiveControl1", "asv_pc") not in kept_ids


def test_classification_from_report_row_round_trips_a_kept_sample():
    row = {
        "sampleID": "RealSample01",
        "type": "sample",
        "basis": "none",
        "matched_keyword": "",
        "action": "kept",
        "row_count": "3",
    }
    c = classification_from_report_row(row)
    assert c.sample_id == "RealSample01"
    assert c.is_control is False
    assert c.is_ambiguous is False
    assert c.is_positive_control is False


def test_classification_from_report_row_recognizes_a_positive_control():
    row = {
        "sampleID": "Mock1",
        "type": "control",
        "basis": "sample_id_string_match",
        "matched_keyword": "mock",
        "action": "excluded",
        "row_count": "2",
    }
    c = classification_from_report_row(row)
    assert c.is_control is True
    assert c.is_positive_control is True


    rows = [
        {"sampleID": "NC1", "featureID": "f1", "count": "1"},
        {"sampleID": "RealSample01", "featureID": "f2", "count": "1"},
    ]
    ]


