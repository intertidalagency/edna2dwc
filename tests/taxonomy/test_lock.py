from __future__ import annotations

from pathlib import Path

import duckdb
import httpx
import pytest
import yaml

from edna2dwc.common.table import read_tsv
from edna2dwc.common.tsv import read_rows
from edna2dwc.common.version import installed_version
from edna2dwc.conversion import artifacts
from edna2dwc.taxonomy import gbif, lock, worms
from edna2dwc.taxonomy.derive_lineage import derive_lineage
from tests.taxonomy.conversion_dir import (
    AAPTOS_ROW,
    registers_answering,
    set_taxonomy_policy,
    worms_handler,
    write_intermediate,
)

pytestmark = pytest.mark.usefixtures("conversion_dir")


def _resolve(handler=worms_handler, **options):
    return lock.run(open_registers=registers_answering(handler), **options)


def _recorded() -> dict:
    return yaml.safe_load(artifacts.CONFIG.read_text(encoding="utf-8"))


def test_the_lock_has_one_row_per_lineage_of_the_table():
    set_taxonomy_policy(require_confident=False)
    write_intermediate(
        [AAPTOS_ROW, {**AAPTOS_ROW, "featureID": "f2", "taxonomy": "g__Halichondria"}]
    )
    _resolve()
    expected = {
        row["lineage_key"]
        for row in derive_lineage(
            read_tsv(duckdb.connect(), artifacts.INTERMEDIATE, "source")
        ).lineage_rows
    }
    locked = list(read_rows(artifacts.RESOLVED_TAXONOMY, delimiter="\t"))
    assert {row["lineage_key"] for row in locked} == expected
    assert len(expected) == 2
    assert all(row["scientificName"] == "Aaptos" for row in locked)


def test_the_lock_keeps_the_findings_of_each_lineage():
    set_taxonomy_policy(require_confident=False)
    write_intermediate(
        [AAPTOS_ROW, {**AAPTOS_ROW, "featureID": "f2", "taxonomy": "g__Halichondria"}]
    )
    result = _resolve()
    findings = {
        row["scientificName"] if row["findings"] else "": row["findings"]
        for row in read_rows(artifacts.RESOLVED_TAXONOMY, delimiter="\t")
    }
    assert findings == {"": "", "Aaptos": "TAXON_FUZZY"}
    assert [f["code"] for f in result.findings] == ["TAXON_FUZZY"]


def test_the_lock_flags_many_names_that_resolved_to_one_taxon_none_of_them_names():
    set_taxonomy_policy(require_confident=False)
    genera = ["Halichondria", "Micromonas", "Balanus", "Pugettia", "Homo"]
    write_intermediate(
        [
            {**AAPTOS_ROW, "featureID": f"f{i}", "taxonomy": f"g__{genus}"}
            for i, genus in enumerate(genera)
        ]
    )
    result = _resolve()
    locked = list(read_rows(artifacts.RESOLVED_TAXONOMY, delimiter="\t"))
    assert all("TAXON_MASS_COLLAPSE" in row["findings"] for row in locked)
    assert all(row["needs_review"] == "true" for row in locked)
    collapse = next(f for f in result.findings if f["code"] == "TAXON_MASS_COLLAPSE")
    assert collapse["count"] == 5
    assert "confirmed/taxa.tsv" in collapse["message"]


def test_a_marker_with_its_own_settings_resolves_its_rows_under_them():
    raw = yaml.safe_load(artifacts.ANSWERS.read_text(encoding="utf-8"))
    raw["markers"] = {
        "16S": {
            "target": "prokaryotes",
            "provenance": "515F/806R",
            "taxonomy": {"require_confident": True},
        },
        "COI": {
            "target": "animals",
            "provenance": "Leray",
            "taxonomy": {"require_confident": False},
        },
    }
    artifacts.ANSWERS.write_text(yaml.safe_dump(raw), encoding="utf-8")
    write_intermediate(
        [{**AAPTOS_ROW, "marker": "16S"}, {**AAPTOS_ROW, "featureID": "f2", "marker": "COI"}]
    )
    _resolve()
    settings = sorted(
        row["settings"] for row in read_rows(artifacts.RESOLVED_TAXONOMY, delimiter="\t")
    )
    assert len(settings) == 2
    assert "require_confident: false" in settings[0]
    assert "require_confident: true" in settings[1]


def test_resolving_leaves_the_intermediate_table_as_it_was():
    before = artifacts.INTERMEDIATE.read_bytes()
    _resolve()
    assert artifacts.INTERMEDIATE.read_bytes() == before


def test_resolving_records_the_registers_the_date_and_the_tool_version():
    _resolve()
    recorded = _recorded()
    assert recorded["steps"] == []
    assert recorded["resolve_taxonomy"]["registers"] == {"worms": worms.BASE_URL}
    assert recorded["resolve_taxonomy"]["edna2dwc_version"] == installed_version()
    assert recorded["resolve_taxonomy"]["resolved_at"]


def test_the_record_names_gbif_when_the_policy_consults_it():
    set_taxonomy_policy(registers=["worms", "gbif"])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.gbif.org":
            return httpx.Response(200, json={"matchType": "NONE"})
        return worms_handler(request)

    _resolve(handler)
    assert _recorded()["resolve_taxonomy"]["registers"] == {
        "worms": worms.BASE_URL,
        "gbif": gbif.BASE_URL,
    }


def test_a_trial_output_leaves_the_lock_and_its_record_alone():
    _resolve()
    locked = artifacts.RESOLVED_TAXONOMY.read_bytes()
    recorded = _recorded()
    set_taxonomy_policy(terminal_fallback="biota")
    _resolve(output_path=Path("trial.tsv"))
    assert Path("trial.tsv").exists()
    assert artifacts.RESOLVED_TAXONOMY.read_bytes() == locked
    assert _recorded() == recorded


def test_the_policy_in_answers_reaches_the_register():
    set_taxonomy_policy(marine_only=True)
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return worms_handler(request)

    _resolve(handler)
    assert any("marine_only=true" in url for url in urls), urls
