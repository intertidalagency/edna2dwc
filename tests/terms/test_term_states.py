from typing import Any

import pytest

from edna2dwc.terms import map_terms
from edna2dwc.terms import term_states as ts
from edna2dwc.terms.map_terms import MappingProposal
from tests.tables import table_of

TERM_TABLE = {
    "occurrenceID": {"priority_tier": "required"},
    "scientificName": {"priority_tier": "required"},
    "phylum": {"priority_tier": "recommended"},
    "probeReporter": {"priority_tier": "strongly_recommended"},
    "recordedBy": {},
}


def _filled(proposals, rows=None):
    return ts.filled_terms(proposals, table_of(rows) if rows is not None else None)


def test_b1c_terms_only_includes_terms_with_a_priority_tier():
    assert ts.b1c_terms(TERM_TABLE) == [
        "occurrenceID",
        "phylum",
        "probeReporter",
        "scientificName",
    ]


@pytest.mark.parametrize(
    ("judgment", "state"),
    [
        ("filled_terms", "Filled"),
        ("ask_terms", "Ask"),
        ("impossible_terms", "Impossible"),
        ("not_applicable_terms", "Not-applicable"),
    ],
)
def test_classify_term_states_gives_a_judged_term_its_state_and_evidence(judgment, state):
    judged: dict[str, Any] = {judgment: {"phylum": "the evidence"}}
    (stated,) = ts.classify_term_states(["phylum"], **judged)
    assert (stated.state, stated.evidence) == (state, "the evidence")


def test_classify_term_states_unclassified_reports_empty_state():
    states = ts.classify_term_states(["phylum"])
    assert states[0].state == ""


def test_classify_term_states_qpcr_block_auto_not_applicable_for_metabarcoding():
    states = ts.classify_term_states(["probeReporter"], assay_type="metabarcoding")
    assert states[0].state == "Not-applicable"
    assert states[0].evidence == ts.METABARCODING_NOT_APPLICABLE_REASON


def test_classify_term_states_qpcr_block_not_auto_marked_for_targeted_assay():
    states = ts.classify_term_states(["probeReporter"], assay_type="targeted_assay")
    assert states[0].state == ""


def test_classify_term_states_qpcr_block_respects_an_existing_filled_state():
    states = ts.classify_term_states(
        ["probeReporter"],
        filled_terms={"probeReporter": "term_mapping.tsv:reporter_dye"},
        assay_type="metabarcoding",
    )
    assert states[0].state == "Filled"


def test_check_every_term_has_a_state_passes_when_all_classified():
    states = [ts.TermState("occurrenceID", "Filled", "x")]
    passed, reason = ts.check_every_term_has_a_state(states)
    assert passed is True
    assert reason == ""


def test_check_every_term_has_a_state_fails_and_names_the_gap():
    states = [ts.TermState("occurrenceID", "Filled", "x"), ts.TermState("phylum", "", "")]
    passed, reason = ts.check_every_term_has_a_state(states)
    assert passed is False
    assert "phylum" in reason


def test_write_term_states_tsv_round_trips(tmp_path):
    states = [ts.TermState("occurrenceID", "Filled", "term_mapping.tsv:sample_id")]
    out_path = tmp_path / "term_states.tsv"
    ts.write_term_states_tsv(states, out_path)
    lines = out_path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "term\tstate\tevidence"
    assert lines[1] == "occurrenceID\tFilled\tterm_mapping.tsv:sample_id"


def test_write_term_states_tsv_sanitizes_a_tab_or_newline_in_evidence(tmp_path):
    states = [ts.TermState("phylum", "Ask", "INPUT_INCOMPLETE:\tno rank columns\nsupplied")]
    out_path = tmp_path / "term_states.tsv"
    ts.write_term_states_tsv(states, out_path)
    lines = out_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert lines[1].count("\t") == 2


def test_filled_terms_names_the_source_column_a_mapping_row_gives():
    filled = _filled([MappingProposal("sample_id", "occurrenceID", "exact")])
    assert filled == {"occurrenceID": "term_mapping.tsv:sample_id"}


