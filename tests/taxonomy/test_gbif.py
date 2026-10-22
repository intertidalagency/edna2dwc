from __future__ import annotations


import httpx
import pytest



@pytest.fixture(autouse=True)
def _reset_api_usage():
    api_usage.reset()
    yield
    api_usage.reset()


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


AAPTOS_MATCH = {
    "usageKey": 2243941,
    "scientificName": "Aaptos Gray, 1867",
    "canonicalName": "Aaptos",
    "rank": "GENUS",
    "status": "ACCEPTED",
    "confidence": 96,
    "matchType": "EXACT",
    "kingdom": "Animalia",
    "phylum": "Porifera",
    "class": "Demospongiae",
    "order": "Suberitida",
    "family": "Suberitidae",
    "genus": "Aaptos",
    "synonym": False,
    "alternatives": [],
}

NO_MATCH = {"matchType": "NONE", "confidence": 0, "synonym": False}


def test_match_parses_real_response_shape():
    with GbifClient(client=_client(lambda r: httpx.Response(200, json=AAPTOS_MATCH))) as gbif:
        match = gbif.match("Aaptos", kingdom="Animalia")
    assert match.usage_key == 2243941
    assert match.canonical_name == "Aaptos"
    assert match.is_confident_match_type is True
    assert match.taxon_concept_id == "https://www.gbif.org/species/2243941"
    assert api_usage.counts()["gbif_match"] == 1


def test_no_match_is_detected():
    with GbifClient(client=_client(lambda r: httpx.Response(200, json=NO_MATCH))) as gbif:
        match = gbif.match("Totally madeupii")
    assert match.is_no_match is True


def test_cache_avoids_re_querying(tmp_path):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json=AAPTOS_MATCH)

    with GbifClient(client=_client(handler), cache_dir=tmp_path) as gbif:
        gbif.match("Aaptos", kingdom="Animalia")
        gbif.match("Aaptos", kingdom="Animalia")
    assert len(calls) == 1

    with GbifClient(client=_client(handler), cache_dir=tmp_path) as gbif2:
        gbif2.match("Aaptos", kingdom="Animalia")


def test_higher_rank_and_fuzzy_match_types_from_raw():
    higher = GbifMatch.from_raw({**AAPTOS_MATCH, "matchType": "HIGHERRANK"})
    assert higher.is_confident_match_type is False
    fuzzy = GbifMatch.from_raw({**AAPTOS_MATCH, "matchType": "FUZZY"})
    assert fuzzy.is_confident_match_type is False


def test_no_match_usage_key_is_none_and_taxon_concept_id_is_blank():
    match = GbifMatch.from_raw(NO_MATCH)
    assert match.usage_key is None
    assert match.taxon_concept_id == ""


def test_from_raw_survives_explicit_json_nulls_for_unresolved_ranks():
    raw = {
        "usageKey": 100,
        "scientificName": None,
        "canonicalName": None,
        "rank": None,
        "status": None,
        "matchType": None,
        "confidence": None,
        "kingdom": "Animalia",
        "phylum": None,
        "class": None,
        "order": None,
        "family": "Suberitidae",
        "genus": None,
        "synonym": None,
        "acceptedUsageKey": None,
        "alternatives": None,
    }
    match = GbifMatch.from_raw(raw)
    assert match.scientific_name == ""
    assert match.canonical_name == ""
    assert match.rank == ""
    assert match.status == ""
    assert match.match_type == "NONE"
    assert match.confidence == 0
    assert match.phylum == ""
    assert match.class_ == ""
    assert match.order == ""
    assert match.genus == ""
    assert match.synonym is False
    assert match.alternatives == []
    assert match.phylum.casefold() == ""


def test_repeated_match_calls_do_not_rewrite_the_cache_file_every_time(tmp_path, monkeypatch):
    write_calls = []



    def handler(request):
        return httpx.Response(200, json=AAPTOS_MATCH)

    with GbifClient(client=_client(handler), cache_dir=tmp_path) as gbif:
        for i in range(10):
            gbif.match(f"Genus{i} species{i}", kingdom="Animalia")
