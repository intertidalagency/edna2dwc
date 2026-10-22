from __future__ import annotations

from edna2dwc.build.result import BuildResult
from edna2dwc.build.sheets import CONTROL_ROSTER, TAXA, SheetReview
from edna2dwc.conversion import stages
from edna2dwc.review import review_page


def test_the_page_lists_what_waits_and_how_to_continue(tmp_path):
    result = BuildResult(
        "needs_review",
        "proposed/control_roster.tsv: 1 sample(s) classified as control",
        archive_dir=tmp_path,
        sheets=[SheetReview(CONTROL_ROSTER, "1 sample(s) classified as control", confirmed=False)],
    )
    assert "control_roster" in [item.title.split(":")[0] for item in result.waiting]
    assert "edna2dwc build" in review_page.render_markdown(result)


def test_an_unconfirmed_answer_is_listed_as_accepted_to_confirm_under_automatic(tmp_path):
    result = BuildResult(
        "ok", "", archive_dir=tmp_path, unconfirmed=["constants.sop"], automatic=True
    )
    markdown = review_page.render_markdown(result)
    assert "--automatic" in markdown.split("## Done")[0]


def test_the_headline_never_says_finished_while_an_item_waits(tmp_path):
    result = BuildResult("ok", "", archive_dir=tmp_path, blank_metadata=["title"], automatic=True)
    markdown = review_page.render_markdown(result)
    assert "metadata.title" in markdown
    assert review_page.STATUS_SENTENCES["ok"] not in markdown


def test_the_headline_says_finished_when_nothing_waits(tmp_path):
    result = BuildResult("ok", "", archive_dir=tmp_path)
    markdown = review_page.render_markdown(result)
    assert review_page.STATUS_SENTENCES["ok"] in markdown


def _page(result: BuildResult) -> str:
    return review_page.render_markdown(result)


def test_the_page_ticks_every_stage_before_convert(tmp_path):
    page = _page(BuildResult("needs_decision", "metadata.title"))
    assert "- [x] Stage 3 of 5: Read (" in page
    assert "- [ ] **Now:** Stage 4 of 5: Convert (" in page
    assert "- [ ] Stage 5 of 5: Check (" in page


def test_at_check_the_page_ticks_convert_even_with_items_waiting(tmp_path):
    result = BuildResult(
        "needs_review", "", archive_dir=tmp_path, blank_metadata=["license"], stage=stages.CHECK
    )
    page = _page(result)
    assert "- [x] Stage 4 of 5: Convert (" in page
    assert "- [ ] **Now:** Stage 5 of 5: Check (" in page


def test_a_build_stopped_on_an_error_waits_on_that_error(tmp_path):
    result = BuildResult("error", "BUNDLE_ARTIFACT_MISSING: absent.xlsx does not exist")
    assert any("absent.xlsx" in item.detail for item in result.waiting)
    assert "Nothing." not in review_page.render_markdown(result)


def test_automatic_lists_a_proposal_it_used_under_accepted_to_confirm(tmp_path):
    result = BuildResult(
        "ok",
        "",
        archive_dir=tmp_path,
        sheets=[SheetReview(TAXA, "7 distinct lineage(s) resolved", confirmed=False)],
        automatic=True,
    )
    assert "## Accepted by --automatic, confirm" in review_page.render_markdown(result)