def test_filled_terms_skips_a_mapping_row_with_no_real_target():
    filled = _filled(
        [MappingProposal("notes", "", "unmapped"), MappingProposal("x", "dynamicProperties", "")]
    )
    assert filled == {}


def test_filled_terms_names_a_constant_by_its_provenance_tag():
    filled = _filled(
        [
            MappingProposal(
                map_terms.CONSTANT_SOURCE_COLUMN, "waterBody", "constant", "document:methods.pdf"
            )
        ]
    )
    assert filled == {"waterBody": "constant:document:methods.pdf"}


def test_filled_terms_covers_a_term_no_mapping_row_names():
    filled = _filled([], [{"basisOfRecord": "MaterialSample"}])
    assert filled == {"basisOfRecord": "default:MaterialSample"}


def test_filled_terms_does_not_call_a_value_a_default_it_does_not_equal():
    filled = _filled([], [{"geodeticDatum": "NAD83"}])
    assert filled == {"geodeticDatum": ts.MAPPED_TABLE_EVIDENCE}


def test_filled_terms_does_not_call_a_term_a_default_when_only_some_rows_hold_it():
    filled = _filled([], [{"basisOfRecord": "MaterialSample"}, {"basisOfRecord": "Event"}])
    assert filled == {"basisOfRecord": ts.MAPPED_TABLE_EVIDENCE}


def test_filled_terms_ignores_a_column_blank_on_every_row():
    filled = _filled([], [{"phylum": ""}, {"phylum": ""}])
    assert filled == {}


def test_filled_terms_prefers_the_mapping_row_over_the_observed_value():
    filled = _filled(
        [MappingProposal("record_basis", "basisOfRecord", "alias")],
        [{"basisOfRecord": "MaterialSample"}],
    )
    assert filled == {"basisOfRecord": "term_mapping.tsv:record_basis"}


def test_filled_terms_leaves_out_a_mapped_term_blank_on_every_row():
    filled = _filled(
        [MappingProposal("phylum_name", "phylum", "exact")], [{"phylum": ""}, {"phylum": ""}]
    )
    assert filled == {}


def test_classify_term_states_asks_about_a_mapped_term_blank_on_every_row():
    proposals = [MappingProposal("phylum_name", "phylum", "exact")]
    states = ts.classify_term_states(
        ["phylum"],
        filled_terms=_filled(proposals, [{"phylum": ""}]),
        mapped_columns=["phylum"],
    )
    assert states[0] == ts.TermState(
        "phylum", "Ask", ts.BLANK_COLUMN_EVIDENCE.format(term="phylum")
    )


def test_classify_term_states_asks_about_a_term_no_column_can_supply():
    states = ts.classify_term_states(["scientificName"], mapped_columns=["occurrenceID"])
    assert states[0].state == "Ask"
    assert states[0].evidence == ts.ABSENT_COLUMN_EVIDENCE.format(term="scientificName")


def test_classify_term_states_asks_about_a_column_blank_on_every_row():
    states = ts.classify_term_states(["phylum"], mapped_columns=["phylum"])
    assert states[0].state == "Ask"
    assert states[0].evidence == ts.BLANK_COLUMN_EVIDENCE.format(term="phylum")


def test_classify_term_states_leaves_the_qpcr_block_not_applicable_when_the_header_is_known():
    states = ts.classify_term_states(["probeReporter"], mapped_columns=[])
    assert states[0].state == "Not-applicable"
    assert states[0].evidence == ts.METABARCODING_NOT_APPLICABLE_REASON


def test_classify_term_states_prefers_a_human_impossible_to_a_derived_ask():
    states = ts.classify_term_states(
        ["phylum"], impossible_terms={"phylum": "no lineage in any input"}, mapped_columns=[]
    )
    assert states[0].state == "Impossible"
    assert states[0].evidence == "no lineage in any input"


