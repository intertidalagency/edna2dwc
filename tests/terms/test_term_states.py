
TERM_TABLE = {
}


    assert ts.b1c_terms(TERM_TABLE) == [
        "occurrenceID",
        "phylum",
        "probeReporter",
        "scientificName",
    ]




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
    out_path = tmp_path / "term_states.tsv"
    ts.write_term_states_tsv(states, out_path)
    lines = out_path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "term\tstate\tevidence"


def test_write_term_states_tsv_sanitizes_a_tab_or_newline_in_evidence(tmp_path):
    states = [ts.TermState("phylum", "Ask", "INPUT_INCOMPLETE:\tno rank columns\nsupplied")]
    out_path = tmp_path / "term_states.tsv"
    ts.write_term_states_tsv(states, out_path)
    lines = out_path.read_text(encoding="utf-8").splitlines()
