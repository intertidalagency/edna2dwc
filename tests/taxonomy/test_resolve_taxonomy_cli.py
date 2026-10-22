from __future__ import annotations

import json
from pathlib import Path

import pytest

from edna2dwc.cli.common import CommandFailed, UsageError
from edna2dwc.cli.taxonomy import _misalignment_advice, _outage_advice
from edna2dwc.conversion import artifacts
from edna2dwc.taxonomy import api_usage
from edna2dwc.taxonomy.gbif import GbifClient, GbifError
from edna2dwc.taxonomy.worms import WormsBatchAlignmentError, WormsClient, WormsError
from tests.taxonomy.conversion_dir import (
    AAPTOS_ROW,
    set_taxonomy_policy,
    write_intermediate,
)

pytestmark = pytest.mark.usefixtures("conversion_dir", "mock_registers")


@pytest.fixture(autouse=True)
def _reset_api_usage():
    api_usage.reset()
    yield
    api_usage.reset()


def test_resolve_taxonomy_writes_the_lock_build_reads(run_cli):
    result = run_cli(["resolve-taxonomy"])
    assert result.exit_code == 0, result.render()
    assert "urn:lsid:marinespecies.org:taxname:132064" in artifacts.RESOLVED_TAXONOMY.read_text()


def test_resolve_taxonomy_output_writes_a_trial_file_instead(run_cli):
    result = run_cli(["resolve-taxonomy", "-o", "trial.tsv"])
    assert result.exit_code == 0, result.render()
    assert Path("trial.tsv").exists()
    assert not artifacts.RESOLVED_TAXONOMY.exists()


def test_resolve_taxonomy_needs_answers_yaml(run_cli):
    artifacts.ANSWERS.unlink()
    with pytest.raises(UsageError, match="answers.yaml"):
        run_cli(["resolve-taxonomy"])


def test_resolve_taxonomy_needs_the_intermediate_table(run_cli):
    artifacts.INTERMEDIATE.unlink()
    with pytest.raises(UsageError, match="occurrence_long.tsv"):
        run_cli(["resolve-taxonomy"])


def test_resolve_taxonomy_rejects_a_comma_separated_intermediate_table(run_cli):
    artifacts.INTERMEDIATE.write_text("sampleID,featureID,count,taxonomy\nS1,f1,3,g__Aaptos\n")
    with pytest.raises(UsageError, match="must be tab-separated"):
        run_cli(["resolve-taxonomy"])


def test_resolve_taxonomy_reads_a_table_whose_values_hold_commas(run_cli):
    comma_heavy_value = json.dumps({key: "1" for key in "abcdefg"})
    write_intermediate(
        [
            {**AAPTOS_ROW, "sampleID": f"S{i}", "dynamicProperties": comma_heavy_value}
            for i in range(5)
        ]
    )
    result = run_cli(["resolve-taxonomy"])
    assert result.exit_code == 0, result.render()
    assert len(artifacts.RESOLVED_TAXONOMY.read_text().splitlines()) == 2


def test_resolving_saves_what_the_registers_answered_to_the_cache(run_cli, mock_registers):
    run_cli(["resolve-taxonomy"])
    assert (mock_registers / "taxonomy" / "worms_match_cache.json").exists()


def test_refresh_neither_reads_nor_writes_the_cache(run_cli, mock_registers):
    run_cli(["resolve-taxonomy", "--refresh"])
    assert not (mock_registers / "taxonomy").exists()


def test_resolve_taxonomy_reports_a_register_outage_as_a_failed_command(run_cli, monkeypatch):
    def outage(*args, **kwargs):
        raise WormsError("3 WoRMS batches failed, treating this as a register outage")

    monkeypatch.setattr(WormsClient, "match_names", outage)
    with pytest.raises(CommandFailed) as raised:
        run_cli(["resolve-taxonomy"])

    assert str(raised.value) == (
        "3 WoRMS batches failed, treating this as a register outage. "
        "Rerun `edna2dwc resolve-taxonomy` to resume: every name the register did answer "
        "is in the on-disk match cache, so the rerun asks only for the rest"
    )


def test_resolve_taxonomy_reports_a_gbif_outage_the_same_way(run_cli, monkeypatch):
    def outage(*args, **kwargs):
        raise GbifError("GBIF request failed after 4 attempts")

    set_taxonomy_policy(registers=["worms", "gbif"])
    monkeypatch.setattr(GbifClient, "match", outage)
    monkeypatch.setattr(
        WormsClient, "match_names", lambda self, names, **kwargs: {n: [] for n in names}
    )
    with pytest.raises(CommandFailed) as raised:
        run_cli(["resolve-taxonomy"])

    assert str(raised.value) == (
        "GBIF request failed after 4 attempts. "
        "Rerun `edna2dwc resolve-taxonomy` to resume: every name the register did answer "
        "is in the on-disk match cache, so the rerun asks only for the rest"
    )


def test_a_register_outage_under_refresh_points_at_a_live_retry(run_cli, monkeypatch):
    def outage(*args, **kwargs):
        raise WormsError("WoRMS request failed after 4 attempts")

    monkeypatch.setattr(WormsClient, "match_names", outage)
    with pytest.raises(CommandFailed) as raised:
        run_cli(["resolve-taxonomy", "--refresh"])

    assert str(raised.value) == (
        "WoRMS request failed after 4 attempts. "
        "--refresh kept nothing this pass looked up, so retry live with "
        "`edna2dwc resolve-taxonomy --refresh`; rerunning it without --refresh runs "
        "against what is already in the cache"
    )


def test_a_batch_alignment_refusal_does_not_promise_a_rerun_will_get_past_it(run_cli, monkeypatch):
    def misaligned(*args, **kwargs):
        raise WormsBatchAlignmentError(
            "WoRMS returned 1 result(s) for a 2-name batch, refusing to guess alignment"
        )

    monkeypatch.setattr(WormsClient, "match_names", misaligned)
    with pytest.raises(CommandFailed) as raised:
        run_cli(["resolve-taxonomy"])

    message = str(raised.value)
    assert message.endswith(_misalignment_advice())
    assert _outage_advice(cache_bypassed=False) not in message


def test_a_label_refresh_outage_discloses_rather_than_discarding_the_finished_pass(
    run_cli, monkeypatch
):
    def outage(*args, **kwargs):
        raise WormsError("WoRMS request failed after 4 attempts")

    monkeypatch.setattr(WormsClient, "current_record_by_aphia_id", outage)
    set_taxonomy_policy(refresh_labels=True)
    result = run_cli(["resolve-taxonomy", "--json"])

    assert result.exit_code == 0, result.render()
    assert "Aaptos" in artifacts.RESOLVED_TAXONOMY.read_text()
    codes = [f["code"] for f in json.loads(result.render())["findings"]]
    assert "TAXON_LABEL_REFRESH_INCOMPLETE" in codes
