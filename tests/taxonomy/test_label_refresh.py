from __future__ import annotations

from typing import Any

import httpx
import pytest

from edna2dwc.taxonomy import api_usage
from edna2dwc.taxonomy.label_refresh import refresh_labels
from edna2dwc.taxonomy.resolve_taxonomy import ResolvedTaxon
from edna2dwc.taxonomy.worms import WormsClient, WormsError


@pytest.fixture(autouse=True)
def _reset_api_usage():
    api_usage.reset()
    yield
    api_usage.reset()


def _resolved(**overrides) -> ResolvedTaxon:
    base: dict[str, Any] = {
        "lineage_key": "k1",
        "scientific_name": "Incertae sedis",
        "scientific_name_id": "urn:lsid:marinespecies.org:taxname:12",
        "taxon_rank": "Kingdom",
        "scientific_name_authorship": "",
        "taxonomic_status": "unaccepted",
        "aphia_id": "12",
        "taxon_concept_id": "",
        "authority": "worms",
    }
    base.update(overrides)
    return ResolvedTaxon(**base)


def test_only_a_stale_label_is_refreshed_from_current_preferred_record():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "AphiaID": 12,
                "scientificname": "Biota incertae sedis",
                "status": "accepted",
                "kingdom": "Biota incertae sedis",
                "phylum": "",
                "class": "",
                "order": "",
                "family": "",
                "genus": "",
                "match_type": "exact",
            },
        )

    worms = WormsClient(client=httpx.Client(transport=httpx.MockTransport(handler)))
    current = _resolved(
        lineage_key="k2",
        scientific_name="Biota incertae sedis",
        taxonomic_status="accepted",
        kingdom="Biota incertae sedis",
    )
    rows = [_resolved(), current]
    refresh_labels(rows, worms)
    assert rows[0].findings == ["TAXON_LABEL_STALE"]
    assert rows[0].scientific_name == "Biota incertae sedis"
    assert rows[0].taxonomic_status == "accepted"
    assert current.findings == []


def test_one_call_per_distinct_aphia_id_not_per_row():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(
            200,
            json={
                "AphiaID": 12,
                "scientificname": "Biota incertae sedis",
                "status": "accepted",
                "kingdom": "",
                "phylum": "",
                "class": "",
                "order": "",
                "family": "",
                "genus": "",
                "match_type": "exact",
            },
        )

    worms = WormsClient(client=httpx.Client(transport=httpx.MockTransport(handler)))
    rows = [_resolved(lineage_key="k1"), _resolved(lineage_key="k2"), _resolved(lineage_key="k3")]
    refresh_labels(rows, worms)
    assert len(calls) == 1


def test_rows_a_person_changed_are_never_refreshed():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "AphiaID": 12,
                "scientificname": "Something Else",
                "status": "accepted",
                "kingdom": "",
                "phylum": "",
                "class": "",
                "order": "",
                "family": "",
                "genus": "",
                "match_type": "exact",
            },
        )

    worms = WormsClient(client=httpx.Client(transport=httpx.MockTransport(handler)))
    rows = [_resolved(provenance="reviewed on 2026-01-01")]
    refresh_labels(rows, worms)
    assert rows[0].findings == []
    assert rows[0].scientific_name == "Incertae sedis"


def test_reparenting_with_an_unchanged_label_still_triggers_a_refresh():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "AphiaID": 12,
                "scientificname": "Incertae sedis",
                "status": "unaccepted",
                "kingdom": "Biota incertae sedis",
                "phylum": "",
                "class": "",
                "order": "",
                "family": "",
                "genus": "",
                "match_type": "exact",
            },
        )

    worms = WormsClient(client=httpx.Client(transport=httpx.MockTransport(handler)))
    rows = [_resolved(kingdom="")]
    refresh_labels(rows, worms)
    assert rows[0].findings == ["TAXON_LABEL_STALE"]
    assert rows[0].kingdom == "Biota incertae sedis"


def test_gbif_authority_rows_are_not_refreshed_via_worms():
    rows = [_resolved(authority="gbif", aphia_id="999")]
    worms = WormsClient(
        client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    )
    refresh_labels(rows, worms)
    assert rows[0].findings == []


def test_an_outage_part_way_through_leaves_every_row_as_resolution_left_it(monkeypatch):
    monkeypatch.setattr("edna2dwc.taxonomy.register_http.MAX_ATTEMPTS", 1)
    answered = []

    def handler(request):
        answered.append(request.url.path)
        if len(answered) == 1:
            return httpx.Response(
                200,
                json={
                    "AphiaID": 12,
                    "scientificname": "Biota incertae sedis",
                    "status": "accepted",
                    "kingdom": "Biota incertae sedis",
                    "phylum": "",
                    "class": "",
                    "order": "",
                    "family": "",
                    "genus": "",
                    "match_type": "exact",
                },
            )
        return httpx.Response(503)

    worms = WormsClient(client=httpx.Client(transport=httpx.MockTransport(handler)))
    rows = [_resolved(lineage_key="k1", aphia_id="12"), _resolved(lineage_key="k2", aphia_id="13")]

    with pytest.raises(WormsError):
        refresh_labels(rows, worms)

    assert len(answered) == 2
    assert [row.scientific_name for row in rows] == ["Incertae sedis", "Incertae sedis"]
    assert [row.taxonomic_status for row in rows] == ["unaccepted", "unaccepted"]
