from __future__ import annotations

from dataclasses import dataclass

import pytest

from edna2dwc.build.classify_samples import classify
from edna2dwc.build.exclude_taxa import exclude, human_taxa
from edna2dwc.build.filter_controls import (
    classification_from_report_row,
    classify_sample,
    control_samples,
    match_keywords,
    tokenize,
)
from edna2dwc.common.findings import FindingsLog
from tests.tables import dicts, table_of


@dataclass
class Removed:
    kept_rows: list[dict[str, str]]
    excluded_rows: list[dict[str, str]]
    findings: FindingsLog


def remove_controls(rows, roster) -> Removed:
    table = table_of(rows)
    result = exclude(
        table,
        controls=control_samples(table.con, roster),
        humans=human_taxa(table),
        drop_human=False,
        excluded_kingdoms_by_marker=None,
    )
    return Removed(dicts(result.kept), dicts(result.excluded), result.findings)


def filter_controls(rows, **classify_options) -> Removed:
    classified = classify(table_of(rows), **classify_options)
    result = remove_controls(rows, classified.roster)
    result.findings.findings[:0] = classified.findings.findings
    return result


def _roster_row(sample_id, kind, action, keyword="", basis="none"):
    return {
        "sampleID": sample_id,
        "type": kind,
        "basis": basis,
        "matched_keyword": keyword,
        "action": action,
        "row_count": "1",
    }


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


def test_short_keyword_only_match_is_kept_and_disclosed():
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
    codes = [f.code for f in result.findings.findings]
    assert codes.count("CONTROL_AMBIGUOUS") == 6


def test_a_confident_keyword_match_excludes_without_asking():
    rows = [
        {"sampleID": "ExtractionBlank01", "featureID": "f1", "count": "1"},
        {"sampleID": "RealSample01", "featureID": "f2", "count": "1"},
    ]
    result = filter_controls(rows)
    assert [r["sampleID"] for r in result.kept_rows] == ["RealSample01"]
    assert [(row["sampleID"], row["exclusion_reason"]) for row in result.excluded_rows] == [
        ("ExtractionBlank01", "control:extraction blank")
    ]
    codes = [f.code for f in result.findings.findings]
    assert "CONTROL_EXCLUDED" in codes
    assert "CONTROL_AMBIGUOUS" not in codes


def test_metadata_type_column_tier_one_takes_precedence_and_excludes():
    rows = [{"sampleID": "S1", "featureID": "f1", "count": "1"}]
    result = filter_controls(rows, sample_types={"S1": "blank"})
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


def test_only_positive_controls_seed_the_leakage_taxa_not_every_control():
    rows = [
        {
            "sampleID": "ExtractionBlank01",
            "featureID": "asv_contam",
            "count": "3",
            "scientificName": "Pseudomonas",
        },
        {
            "sampleID": "MockCommunity1",
            "featureID": "asv_spike",
            "count": "50",
            "scientificName": "Macropus giganteus",
        },
        {
            "sampleID": "FieldSample1",
            "featureID": "asv_pseudo",
            "count": "8",
            "scientificName": "Pseudomonas",
        },
    ]
    result = filter_controls(rows)

    assert classify_sample("ExtractionBlank01").is_positive_control is False
    assert classify_sample("MockCommunity1").is_positive_control is True

    leaked = [f.message for f in result.findings.findings if f.code == "CONTROL_TAXON_LEAKAGE"]
    assert leaked == [], leaked

    kept_ids = {(r["sampleID"], r["featureID"]) for r in result.kept_rows}
    assert ("FieldSample1", "asv_pseudo") in kept_ids


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


def test_remove_controls_honors_a_hand_edited_classification():
    rows = [
        {"sampleID": "NC1", "featureID": "f1", "count": "1"},
        {"sampleID": "RealSample01", "featureID": "f2", "count": "1"},
    ]
    roster = [
        _roster_row("NC1", "control", "excluded", "nc", basis="answer"),
        _roster_row("RealSample01", "sample", "kept"),
    ]
    result = remove_controls(rows, roster)
    assert {r["sampleID"] for r in result.kept_rows} == {"RealSample01"}
    assert "CONTROL_AMBIGUOUS" not in [f.code for f in result.findings.findings]


def test_removing_controls_does_not_disclose_an_ambiguous_sample_a_second_time():
    rows = [{"sampleID": "NC1", "featureID": "f1", "count": "1"}]
    roster = [_roster_row("NC1", "control", "ambiguous", "nc", basis="sample_id_string_match")]

    result = remove_controls(rows, roster)

    assert [f.code for f in result.findings.findings] == []


@pytest.mark.parametrize("sample_id", ["FC_NegPCR", "negpcr1", "PCR-Neg-2"])
def test_a_pcr_negative_written_neg_pcr_is_a_confident_control(sample_id):
    classification = classify_sample(sample_id)
    assert classification.is_control
    assert not classification.is_ambiguous


def test_a_bare_neg_is_an_ambiguous_control_keyword():
    classification = classify_sample("Site4-Neg")
    assert classification.is_control
    assert classification.is_ambiguous
    assert classification.matched_keyword == "neg"


@pytest.mark.parametrize(
    "value", ["rtsf blank", "PCR negative control", "Field Blank", "extraction blank"]
)
def test_a_type_value_naming_a_control_in_words_classifies_it(value):
    classification = classify_sample("SAMPLE_1", metadata_type=value)
    assert classification.is_control
    assert classification.basis == "sample_metadata"
    assert not classification.is_ambiguous


def test_a_type_value_with_only_a_weak_keyword_asks():
    classification = classify_sample("S7", metadata_type="NC")
    assert classification.is_control
    assert classification.is_ambiguous
    assert classification.basis == "sample_metadata"


def test_a_type_value_naming_no_control_leaves_the_sample_id_to_decide():
    assert not classify_sample("Station4", metadata_type="seawater").is_control
    assert classify_sample("FieldBlank02", metadata_type="seawater").is_control
