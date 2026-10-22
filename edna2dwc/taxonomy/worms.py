from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from edna2dwc.common import progress
from edna2dwc.taxonomy import api_usage, register_http
from edna2dwc.taxonomy.match_cache import MatchCache
from edna2dwc.taxonomy.register_http import TIMEOUT

BASE_URL = "https://www.marinespecies.org/rest"
BATCH_SIZE = 50
MAX_CONCURRENT_BATCHES = 4
MAX_CONSECUTIVE_FAILED_BATCHES = 2 * MAX_CONCURRENT_BATCHES
MIN_BATCHES_FOR_PROGRESS = 2
_CACHE_FILENAME = "worms_match_cache.json"

CONFIDENT_MATCH_TYPES = ("exact", "exact_subgenus", "exact_replaced")

BIOTA_INCERTAE_SEDIS = "Biota incertae sedis"
BIOTA_INCERTAE_SEDIS_APHIA_ID = 12
BIOTA_APHIA_ID = 1


class WormsError(RuntimeError):
    pass


class WormsBatchAlignmentError(WormsError):
    pass


@dataclass
class AphiaRecord:
    aphia_id: int
    scientificname: str
    authority: str
    status: str
    rank: str
    kingdom: str
    phylum: str
    class_: str
    order: str
    family: str
    genus: str
    match_type: str
    valid_aphia_id: int | None
    valid_name: str | None
    raw: dict = field(repr=False, default_factory=dict)

    @property
    def name(self) -> str:
        return self.scientificname

    @property
    def register_id(self) -> int:
        return self.aphia_id

    @property
    def is_accepted(self) -> bool:
        return self.status == "accepted"

    @property
    def lsid(self) -> str:
        return f"urn:lsid:marinespecies.org:taxname:{self.aphia_id}"

    @property
    def is_confident_match_type(self) -> bool:
        return self.match_type in CONFIDENT_MATCH_TYPES

    @classmethod
    def from_raw(cls, raw: dict) -> AphiaRecord:
        return cls(
            aphia_id=raw["AphiaID"],
            scientificname=raw["scientificname"],
            authority=raw.get("authority") or "",
            status=raw.get("status") or "",
            rank=raw.get("rank") or "",
            kingdom=raw.get("kingdom") or "",
            phylum=raw.get("phylum") or "",
            class_=raw.get("class") or "",
            order=raw.get("order") or "",
            family=raw.get("family") or "",
            genus=raw.get("genus") or "",
            match_type=raw.get("match_type") or "",
            valid_aphia_id=raw.get("valid_AphiaID"),
            valid_name=raw.get("valid_name"),
            raw=raw,
        )


def _usable_records(raws: list[dict]) -> list[AphiaRecord]:
    return [AphiaRecord.from_raw(raw) for raw in raws if raw.get("scientificname")]


def _retry_request(client: httpx.Client, url: str, *, params=None) -> httpx.Response | None:
    response = register_http.get(client, url, params=params, register="worms", error=WormsError)
    return None if response.status_code == 204 else response


def _failures_not_yet_seen(futures: Iterable[Future], seen: set[Future]) -> list[WormsError]:
    return [
        failure
        for future in futures
        if future not in seen and not future.cancelled()
        if isinstance(failure := future.exception(), WormsError)
    ]


def _describe_failure(failure: WormsError) -> str:
    cause = failure.__cause__
    if not isinstance(cause, Exception):
        return "misaligned result count"
    return api_usage.describe_failure(cause)


def _gave_up_error(failures: list[WormsError]) -> WormsError:
    if all(isinstance(failure, WormsBatchAlignmentError) for failure in failures):
        return WormsBatchAlignmentError(
            f"{len(failures)} WoRMS batches came back with a result count that does not match "
            "the names asked about: refusing to guess alignment, and not retrying them one "
            "name at a time"
        )
    causes = Counter(_describe_failure(failure) for failure in failures)
    tally = ", ".join(f"{count} {cause}" for cause, count in causes.most_common())
    return WormsError(
        f"{len(failures)} WoRMS batches in a row failed ({tally}), each after "
        f"{register_http.MAX_ATTEMPTS} attempts. Treating this as a register outage rather than "
        "as names WoRMS cannot handle"
    )


