from __future__ import annotations

import json

import pytest

from edna2dwc.cli.common import CommandLineError
from edna2dwc.common import findings


def test_findings_lists_every_code_with_its_severity_and_meaning(run_cli):
    text = run_cli(["findings"]).render()
    assert all(f"`{code}`" in text for code in findings.CODES)
    (line,) = [line for line in text.splitlines() if "`TAXON_FUZZY_REJECTED`" in line]
    assert "warning" in line


def test_findings_explains_the_codes_it_is_given(run_cli):
    text = run_cli(["findings", "CONTRACT_INVALID", "GBIF_VALIDATOR_ISSUE"]).render()
    assert text.splitlines() == [
        f"CONTRACT_INVALID (error): {findings.meaning('CONTRACT_INVALID')}",
        f"GBIF_VALIDATOR_ISSUE (varies): {findings.meaning('GBIF_VALIDATOR_ISSUE')}",
    ]


def test_findings_names_a_code_it_does_not_know(run_cli):
    with pytest.raises(CommandLineError, match="NOT_A_CODE"):
        run_cli(["findings", "NOT_A_CODE"])


def test_findings_json_gives_each_code_as_an_object(run_cli):
    body = json.loads(run_cli(["findings", "CONTRACT_INVALID", "--json"]).render())
    assert body == [
        {
            "code": "CONTRACT_INVALID",
            "severity": "error",
            "meaning": findings.meaning("CONTRACT_INVALID"),
        }
    ]
