from pathlib import Path

import pytest

from edna2dwc.conversion.provenance import (
    Answer,
    AnswerError,
    SheetRefused,
    parse_answer,
    refuse_unprovenanced,
    unconfirmed_answers,
)


def test_parse_answer_reads_value_provenance_and_confirmed():
    entry = {"value": "2026", "provenance": "methods.pdf p. 1", "confirmed": "PI: yes"}
    assert parse_answer(entry, "metadata.pub_date") == Answer(
        "2026", "methods.pdf p. 1", "PI: yes"
    )


def test_parse_answer_refuses_an_answer_without_provenance():
    with pytest.raises(AnswerError, match=r"metadata\.title needs provenance:"):
        parse_answer({"value": "Kelp", "confirmed": ""}, "metadata.title")


def test_parse_answer_refuses_an_unknown_key():
    entry = {"value": "Kelp", "provenance": "PI", "override": "user:PI"}
    with pytest.raises(AnswerError, match="unknown key"):
        parse_answer(entry, "metadata.title")


def test_parse_answer_reads_a_term_state_reason_without_a_value():
    answer = parse_answer({"provenance": "no PCR profile given"}, "term_states", value_key=None)
    assert answer == Answer(None, "no PCR profile given")


def test_parse_answer_reads_a_marker_target():
    entry = {"target": "vertebrates", "provenance": "MiFish primers"}
    assert parse_answer(entry, "markers.12S", value_key="target").value == "vertebrates"


def test_whitespace_in_confirmed_leaves_the_answer_unconfirmed():
    answer = parse_answer({"value": "x", "provenance": "PI", "confirmed": "   "}, "constants.x")
    assert answer.unconfirmed


def test_a_skeleton_placeholder_with_no_provenance_is_unanswered_not_unconfirmed():
    raw = {"metadata": {"abstract": {"value": "", "provenance": "", "confirmed": ""}}}
    assert unconfirmed_answers(raw) == []


def test_unconfirmed_answers_walks_nested_sections_and_marker_constants():
    raw = {
        "metadata": {"title": {"value": "Kelp", "provenance": "PI", "confirmed": "PI: yes"}},
        "markers": {
            "12S": {
                "target": "vertebrates",
                "provenance": "MiFish primers",
                "constants": {"sop": {"value": "x", "provenance": "methods.pdf"}},
            }
        },
    }
    assert unconfirmed_answers(raw) == ["markers.12S", "markers.12S.constants.sop"]


def test_refuse_unprovenanced_names_the_rows_and_caps_the_list():
    rows = [f"row{i}" for i in range(12)]
    with pytest.raises(SheetRefused) as refused:
        refuse_unprovenanced(Path("confirmed") / "term_mapping.tsv", rows)
    message = str(refused.value)
    assert "12 row(s)" in message
    assert "row9" in message
    assert "row10" not in message
    assert "and 2 more" in message


def test_refuse_unprovenanced_passes_when_every_row_has_provenance():
    refuse_unprovenanced(Path("term_mapping.tsv"), [])


@pytest.mark.parametrize(
    "confirmed",
    ["automatic", "data", "agent", "yes", "ok", "  Automatic. ", "YES!", True],
)
def test_a_confirmation_no_person_wrote_is_refused_and_told_where_it_belongs(confirmed):
    entry = {"value": "2026", "provenance": "methods.pdf", "confirmed": confirmed}
    with pytest.raises(AnswerError) as refused:
        parse_answer(entry, "metadata.pub_date")
    assert "metadata.pub_date" in str(refused.value)
    assert "build --automatic" in str(refused.value)


@pytest.mark.parametrize(
    "confirmed",
    [
        "PI: yes",
        "J. Smith: the sites are intertidal",
        "Yes, per J. Smith",
        "Data manager K. Lee: keep",
        "No, S3 is a sample (PI)",
        "",
    ],
)
def test_a_persons_reply_or_nothing_is_accepted(confirmed):
    entry = {"value": "2026", "provenance": "methods.pdf", "confirmed": confirmed}
    assert parse_answer(entry, "metadata.pub_date").confirmed == confirmed
