from __future__ import annotations

from edna2dwc.build.derive_fields import PROPOSED_SAMPLES
from edna2dwc.build.questions import MissingAnswer
from edna2dwc.build.result import ACCEPTED, DONE, NOT_REACHED, WAITING, BuildResult, ReviewItem
from edna2dwc.build.sheets import (
    CONTROL_ROSTER,
    DERIVED_VALUES,
    LISTED_ROWS,
    TAXA,
    TERM_MAPPING,
    RowsChanged,
    SheetReview,
)
from edna2dwc.conversion import stages


def _items(result: BuildResult) -> dict[str, ReviewItem]:
    return {item.title.split(":")[0]: item for item in result.items}


def test_a_missing_answer_names_the_key_to_set():
    result = BuildResult(
        "needs_decision",
        "markers.12S",
        missing_answers=[MissingAnswer("markers.12S", "What does it amplify?", "{target: x}")],
    )
    item = _items(result)["markers.12S"]
    assert item.status == WAITING
    assert all(fact in item.how for fact in ("markers.12S", "answers.yaml", "{target: x}"))


def test_a_halt_before_the_proposals_shows_them_not_reached():
    items = _items(BuildResult("needs_decision", "metadata.title"))
    assert {
        items[sheet].status
        for sheet in ("control_roster", "term_mapping", "taxa", "derived_values")
    } == {NOT_REACHED}


def test_an_open_proposal_says_how_to_confirm_it(tmp_path):
    result = BuildResult(
        "needs_review",
        "",
        archive_dir=tmp_path,
        sheets=[SheetReview(TERM_MAPPING, "1 ambiguous mapping(s)", confirmed=False)],
    )
    item = _items(result)["term_mapping"]
    assert item.status == WAITING
    assert "confirmed/term_mapping.tsv" in item.how
    assert "proposed/term_mapping.tsv" in item.how


def test_an_open_control_roster_is_closed_by_answers_not_a_confirmed_sheet(tmp_path):
    result = BuildResult(
        "needs_review",
        "",
        archive_dir=tmp_path,
        sheets=[SheetReview(CONTROL_ROSTER, "1 sample(s) excluded: Blank1", confirmed=False)],
    )
    item = _items(result)["control_roster"]
    assert item.status == WAITING
    assert "controls:" in item.how
    assert "answers.yaml" in item.how
    assert "confirmed/" not in item.how


def test_a_confirmed_sheet_or_a_quiet_proposal_is_done(tmp_path):
    result = BuildResult(
        "ok",
        "",
        archive_dir=tmp_path,
        sheets=[
            SheetReview(TERM_MAPPING, "1 ambiguous mapping(s)", confirmed=True),
            SheetReview(CONTROL_ROSTER, "", confirmed=False),
        ],
    )
    items = _items(result)
    assert items["term_mapping"].status == items["control_roster"].status == DONE
    assert "confirmed/term_mapping.tsv" in items["term_mapping"].detail


def test_a_confirmed_sheet_counts_its_changed_rows_and_the_unconfirmed_ones(tmp_path):
    rows = RowsChanged(changed=3, unconfirmed=1, first_unconfirmed=["S2/f1"])
    review = SheetReview(DERIVED_VALUES, "", confirmed=True, rows=rows)
    result = BuildResult("ok", "", archive_dir=tmp_path, sheets=[review])
    item = _items(result)["derived_values"]
    assert item.status == DONE
    assert item.detail.endswith("3 row(s) changed, 1 not confirmed")


def test_a_blank_required_field_waits_even_under_automatic(tmp_path):
    result = BuildResult(
        "needs_review", "", archive_dir=tmp_path, blank_metadata=["title"], automatic=True
    )
    item = _items(result)["metadata.title"]
    assert item.status == WAITING
    assert "Blank" in item.detail
    assert "metadata.title" in item.how


def test_an_unconfirmed_answer_waits_for_a_person(tmp_path):
    result = BuildResult(
        "needs_review", "", archive_dir=tmp_path, unconfirmed=["metadata.pub_date"]
    )
    item = _items(result)["metadata"]
    assert item.status == WAITING
    assert "`metadata.pub_date`" in item.detail
    assert "no person has confirmed" in item.detail
    assert "`confirmed` field in `answers.yaml`" in item.how


def test_unconfirmed_answers_are_grouped_by_section_and_the_list_is_capped(tmp_path):
    keys = [f"term_states.impossible.term{n}" for n in range(12)] + ["markers.16S"]
    result = BuildResult("needs_review", "", archive_dir=tmp_path, unconfirmed=keys)
    items = _items(result)
    assert "12 answer(s)" in items["term_states.impossible"].detail
    assert "and 2 more" in items["term_states.impossible"].detail
    assert "1 answer(s)" in items["markers"].detail


def test_derived_values_say_how_to_correct_a_sample_after_the_proposed_ones(tmp_path):
    review = SheetReview(DERIVED_VALUES, "a coordinate sign looks wrong", confirmed=False)
    result = BuildResult("needs_review", "", archive_dir=tmp_path, sheets=[review])
    how = _items(result)["derived_values"].how
    assert "`provenance`" in how
    assert "`confirmed`" in how
    assert str(PROPOSED_SAMPLES) in how


