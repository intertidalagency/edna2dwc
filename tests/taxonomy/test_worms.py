from __future__ import annotations

import json

import httpx
import pytest

    WormsClient,
    WormsError,
)

AAPTOS_RECORD = {
    "AphiaID": 132064,
    "scientificname": "Aaptos",
    "authority": "Gray, 1867",
    "status": "accepted",
    "rank": "Genus",
    "kingdom": "Animalia",
    "phylum": "Porifera",
    "class": "Demospongiae",
    "order": "Suberitida",
    "family": "Suberitidae",
    "genus": "Aaptos",
    "valid_AphiaID": 132064,
    "valid_name": "Aaptos",
    "match_type": "exact",
    "lsid": "urn:lsid:marinespecies.org:taxname:132064",
}


@pytest.fixture(autouse=True)
def _reset_api_usage():
    api_usage.reset()
    yield
    api_usage.reset()


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_match_names_returns_one_entry_per_unique_name_in_order():
    def handler(request):
        names = request.url.params.get_list("scientificnames[]")
        assert names == ["Aaptos", "Acartia tonsa"]
        return httpx.Response(200, json=[[AAPTOS_RECORD], []])

    with WormsClient(client=_client(handler)) as worms:
        result = worms.match_names(["Aaptos", "Acartia tonsa"])
    assert [r.aphia_id for r in result["Aaptos"]] == [132064]
    assert result["Acartia tonsa"] == []


def test_match_names_dedupes_before_calling():
    call_count = 0

    def handler(request):
        nonlocal call_count
        call_count += 1
        names = request.url.params.get_list("scientificnames[]")
        assert names == ["Aaptos"]
        return httpx.Response(200, json=[[AAPTOS_RECORD]])

    with WormsClient(client=_client(handler)) as worms:
        worms.match_names(["Aaptos", "Aaptos", "Aaptos"])
    assert call_count == 1
    assert api_usage.counts()["worms_match"] == 1


def test_match_names_batches_at_50():
    seen_batch_sizes = []

    def handler(request):
        names = request.url.params.get_list("scientificnames[]")
        seen_batch_sizes.append(len(names))
        return httpx.Response(200, json=[[] for _ in names])

    with WormsClient(client=_client(handler)) as worms:
        worms.match_names(names)


def test_204_no_match_returns_empty_list_not_an_error():
    def handler(request):
        return httpx.Response(204)

    with WormsClient(client=_client(handler)) as worms:
        assert worms.match_one("Nonexistentus madeupii") == []


def test_result_batch_length_mismatch_refuses_to_guess_alignment():
    def handler(request):
        names = request.url.params.get_list("scientificnames[]")

        worms.match_names(["A", "B"])


def test_on_disk_cache_avoids_re_querying_across_client_instances(tmp_path):
    call_count = 0

    def handler(request):
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json=[[AAPTOS_RECORD]])

    with WormsClient(client=_client(handler), cache_dir=tmp_path) as worms:
        worms.match_one("Aaptos")
    assert call_count == 1
    cached = json.loads((tmp_path / "worms_match_cache.json").read_text())
    assert cached["Aaptos\x1fFalse"][0]["AphiaID"] == 132064

    with WormsClient(client=_client(handler), cache_dir=tmp_path) as worms2:
        result = worms2.match_one("Aaptos")
    assert call_count == 1
    assert result[0].aphia_id == 132064


def test_cache_key_folds_in_marine_only_so_the_two_never_collide(tmp_path):
    calls = []

    def handler(request):
        calls.append(request.url.params.get("marine_only"))
        return httpx.Response(200, json=[[AAPTOS_RECORD]])

    with WormsClient(client=_client(handler), cache_dir=tmp_path, marine_only=False) as worms:
        worms.match_one("Aaptos")
    with WormsClient(client=_client(handler), cache_dir=tmp_path, marine_only=True) as worms2:
        worms2.match_one("Aaptos")
    assert calls == ["false", "true"]


def test_repeated_match_one_calls_do_not_rewrite_the_cache_file_every_time(tmp_path, monkeypatch):
    write_calls = []



        for i in range(10):
            worms.match_one(f"Genus{i} species{i}")


    def handler(request):

    assert record.scientificname == "Aaptos"





