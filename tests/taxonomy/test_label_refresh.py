from __future__ import annotations

import httpx
import pytest



@pytest.fixture(autouse=True)
def _reset_api_usage():
    api_usage.reset()
    yield
    api_usage.reset()


def _resolved(**overrides) -> ResolvedTaxon:
        "lineage_key": "k1",
        "scientific_name": "Incertae sedis",
        "scientific_name_id": "urn:lsid:marinespecies.org:taxname:12",
        "taxon_rank": "Kingdom",
        "scientific_name_authorship": "",
        "taxonomic_status": "unaccepted",
        "taxon_concept_id": "",
        "authority": "worms",
    }
    base.update(overrides)
    return ResolvedTaxon(**base)


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
    assert rows[0].scientific_name == "Biota incertae sedis"
    assert rows[0].taxonomic_status == "accepted"


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
    assert rows[0].scientific_name == "Incertae sedis"


def test_reparenting_with_an_unchanged_label_still_triggers_a_refresh():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "AphiaID": 12,
                "phylum": "",
                "class": "",
                "order": "",
                "family": "",
                "genus": "",
                "match_type": "exact",
            },
        )

    worms = WormsClient(client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert rows[0].kingdom == "Biota incertae sedis"


def test_gbif_authority_rows_are_not_refreshed_via_worms():
    worms = WormsClient(
        client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    )