def test_an_unconfirmed_sheet_row_points_at_its_confirmed_column(tmp_path):
    rows = RowsChanged(changed=1, unconfirmed=1, first_unconfirmed=["S1/f1"])
    review = SheetReview(DERIVED_VALUES, "", confirmed=True, rows=rows)
    result = BuildResult("needs_review", "", archive_dir=tmp_path, sheets=[review])
    item = _items(result)["confirmed/derived_values.tsv"]
    assert "1 answer(s) no person has confirmed: `S1/f1`" in item.detail
    assert "`confirmed` column of `confirmed/derived_values.tsv`" in item.how


def test_a_sheet_with_many_unconfirmed_rows_names_the_first_and_counts_the_rest(tmp_path):
    first = [f"S{n}/f1" for n in range(LISTED_ROWS)]
    rows = RowsChanged(changed=300_000, unconfirmed=300_000, first_unconfirmed=first)
    review = SheetReview(DERIVED_VALUES, "", confirmed=True, rows=rows)
    result = BuildResult("needs_review", "", archive_dir=tmp_path, sheets=[review])
    item = _items(result)["confirmed/derived_values.tsv"]
    assert item.detail.startswith("300000 answer(s) no person has confirmed: `S0/f1`")
    assert "and 299990 more" in item.detail
    assert result.unconfirmed_count == 300_000
    assert "answers.yaml" not in item.how


def test_an_open_mapping_asks_for_provenance_and_a_reply_on_each_row_changed(tmp_path):
    review = SheetReview(TERM_MAPPING, "1 ambiguous mapping(s)", confirmed=False)
    result = BuildResult("needs_review", "", archive_dir=tmp_path, sheets=[review])
    how = _items(result)["term_mapping"].how
    assert "`provenance`" in how
    assert "`confirmed`" in how


def test_an_open_mapping_says_what_each_target_does(tmp_path):
    review = SheetReview(TERM_MAPPING, "1 ambiguous mapping(s)", confirmed=False)
    result = BuildResult("needs_review", "", archive_dir=tmp_path, sheets=[review])
    how = _items(result)["term_mapping"].how
    assert "`extendedmeasurementorfact`" in how
    assert "`dynamicProperties`" in how
    assert "basis `internal`" in how


def test_a_required_field_left_out_names_the_eml_element_it_leaves_out(tmp_path):
    result = BuildResult(
        "needs_review",
        "",
        archive_dir=tmp_path,
        blank_metadata=["title"],
        missing_eml_elements=["title"],
    )
    item = _items(result)["metadata.title"]
    assert "`<title>`" in item.detail
    assert "GBIF" in item.detail


def test_with_nothing_waiting_at_convert_the_next_action_starts_check_with_the_audit(tmp_path):
    result = BuildResult("ok", "", archive_dir=tmp_path)
    assert result.next_step.startswith("Stage 5, Check: audit the archive")


def test_with_nothing_waiting_at_check_the_next_action_is_evaluate(tmp_path):
    result = BuildResult("ok", "", archive_dir=tmp_path, stage=stages.CHECK)
    assert result.next_step.startswith("`edna2dwc evaluate")


def test_a_validator_issue_to_adjudicate_waits_with_the_line_that_accepts_it(tmp_path):
    line = "ON_LAND: {status: accepted, provenance: <who and why>}"
    result = BuildResult(
        "needs_review",
        "",
        archive_dir=tmp_path,
        adjudications_needed=[f"OBIS ON_LAND: 19 record(s). To accept it, add {line}"],
    )
    (item,) = [i for i in result.waiting if i.kind == "adjudication"]
    assert line in item.detail
    assert "adjudications:" in item.how


def test_a_build_stopped_on_an_error_points_next_at_the_error(tmp_path):
    result = BuildResult("error", "a step failed")
    assert result.next_step == "fix the error above, then `edna2dwc build`"


def test_an_unconfirmed_answer_says_to_leave_confirmed_empty_with_nobody_to_ask(tmp_path):
    result = BuildResult(
        "needs_review", "", archive_dir=tmp_path, unconfirmed=["metadata.pub_date"]
    )
    item = _items(result)["metadata"]
    assert "nobody to ask" in item.how
    assert "build --automatic" in item.how
    assert "never write it yourself" in item.how


def test_with_items_waiting_the_next_action_counts_them_in_the_page(tmp_path):
    result = BuildResult("needs_review", "", archive_dir=tmp_path, blank_metadata=["license"])
    assert result.next_step == (
        'close the 1 item(s) under "Waiting on you" in REVIEW.md, then `edna2dwc build`'
    )


def test_an_unconfirmed_answer_is_accepted_to_confirm_under_automatic(tmp_path):
    result = BuildResult(
        "ok", "", archive_dir=tmp_path, unconfirmed=["constants.sop"], automatic=True
    )
    item = _items(result)["constants"]
    assert item.status == ACCEPTED
    assert "--automatic" in item.detail


def test_automatic_accepts_a_proposal_it_used_and_says_how_to_confirm_it(tmp_path):
    result = BuildResult(
        "ok",
        "",
        archive_dir=tmp_path,
        sheets=[SheetReview(TAXA, "7 distinct lineage(s) resolved", confirmed=False)],
        automatic=True,
    )
    item = _items(result)["taxa"]
    assert item.status == ACCEPTED
    assert "7 distinct lineage(s) resolved" in item.detail
    assert "confirmed/taxa.tsv" in item.how
