from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import httpx


BASE_URL = "https://www.marinespecies.org/rest"
BATCH_SIZE = 50

CONFIDENT_MATCH_TYPES = ("exact", "exact_subgenus", "exact_replaced")

BIOTA_INCERTAE_SEDIS = "Biota incertae sedis"
BIOTA_INCERTAE_SEDIS_APHIA_ID = 12
BIOTA_APHIA_ID = 1


class WormsError(RuntimeError):


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
    def lsid(self) -> str:
        return f"urn:lsid:marinespecies.org:taxname:{self.aphia_id}"

    @property
    def is_confident_match_type(self) -> bool:
        return self.match_type in CONFIDENT_MATCH_TYPES

    @classmethod
    def from_raw(cls, raw: dict) -> AphiaRecord:
        return cls(
            aphia_id=raw["AphiaID"],
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


def _retry_request(client: httpx.Client, url: str, *, params=None) -> httpx.Response | None:


class WormsClient:
    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        cache_dir: Path | None = None,
        marine_only: bool = False,
    ):
        self._client = client or httpx.Client(timeout=TIMEOUT)
        self._owns_client = client is None
        self._marine_only = marine_only

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _cache_key(self, name: str) -> str:
        return f"{name}\x1f{self._marine_only}"

        unique_names = list(dict.fromkeys(names))
        to_fetch = [n for n in unique_names if self._cache_key(n) not in self._match_cache]

        return {
            for name in unique_names
        }

    def match_one(self, name: str) -> list[AphiaRecord]:
        return self.match_names([name])[name]

    def record_by_aphia_id(self, aphia_id: int) -> AphiaRecord | None:
        api_usage.record("worms_record_by_id")
        response = _retry_request(self._client, f"{BASE_URL}/AphiaRecordByAphiaID/{aphia_id}")
        if response is None:
            return None
