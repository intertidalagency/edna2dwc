from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import httpx

from edna2dwc.taxonomy import api_usage, register_http
from edna2dwc.taxonomy.match_cache import MatchCache
from edna2dwc.taxonomy.register_http import TIMEOUT

BASE_URL = "https://api.gbif.org/v1"
CONFIDENT_MATCH_TYPES = ("EXACT",)


class GbifError(RuntimeError):
    pass


def species_url(usage_key: object) -> str:
    return f"https://www.gbif.org/species/{usage_key}" if usage_key not in (None, "") else ""


@dataclass
class GbifMatch:
    usage_key: int | None
    scientific_name: str
    canonical_name: str
    rank: str
    status: str
    match_type: str
    confidence: int
    kingdom: str
    phylum: str
    class_: str
    order: str
    family: str
    genus: str
    synonym: bool
    accepted_usage_key: int | None
    alternatives: list[dict] = field(default_factory=list, repr=False)
    raw: dict = field(repr=False, default_factory=dict)

    @property
    def name(self) -> str:
        return self.canonical_name

    @property
    def register_id(self) -> int | None:
        return self.usage_key

    @property
    def is_accepted(self) -> bool:
        return self.status == "ACCEPTED"

    @property
    def taxon_concept_id(self) -> str:
        return species_url(self.usage_key)

    @property
    def is_confident_match_type(self) -> bool:
        return self.match_type in CONFIDENT_MATCH_TYPES

    @property
    def is_no_match(self) -> bool:
        return self.match_type == "NONE" or self.usage_key is None

    @classmethod
    def from_raw(cls, raw: dict) -> GbifMatch:
        return cls(
            usage_key=raw.get("usageKey"),
            scientific_name=raw.get("scientificName") or "",
            canonical_name=raw.get("canonicalName") or "",
            rank=raw.get("rank") or "",
            status=raw.get("status") or "",
            match_type=raw.get("matchType") or "NONE",
            confidence=raw.get("confidence") or 0,
            kingdom=raw.get("kingdom") or "",
            phylum=raw.get("phylum") or "",
            class_=raw.get("class") or "",
            order=raw.get("order") or "",
            family=raw.get("family") or "",
            genus=raw.get("genus") or "",
            synonym=raw.get("synonym") or False,
            accepted_usage_key=raw.get("acceptedUsageKey"),
            alternatives=raw.get("alternatives") or [],
            raw=raw,
        )


_CACHE_FILENAME = "gbif_match_cache.json"


class GbifClient:
    def __init__(self, *, client: httpx.Client | None = None, cache_dir: Path | None = None):
        self._client = client or httpx.Client(timeout=TIMEOUT)
        self._owns_client = client is None
        self._cache = MatchCache(cache_dir, _CACHE_FILENAME)

    def close(self) -> None:
        self._cache.save()
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> GbifClient:  # noqa: PYI034
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def match(self, name: str, *, kingdom: str = "") -> GbifMatch:
        cache_key = f"{name}\x1f{kingdom}"
        if cache_key not in self._cache:
            params = {"name": name, "strict": "false", "verbose": "true"}
            if kingdom:
                params["kingdom"] = kingdom
            api_usage.record("gbif_match")
            response = register_http.get(
                self._client,
                f"{BASE_URL}/species/match",
                params=params,
                register="gbif",
                error=GbifError,
            )
            self._cache.add({cache_key: response.json()})
        return GbifMatch.from_raw(self._cache[cache_key])

    def species_by_key(self, key: int) -> dict | None:
        cache_key = f"species:{key}"
        if cache_key not in self._cache:
            api_usage.record("gbif_species_by_key")
            response = register_http.get(
                self._client, f"{BASE_URL}/species/{key}", register="gbif", error=GbifError
            )
            self._cache.add({cache_key: response.json()})
        return self._cache[cache_key]


__all__ = ["CONFIDENT_MATCH_TYPES", "GbifClient", "GbifError", "GbifMatch"]
