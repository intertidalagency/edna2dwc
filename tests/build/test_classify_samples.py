from __future__ import annotations

from edna2dwc.build.classify_samples import classify
from tests.tables import table_of


def _row(sample_id, feature_id="f1", **extra):
    return {
        "sampleID": sample_id,
        "featureID": feature_id,
        "count": "3",
        "taxonomy": "d__x",
        **extra,
    }


def _by_id(rows):
    return {row["sampleID"]: row for row in rows}


def test_the_roster_is_built_from_a_table_that_has_no_taxonomy_yet():
    result = classify(table_of([_row("FieldBlank01"), _row("Site7"), _row("Site7", "f2")]))

    assert result.findings.findings == []
    by_id = _by_id(result.roster)
    assert by_id["FieldBlank01"]["type"] == "control"
    assert by_id["FieldBlank01"]["action"] == "excluded"
    assert by_id["Site7"]["type"] == "sample"
    assert by_id["Site7"]["row_count"] == "2"


def test_an_answer_keeps_a_sample_the_tool_would_exclude():
    result = classify(table_of([_row("FieldBlank01")]), control_answers={"FieldBlank01": "sample"})

    by_id = _by_id(result.roster)
    assert (by_id["FieldBlank01"]["type"], by_id["FieldBlank01"]["action"]) == ("sample", "kept")


def test_an_answer_excludes_a_sample_the_tool_would_keep():
    result = classify(table_of([_row("Site7")]), control_answers={"Site7": "control"})

    by_id = _by_id(result.roster)
    assert (by_id["Site7"]["type"], by_id["Site7"]["action"]) == ("control", "excluded")


def test_the_proposal_ignores_the_answers():
    result = classify(table_of([_row("FieldBlank01")]), control_answers={"FieldBlank01": "sample"})

    proposed = _by_id(result.proposal)
    assert proposed["FieldBlank01"]["type"] == "control"
    assert proposed["FieldBlank01"]["action"] == "excluded"


def test_an_answer_for_a_sample_the_table_lacks_is_reported_and_dropped():
    result = classify(
        table_of([_row("Site7")]), control_answers={"Site7": "sample", "Gone9": "control"}
    )

    (finding,) = result.findings.findings
    assert finding.code == "CONTROL_ANSWER_UNMATCHED"
    assert "Gone9" in finding.message
    assert set(_by_id(result.roster)) == {"Site7"}


def test_an_uncorroborated_keyword_match_is_left_ambiguous():
    result = classify(table_of([_row("NC-1")]))

    assert [f.code for f in result.findings.findings] == ["CONTROL_AMBIGUOUS"]
    assert _by_id(result.roster)["NC-1"]["action"] == "ambiguous"


def test_a_type_column_in_the_occurrence_table_outranks_the_sample_id():
    result = classify(
        table_of([_row("Site7", sample_type="blank")]), occurrence_type_col="sample_type"
    )

    by_id = _by_id(result.roster)
    assert by_id["Site7"]["basis"] == "occurrence_type"
    assert by_id["Site7"]["action"] == "excluded"


def test_sample_metadata_reaches_the_strongest_evidence_tier():
    result = classify(table_of([_row("Site7")]), sample_types={"Site7": "negative control"})

    assert _by_id(result.roster)["Site7"]["basis"] == "sample_metadata"


def test_an_answered_control_classification_resolves_the_ambiguous_sample():
    result = classify(
        table_of([_row("NC1"), _row("NC2")]), control_answers={"NC1": "control", "NC2": "sample"}
    )

    assert result.findings.findings == []
    by_id = _by_id(result.roster)
    assert (by_id["NC1"]["type"], by_id["NC1"]["action"]) == ("control", "excluded")
    assert (by_id["NC2"]["type"], by_id["NC2"]["action"]) == ("sample", "kept")
    assert _by_id(result.proposal)["NC1"]["action"] == "ambiguous"