def test_classify_term_states_prefers_a_human_ask_to_a_derived_one():
    states = ts.classify_term_states(
        ["phylum"], ask_terms={"phylum": "decision:marker_targets"}, mapped_columns=[]
    )
    assert states[0].state == "Ask"
    assert states[0].evidence == "decision:marker_targets"


def test_classify_term_states_derives_no_ask_for_a_filled_term():
    states = ts.classify_term_states(
        ["phylum"], filled_terms={"phylum": "term_mapping.tsv:phylum_name"}, mapped_columns=[]
    )
    assert states[0].state == "Filled"


STEP_TERM_TABLE = {
    "occurrenceID": {"priority_tier": "required", "tier": "required"},
    "basisOfRecord": {"priority_tier": "required", "tier": "required"},
    "scientificName": {"priority_tier": "required", "tier": "required"},
    "phylum": {"priority_tier": "recommended"},
    "probeReporter": {"priority_tier": "strongly_recommended"},
}

MAPPING = [
    MappingProposal("occurrenceID", "occurrenceID", "exact"),
    MappingProposal("species_name", "scientificName", "exact"),
]

MAPPED_ROWS = [{"occurrenceID": "occ-1", "scientificName": "Calanus finmarchicus", "phylum": ""}]


def _stated(proposals=MAPPING, rows=None, **judgments):
    table = table_of(rows) if rows is not None else None
    states, log = ts.state_terms(STEP_TERM_TABLE, proposals, table, **judgments)
    return log, [f"{s.term}\t{s.state}\t{s.evidence}" for s in states]


def test_state_terms_gives_filled_terms_their_mapping_evidence():
    _, lines = _stated()
    assert "occurrenceID\tFilled\tterm_mapping.tsv:occurrenceID" in lines
    assert "scientificName\tFilled\tterm_mapping.tsv:species_name" in lines


def test_state_terms_states_a_term_only_the_occurrence_table_records():
    _, lines = _stated(rows=[{"occurrenceID": "occ-1", "basisOfRecord": "MaterialSample"}])
    assert "basisOfRecord\tFilled\tdefault:MaterialSample" in lines


def test_state_terms_marks_the_qpcr_block_not_applicable_for_metabarcoding():
    _, lines = _stated()
    assert any(line.startswith("probeReporter\tNot-applicable") for line in lines)


@pytest.mark.parametrize(
    ("judgment", "state"),
    [("ask", "Ask"), ("impossible", "Impossible"), ("not_applicable", "Not-applicable")],
)
def test_state_terms_states_a_term_a_person_judged_with_their_reason(judgment, state):
    _, lines = _stated(**{judgment: {"phylum": "the reason"}})
    assert f"phylum\t{state}\tthe reason" in lines


def test_state_terms_reports_a_term_with_no_state():
    log, _ = _stated(proposals=[MappingProposal("occurrenceID", "occurrenceID", "exact")])
    (finding,) = log.findings
    assert finding.code == "TERM_STATE_MISSING"
    assert "scientificName" in finding.message


def test_state_terms_asks_about_a_term_the_mapped_table_cannot_supply():
    log, lines = _stated(rows=MAPPED_ROWS)
    absent = ts.ABSENT_COLUMN_EVIDENCE.format(term="basisOfRecord")
    blank = ts.BLANK_COLUMN_EVIDENCE.format(term="phylum")
    assert f"basisOfRecord\tAsk\t{absent}" in lines
    assert f"phylum\tAsk\t{blank}" in lines
    assert log.findings == []


@pytest.mark.parametrize("judgment", ["not_applicable", "impossible"])
@pytest.mark.parametrize("term", ["occurrenceID", "basisOfRecord", "scientificName"])
def test_state_terms_refuses_to_excuse_a_term_the_archive_requires(judgment, term):
    with pytest.raises(ts.TermSpecError) as error:
        _stated(**{judgment: {term: "no reason"}})
    assert term in str(error.value)
    assert f"term_states.{judgment}" in str(error.value)