class WormsClient:
    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        cache_dir: Path | None = None,
        marine_only: bool = False,
        stage: str = "worms",
    ):
        self._client = client or httpx.Client(timeout=TIMEOUT)
        self._owns_client = client is None
        self._marine_only = marine_only
        self._stage = stage
        self._match_cache = MatchCache(cache_dir, _CACHE_FILENAME)

    def close(self) -> None:
        self._match_cache.save()
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> WormsClient:  # noqa: PYI034
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _cache_key(self, name: str) -> str:
        return f"{name}\x1f{self._marine_only}"

    def cache_status(self, names: Iterable[str]) -> progress.LookupEstimate:
        unique = list(dict.fromkeys(names))
        cached = sum(1 for n in unique if self._cache_key(n) in self._match_cache)
        uncached = len(unique) - cached
        return progress.LookupEstimate(
            distinct_names=len(unique),
            cached=cached,
            batches=-(-uncached // BATCH_SIZE),
            concurrency=MAX_CONCURRENT_BATCHES,
        )

    def _fetch_batch(self, batch: list[str]) -> None:
        params = [("scientificnames[]", n) for n in batch]
        params.append(("marine_only", "true" if self._marine_only else "false"))
        api_usage.record("worms_match")
        response = _retry_request(
            self._client, f"{BASE_URL}/AphiaRecordsByMatchNames", params=params
        )
        results = response.json() if response is not None else [None] * len(batch)
        if len(results) != len(batch):
            raise WormsBatchAlignmentError(
                f"WoRMS returned {len(results)} result(s) for a {len(batch)}-name batch "
                "-- refusing to guess alignment"
            )
        self._match_cache.add(
            {
                self._cache_key(name): candidates or []
                for name, candidates in zip(batch, results, strict=True)
            }
        )

    def _fetch_batches(
        self,
        batches: list[list[str]],
        *,
        isolate_failures: bool,
        on_done: Callable[[int], None] | None = None,
    ) -> list[list[str]]:

        def settled(batch: list[str]) -> None:
            if on_done is not None:
                on_done(len(batch))

        if len(batches) == 1:
            try:
                self._fetch_batch(batches[0])
            except WormsError:
                if not isolate_failures:
                    raise
                settled(batches[0])
                return batches
            settled(batches[0])
            return []

        failed: list[list[str]] = []
        failed_in_a_row: list[WormsError] = []
        pool = ThreadPoolExecutor(max_workers=min(MAX_CONCURRENT_BATCHES, len(batches)))
        try:
            futures = {pool.submit(self._fetch_batch, batch): batch for batch in batches}
            seen: set[Future] = set()
            for future in as_completed(futures):
                seen.add(future)
                batch = futures[future]
                try:
                    future.result()
                    failed_in_a_row.clear()
                except WormsError as failure:
                    if not isolate_failures:
                        raise
                    failed.append(batch)
                    failed_in_a_row.append(failure)
                    if len(failed_in_a_row) >= MAX_CONSECUTIVE_FAILED_BATCHES:
                        pool.shutdown(wait=True, cancel_futures=True)
                        unseen = _failures_not_yet_seen(futures, seen)
                        raise _gave_up_error(failed_in_a_row + unseen) from failure
                settled(batch)
        except WormsError:
            pool.shutdown(wait=True, cancel_futures=True)
            raise
        except BaseException:
            pool.shutdown(wait=False, cancel_futures=True)
            raise
        pool.shutdown(wait=True)
        return failed

    def match_names(
        self, names: list[str], *, isolate_failures: bool = False, stage: str | None = None
    ) -> dict[str, list[AphiaRecord]]:
        unique_names = list(dict.fromkeys(names))
        to_fetch = [n for n in unique_names if self._cache_key(n) not in self._match_cache]
        batches = [
            to_fetch[start : start + BATCH_SIZE] for start in range(0, len(to_fetch), BATCH_SIZE)
        ]
        if batches:
            bar = (
                progress.BatchProgress(
                    total_batches=len(batches),
                    stage=stage or self._stage,
                )
                if len(batches) >= MIN_BATCHES_FOR_PROGRESS
                else None
            )
            failed = self._fetch_batches(
                batches,
                isolate_failures=isolate_failures,
                on_done=bar.advance if bar is not None else None,
            )
            retriable = [name for batch in failed if len(batch) > 1 for name in batch]
            if retriable:
                self._fetch_batches([[name] for name in retriable], isolate_failures=True)
            if bar is not None:
                bar.finish()

        return {
            name: _usable_records(self._match_cache[self._cache_key(name)])
            for name in unique_names
            if self._cache_key(name) in self._match_cache
        }

    def match_one(self, name: str) -> list[AphiaRecord]:
        return self.match_names([name])[name]

    def record_by_aphia_id(self, aphia_id: int) -> AphiaRecord | None:
        key = f"record:{aphia_id}"
        if key not in self._match_cache:
            record = self.current_record_by_aphia_id(aphia_id)
            self._match_cache.add({key: [record.raw] if record is not None else []})
        return next(iter(_usable_records(self._match_cache[key])), None)

    def current_record_by_aphia_id(self, aphia_id: int) -> AphiaRecord | None:
        api_usage.record("worms_record_by_id")
        response = _retry_request(self._client, f"{BASE_URL}/AphiaRecordByAphiaID/{aphia_id}")
        if response is None:
            return None
        return next(iter(_usable_records([response.json()])), None)
