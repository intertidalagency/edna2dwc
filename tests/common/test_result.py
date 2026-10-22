from __future__ import annotations

import json

import pytest

from edna2dwc.common.findings import FindingsLog
from edna2dwc.common.result import CommandResult


def _status(log: FindingsLog) -> str:
    return CommandResult.of("test", log).status


@pytest.mark.parametrize(
    ("codes", "status"),
    [
        ([], "ok"),
        (["CONTRACT_INVALID"], "error"),
        (["TAXON_UNRESOLVED", "TAXON_LABEL_STALE"], "ok"),
    ],
)
def test_status_is_error_only_on_an_error_finding(codes, status):
    log = FindingsLog()
    for code in codes:
        log.add(code, "a finding")
    assert _status(log) == status


def test_an_error_finding_only_sets_the_exit_code_for_a_command_that_asked_for_it():
    log = FindingsLog()
    log.add("CONTRACT_INVALID", "bad table")
    assert CommandResult.of("test", log).exit_code == 0
    assert CommandResult.of("test", log, exits_on_error=True).exit_code == 1


def test_render_returns_the_text_without_the_json_flag():
    result = CommandResult.of("test", FindingsLog(), text="done")
    assert result.render() == "done"


def test_render_returns_the_result_keys_under_the_json_flag():
    result = CommandResult.of(
        "test", FindingsLog(), outputs={"occurrence": "o.tsv"}, text="done", as_json=True
    )
    assert json.loads(result.render()) == {
        "command": "test",
        "status": "ok",
        "decision": None,
        "findings": [],
        "outputs": {"occurrence": "o.tsv"},
        "next": None,
    }


def test_extra_keys_are_merged_into_the_reported_json():
    result = CommandResult.of("test", FindingsLog(), extra={"every_term_has_a_state": True})
    assert result.to_json_object()["every_term_has_a_state"] is True


def test_a_json_body_replaces_the_result_keys_entirely():
    result = CommandResult(command="test", json_body=[{"sheet": "control_roster"}], as_json=True)
    assert json.loads(result.render()) == [{"sheet": "control_roster"}]


def test_a_conversion_command_ends_its_text_with_its_stage_and_next_step():
    result = CommandResult.of(
        "assemble", FindingsLog(), text="Wrote 3 row(s)", next_step="resolve"
    )
    assert result.render() == "Wrote 3 row(s)\nStage 3 of 5: Read\nNext: resolve"


def test_a_command_outside_the_stages_renders_its_text_alone():
    result = CommandResult.of("findings", FindingsLog(), text="codes", next_step="read them")
    assert result.render() == "codes"


def test_the_json_names_the_stage_beside_the_next_step():
    result = CommandResult.of("assemble", FindingsLog(), next_step="resolve", as_json=True)
    body = json.loads(result.render())
    assert (body["stage"], body["next"]) == ("Stage 3 of 5: Read", "resolve")


def test_a_command_with_its_own_json_body_still_names_its_stage():
    result = CommandResult(
        command="doctor", json_body={"status": "ok"}, next_step="inspect", as_json=True
    )
    body = json.loads(result.render())
    assert (body["stage"], body["next"]) == ("Stage 1 of 5: Inspect", "inspect")


def test_a_build_names_the_stage_it_reached_rather_than_its_own():
    result = CommandResult(command="build", stage="Describe", next_step="answer", text="Stopped")
    assert result.render() == "Stopped\nStage 2 of 5: Describe\nNext: answer"
