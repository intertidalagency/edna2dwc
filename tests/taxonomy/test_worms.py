from __future__ import annotations

import concurrent.futures
import json
import os
import threading
import time

import httpx
import pytest

from edna2dwc.common import progress
from edna2dwc.taxonomy import api_usage
from edna2dwc.taxonomy.match_cache import MatchCache
from edna2dwc.taxonomy.worms import (
    BATCH_SIZE,
    MAX_CONCURRENT_BATCHES,
    MAX_CONSECUTIVE_FAILED_BATCHES,
    WormsBatchAlignmentError,
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


def _answer_every_name(request):
    names = request.url.params.get_list("scientificnames[]")
    return httpx.Response(200, json=[[{**AAPTOS_RECORD, "scientificname": n}] for n in names])


def _match_no_name(request):
    names = request.url.params.get_list("scientificnames[]")
    return httpx.Response(200, json=[[] for _ in names])


def _names(count: int) -> list[str]:
    return [f"Genus{i} species{i}" for i in range(count)]


def test_match_names_returns_one_entry_per_unique_name_in_order():
    def handler(request):
        names = request.url.params.get_list("scientificnames[]")
        assert names == ["Aaptos", "Acartia tonsa"]
        return httpx.Response(200, json=[[AAPTOS_RECORD], []])

    with WormsClient(client=_client(handler)) as worms:
        result = worms.match_names(["Aaptos", "Acartia tonsa"])
    assert [r.aphia_id for r in result["Aaptos"]] == [132064]
    assert result["Acartia tonsa"] == []


def test_a_match_with_a_null_name_is_not_a_usable_record():
    def handler(request):
        return httpx.Response(200, json=[[{**AAPTOS_RECORD, "scientificname": None}]])

    with WormsClient(client=_client(handler)) as worms:
        assert worms.match_one("Aaptos") == []


def test_a_record_by_aphia_id_with_a_null_name_is_not_a_usable_record():
    def handler(request):
        return httpx.Response(200, json={**AAPTOS_RECORD, "scientificname": None})

    with WormsClient(client=_client(handler)) as worms:
        assert worms.record_by_aphia_id(132064) is None
        assert worms.current_record_by_aphia_id(132064) is None


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

    names = _names(120)
    with WormsClient(client=_client(handler)) as worms:
        worms.match_names(names)
    assert sorted(seen_batch_sizes) == [20, 50, 50]


def test_204_no_match_returns_empty_list_not_an_error():
    def handler(request):
        return httpx.Response(204)

    with WormsClient(client=_client(handler)) as worms:
        assert worms.match_one("Nonexistentus madeupii") == []


def test_result_batch_length_mismatch_refuses_to_guess_alignment():
    def handler(request):
        names = request.url.params.get_list("scientificnames[]")
        return httpx.Response(200, json=[[] for _ in names[:-1]])

    with WormsClient(client=_client(handler)) as worms, pytest.raises(WormsBatchAlignmentError):
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
    original_replace = os.replace

    def counting_replace(source, destination):
        write_calls.append(destination)
        return original_replace(source, destination)

    monkeypatch.setattr(os, "replace", counting_replace)

    with WormsClient(client=_client(_answer_every_name), cache_dir=tmp_path) as worms:
        for i in range(10):
            worms.match_one(f"Genus{i} species{i}")
        assert len(write_calls) == 0
    assert len(write_calls) == 1


def test_a_stalled_flush_cannot_overwrite_a_newer_one_and_lose_its_batches(tmp_path, monkeypatch):
    names = _names(3 * BATCH_SIZE)
    first_batch_flushing = threading.Event()

    def handler(request):
        got = request.url.params.get_list("scientificnames[]")
        if "Genus0 species0" not in got:
            first_batch_flushing.wait(timeout=5)
        return _answer_every_name(request)

    real_snapshot = MatchCache._take_snapshot

    def snapshot_stalling_the_first_claim(self, min_unsaved):
        snapshot = real_snapshot(self, min_unsaved)
        if snapshot is not None and not first_batch_flushing.is_set():
            first_batch_flushing.set()
            time.sleep(0.5)
        return snapshot

    monkeypatch.setattr(MatchCache, "_take_snapshot", snapshot_stalling_the_first_claim)
    with WormsClient(client=_client(handler), cache_dir=tmp_path) as worms:
        worms.match_names(names)

    def refuse(request):
        raise AssertionError(f"a warm cache still issued a request: {request.url}")

    with WormsClient(client=_client(refuse), cache_dir=tmp_path) as warm:
        assert set(warm.match_names(names)) == set(names)


def _record_handler(requests: list[str]):
    def handler(request):
        requests.append(request.url.path)
        if request.url.path.endswith("/AphiaRecordByAphiaID/132064"):
            return httpx.Response(200, json=AAPTOS_RECORD)
        return httpx.Response(204)

    return handler


def test_record_by_aphia_id_is_answered_from_the_cache_the_second_time(tmp_path):
    requests: list[str] = []
    with WormsClient(client=_client(_record_handler(requests)), cache_dir=tmp_path) as worms:
        worms.record_by_aphia_id(132064)
    with WormsClient(client=_client(_record_handler(requests)), cache_dir=tmp_path) as warm:
        record = warm.record_by_aphia_id(132064)
    assert record is not None
    assert record.scientificname == "Aaptos"
    assert requests == ["/rest/AphiaRecordByAphiaID/132064"]


def test_record_by_aphia_id_caches_an_id_the_register_does_not_know(tmp_path):
    requests: list[str] = []
    with WormsClient(client=_client(_record_handler(requests)), cache_dir=tmp_path) as worms:
        worms.record_by_aphia_id(999)
    with WormsClient(client=_client(_record_handler(requests)), cache_dir=tmp_path) as warm:
        assert warm.record_by_aphia_id(999) is None
    assert requests == ["/rest/AphiaRecordByAphiaID/999"]


def test_current_record_by_aphia_id_asks_the_register_even_when_the_id_is_cached(tmp_path):
    requests: list[str] = []
    with WormsClient(client=_client(_record_handler(requests)), cache_dir=tmp_path) as worms:
        worms.record_by_aphia_id(132064)
        record = worms.current_record_by_aphia_id(132064)
    assert record is not None
    assert len(requests) == 2
    assert api_usage.counts()["worms_record_by_id"] == 2


def test_isolate_failures_retries_a_failed_batch_one_name_at_a_time(monkeypatch):
    monkeypatch.setattr("edna2dwc.taxonomy.register_http.MAX_ATTEMPTS", 1)
    bad_name = "Genus3 species3"
    seen_batch_sizes = []

    def handler(request):
        names = request.url.params.get_list("scientificnames[]")
        seen_batch_sizes.append(len(names))
        if bad_name in names:
            return httpx.Response(500)
        return _answer_every_name(request)

    names = _names(5)
    with WormsClient(client=_client(handler)) as worms:
        result = worms.match_names(names, isolate_failures=True)

    assert seen_batch_sizes == [5, 1, 1, 1, 1, 1]
    assert sorted(result) == sorted(n for n in names if n != bad_name)


def test_progress_completes_and_counts_every_name_when_a_batch_fails_and_retries(
    monkeypatch, capsys
):
    monkeypatch.setattr("edna2dwc.taxonomy.register_http.MAX_ATTEMPTS", 1)
    monkeypatch.delenv(progress.QUIET_ENV, raising=False)
    bad_name = "Genus0 species0"

    def handler(request):
        names = request.url.params.get_list("scientificnames[]")
        if bad_name in names and len(names) > 1:
            return httpx.Response(500)
        return _answer_every_name(request)

    names = _names(BATCH_SIZE + 5)
    with WormsClient(client=_client(handler), stage="resolve-taxonomy") as worms:
        result = worms.match_names(names, isolate_failures=True)

    assert sorted(result) == sorted(names)
    err = capsys.readouterr().err
    assert "[2/2]" in err
    assert f"{BATCH_SIZE + 5} names" in err


def test_a_name_that_failed_under_isolate_failures_still_raises_on_the_next_lookup(monkeypatch):
    monkeypatch.setattr("edna2dwc.taxonomy.register_http.MAX_ATTEMPTS", 1)

    def handler(request):
        return httpx.Response(500)

    with WormsClient(client=_client(handler)) as worms:
        worms.match_names(["Aaptos", "Acartia tonsa"], isolate_failures=True)
        with pytest.raises(WormsError):
            worms.match_one("Aaptos")


def test_without_isolate_failures_a_failed_batch_raises(monkeypatch):
    monkeypatch.setattr("edna2dwc.taxonomy.register_http.MAX_ATTEMPTS", 1)

    def handler(request):
        return httpx.Response(500)

    with WormsClient(client=_client(handler)) as worms, pytest.raises(WormsError):
        worms.match_names(["Aaptos", "Acartia tonsa"])


def test_a_register_wide_outage_stops_instead_of_retrying_every_name_alone(monkeypatch):
    monkeypatch.setattr("edna2dwc.taxonomy.register_http.MAX_ATTEMPTS", 1)
    seen_batch_sizes = []
    lock = threading.Lock()

    def handler(request):
        with lock:
            seen_batch_sizes.append(len(request.url.params.get_list("scientificnames[]")))
        return httpx.Response(503)

    names = _names(10 * BATCH_SIZE)
    with WormsClient(client=_client(handler)) as worms, pytest.raises(WormsError) as raised:
        worms.match_names(names, isolate_failures=True)
    assert type(raised.value) is WormsError

    assert 1 not in seen_batch_sizes
    assert len(seen_batch_sizes) <= len(names) // BATCH_SIZE


def _rate_limited(request):
    return httpx.Response(429)


def _timed_out(request):
    raise httpx.ReadTimeout("slow", request=request)


@pytest.mark.parametrize(
    ("failure", "reported"),
    [(_rate_limited, "HTTP 429 Too Many Requests"), (_timed_out, "ReadTimeout")],
)
def test_a_register_wide_outage_says_how_the_batches_failed(monkeypatch, failure, reported):
    monkeypatch.setattr("edna2dwc.taxonomy.register_http.MAX_ATTEMPTS", 1)

    names = _names(10 * BATCH_SIZE)
    with WormsClient(client=_client(failure)) as worms, pytest.raises(WormsError) as raised:
        worms.match_names(names, isolate_failures=True)

    assert reported in str(raised.value)


def test_a_register_wide_outage_says_how_many_attempts_each_batch_had(monkeypatch):
    monkeypatch.setattr("edna2dwc.taxonomy.register_http.MAX_ATTEMPTS", 3)
    monkeypatch.setattr("edna2dwc.taxonomy.register_http.sleep", lambda seconds: None)

    names = _names(10 * BATCH_SIZE)
    with WormsClient(client=_client(_timed_out)) as worms, pytest.raises(WormsError) as raised:
        worms.match_names(names, isolate_failures=True)

    assert "each after 3 attempts" in str(raised.value)


def test_failures_short_of_an_outage_are_still_isolated_one_name_at_a_time(monkeypatch):
    monkeypatch.setattr("edna2dwc.taxonomy.register_http.MAX_ATTEMPTS", 1)
    doomed = {
        f"Genus{i * BATCH_SIZE} species{i * BATCH_SIZE}"
        for i in range(MAX_CONSECUTIVE_FAILED_BATCHES - 1)
    }
    lock = threading.Lock()
    isolated = []

    def handler(request):
        names = request.url.params.get_list("scientificnames[]")
        if doomed & set(names):
            with lock:
                if len(names) == 1:
                    isolated.append(names[0])
            return httpx.Response(503)
        return _answer_every_name(request)

    names = _names(10 * BATCH_SIZE)
    with WormsClient(client=_client(handler)) as worms:
        result = worms.match_names(names, isolate_failures=True)

    assert sorted(isolated) == sorted(doomed)
    assert sorted(result) == sorted(n for n in names if n not in doomed)


def test_giving_up_on_misaligned_batches_does_not_report_the_register_going_quiet():
    def handler(request):
        names = request.url.params.get_list("scientificnames[]")
        return httpx.Response(200, json=[[] for _ in names[:-1]])

    names = _names((MAX_CONSECUTIVE_FAILED_BATCHES + 2) * BATCH_SIZE)
    with WormsClient(client=_client(handler)) as worms, pytest.raises(WormsBatchAlignmentError):
        worms.match_names(names, isolate_failures=True)


def test_giving_up_on_a_transport_failure_among_misaligned_batches_is_still_an_outage(monkeypatch):
    monkeypatch.setattr("edna2dwc.taxonomy.register_http.MAX_ATTEMPTS", 1)

    def handler(request):
        names = request.url.params.get_list("scientificnames[]")
        if names[0] == "Genus0 species0":
            time.sleep(0.2)
            return httpx.Response(503)
        return httpx.Response(200, json=[[] for _ in names[:-1]])

    names = _names((MAX_CONSECUTIVE_FAILED_BATCHES + 2) * BATCH_SIZE)
    with WormsClient(client=_client(handler)) as worms, pytest.raises(WormsError) as raised:
        worms.match_names(names, isolate_failures=True)

    assert not isinstance(raised.value, WormsBatchAlignmentError)


def test_an_outage_cancels_the_batches_still_queued(monkeypatch):
    monkeypatch.setattr("edna2dwc.taxonomy.register_http.MAX_ATTEMPTS", 1)
    served = []
    lock = threading.Lock()

    def handler(request):
        with lock:
            served.append(request.url.params.get_list("scientificnames[]"))
        time.sleep(0.01)
        return httpx.Response(503)

    names = _names(40 * BATCH_SIZE)
    with WormsClient(client=_client(handler)) as worms, pytest.raises(WormsError):
        worms.match_names(names, isolate_failures=True)

    assert len(served) < 40


def test_an_interrupt_cancels_the_batches_still_queued(monkeypatch):
    monkeypatch.setattr("edna2dwc.taxonomy.register_http.MAX_ATTEMPTS", 1)
    served = []
    lock = threading.Lock()

    def handler(request):
        names = request.url.params.get_list("scientificnames[]")
        with lock:
            served.append(names)
        time.sleep(0.01)
        return httpx.Response(200, json=[[] for _ in names])

    calls = {"n": 0}
    real_result = concurrent.futures.Future.result

    def interrupt_on_first_result(self, timeout=None):
        calls["n"] += 1
        value = real_result(self, timeout)
        if calls["n"] < 2:
            raise KeyboardInterrupt
        return value

    monkeypatch.setattr(concurrent.futures.Future, "result", interrupt_on_first_result)
    names = _names(40 * BATCH_SIZE)
    with WormsClient(client=_client(handler)) as worms, pytest.raises(KeyboardInterrupt):
        worms.match_names(names)

    assert len(served) < 40


class _OwnedLock:
    def __init__(self):
        self._lock = threading.Lock()
        self.owner = None

    def __enter__(self):
        self._lock.acquire()
        self.owner = threading.get_ident()

    def __exit__(self, *exc):
        self.owner = None
        self._lock.release()


def test_a_flush_does_not_hold_the_cache_lock_while_it_writes(tmp_path, monkeypatch):
    monkeypatch.setattr("edna2dwc.taxonomy.register_http.MAX_ATTEMPTS", 1)
    holders = []

    worms = WormsClient(client=_client(_match_no_name), cache_dir=tmp_path)
    lock = _OwnedLock()
    monkeypatch.setattr(worms._match_cache, "_lock", lock)
    real_replace = os.replace

    def watch_write(source, destination):
        holders.append(lock.owner == threading.get_ident())
        return real_replace(source, destination)

    monkeypatch.setattr(os, "replace", watch_write)
    worms.match_names(_names(4 * BATCH_SIZE))
    worms.close()

    assert holders
    assert not any(holders)


def test_cache_status_counts_distinct_names_and_the_requests_they_need():
    with WormsClient(client=_client(_match_no_name)) as worms:
        cold = worms.cache_status(["Aaptos", "Aaptos", "Acartia tonsa"])
        assert cold.distinct_names == 2
        assert cold.cached == 0
        assert cold.uncached == 2
        assert cold.batches == 1

        worms.match_names(["Aaptos"])
        warm = worms.cache_status(["Aaptos", "Acartia tonsa"])

    assert warm.cached == 1
    assert warm.uncached == 1


def test_cache_status_splits_the_uncached_remainder_into_batches():
    with WormsClient(client=_client(lambda request: httpx.Response(500))) as worms:
        estimate = worms.cache_status(f"Name {i}" for i in range(BATCH_SIZE * 3 + 1))

    assert estimate.distinct_names == BATCH_SIZE * 3 + 1
    assert estimate.batches == 4


def test_cache_status_of_a_fully_cached_set_needs_no_requests():
    with WormsClient(client=_client(_match_no_name)) as worms:
        worms.match_names(["Aaptos", "Acartia tonsa"])
        estimate = worms.cache_status(["Aaptos", "Acartia tonsa"])

    assert estimate.uncached == 0
    assert estimate.batches == 0


def test_a_multi_batch_fetch_reports_progress_on_stderr(capsys, monkeypatch):
    monkeypatch.delenv("EDNA2DWC_QUIET", raising=False)

    with WormsClient(client=_client(_match_no_name)) as worms:
        worms.match_names([f"Name {i}" for i in range(BATCH_SIZE * 2)])

    err = capsys.readouterr().err
    assert "[1/2]" in err
    assert f"{BATCH_SIZE * 2} names" in err


def test_a_single_batch_fetch_stays_silent(capsys, monkeypatch):
    monkeypatch.delenv("EDNA2DWC_QUIET", raising=False)

    with WormsClient(client=_client(_match_no_name)) as worms:
        worms.match_names(["Aaptos", "Acartia tonsa"])

    assert capsys.readouterr().err == ""


def test_failed_batches_scattered_among_answered_ones_are_not_an_outage():
    names = _names(30 * BATCH_SIZE)
    doomed = {names[start] for start in range(0, len(names), 3 * BATCH_SIZE)}

    def handler(request):
        got = request.url.params.get_list("scientificnames[]")
        if len(got) > 1 and doomed & set(got):
            return httpx.Response(503)
        return _answer_every_name(request)

    with WormsClient(client=_client(handler)) as worms:
        result = worms.match_names(names, isolate_failures=True)

    assert sorted(result) == sorted(names)


def test_a_batch_in_flight_when_an_outage_is_declared_still_reaches_the_cache(tmp_path):
    names = _names(11 * BATCH_SIZE)
    straggler = names[:BATCH_SIZE]

    def handler(request):
        got = request.url.params.get_list("scientificnames[]")
        if got == straggler:
            time.sleep(0.3)
            return httpx.Response(200, json=[[] for _ in got])
        return httpx.Response(503)

    worms = WormsClient(client=_client(handler), cache_dir=tmp_path)
    with worms, pytest.raises(WormsError):
        worms.match_names(names, isolate_failures=True)

    cached = json.loads((tmp_path / "worms_match_cache.json").read_text())
    assert {f"{name}\x1fFalse" for name in straggler} <= set(cached)


def test_batches_are_fetched_concurrently_up_to_the_limit():
    in_flight = 0
    peak = 0
    lock = threading.Lock()

    def handler(request):
        nonlocal in_flight, peak
        with lock:
            in_flight += 1
            peak = max(peak, in_flight)
        time.sleep(0.05)
        with lock:
            in_flight -= 1
        return _match_no_name(request)

    with WormsClient(client=_client(handler)) as worms:
        worms.match_names(_names(3 * BATCH_SIZE))

    assert 1 < peak <= MAX_CONCURRENT_BATCHES


def test_concurrent_batches_lose_neither_a_cache_entry_nor_a_counted_request():
    names = _names(20 * BATCH_SIZE)
    with WormsClient(client=_client(_answer_every_name)) as worms:
        worms.match_names(names)
        assert api_usage.counts()["worms_match"] == 20

        api_usage.reset()
        assert set(worms.match_names(names)) == set(names)
    assert api_usage.counts().get("worms_match", 0) == 0


def test_a_cache_file_cut_off_partway_is_read_as_empty_and_written_whole(tmp_path):
    cache_path = tmp_path / "worms_match_cache.json"
    cache_path.write_text('{"Aaptos\\u001fFalse": [{"AphiaID": 13', encoding="utf-8")

    with WormsClient(client=_client(_answer_every_name), cache_dir=tmp_path) as worms:
        assert worms.match_one("Aaptos")[0].aphia_id == 132064

    assert set(json.loads(cache_path.read_text(encoding="utf-8"))) == {"Aaptos\x1fFalse"}
