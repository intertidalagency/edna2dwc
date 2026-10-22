from __future__ import annotations

import pytest

from edna2dwc.cli import app
from edna2dwc.cli.groups import INGEST, PIPELINE, SETUP, VERBS
from tests.cli_commands import flags_by_command

BOX_CHARACTERS = "╭╮╰╯│─"
ROOT_EXAMPLE = "edna2dwc inspect data/"


def help_text(capsys, argv: list[str]) -> str:
    with pytest.raises(SystemExit):
        app(argv, exit_on_error=False)
    return capsys.readouterr().out


def visible_group_titles() -> list[str]:
    return [group.name for group in PIPELINE if group.show]


def test_root_help_draws_no_boxes(capsys):
    text = help_text(capsys, ["--help"])
    assert not set(text) & set(BOX_CHARACTERS)


def test_root_help_leads_with_the_verbs_and_demotes_the_rest(capsys):
    text = help_text(capsys, ["--help"])
    verbs = text.index(VERBS.name)
    assert verbs < text.index(SETUP.name) < text.index(INGEST.name)
    verbs_block = text[verbs:].split("\n\n", 1)[0]
    assert all(verb in verbs_block for verb in ("inspect", "resolve-taxonomy", "build"))


@pytest.mark.parametrize("argv", [["--help"], ["build", "--help"]])
def test_help_names_the_audit_record_among_builds_inputs(capsys, argv):
    assert "audit_record.json" in help_text(capsys, argv)


def test_root_help_names_each_group_once(capsys):
    text = help_text(capsys, ["--help"])
    for title in visible_group_titles():
        assert text.count(f"{title}:") == 1, title


def test_root_help_leads_with_examples_and_ends_with_where_to_go_next(capsys):
    text = help_text(capsys, ["--help"])
    assert text.index("Usage:") < text.index(ROOT_EXAMPLE) < text.index(VERBS.name)
    assert "edna2dwc <command> --help" in text
    assert "https://github.com/intertidalagency/edna2dwc" in text
    assert "`" not in text


def test_root_help_folds_help_version_and_quiet_into_one_options_section(capsys):
    text = help_text(capsys, ["--help"])
    assert text.count("Options:") == 1
    assert "-h, --help" in text
    assert "--version" in text
    assert "--quiet" in text
    assert "[default: False]" not in text


def test_subcommand_help_is_flat_and_keeps_the_pointer_to_the_root_out(capsys):
    text = help_text(capsys, ["record-step", "--help"])
    assert not set(text) & set(BOX_CHARACTERS)
    assert "--config" in text
    assert "--raw" in text
    assert "edna2dwc <command> --help" not in text
    assert ROOT_EXAMPLE not in text


TYPE_INTERNALS = ("ANNOTATED[", "PARAMETER(", "VALIDATOR", "TUPLE[", "ELLIPSIS")


@pytest.mark.parametrize("command", sorted(flags_by_command()))
def test_no_usage_line_shows_python_type_internals(capsys, command):
    usage = help_text(capsys, [*command.split(), "--help"]).split("\n\n", 1)[0]
    assert not [internal for internal in TYPE_INTERNALS if internal in usage], usage
