from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import httpx


BASE_URL = "https://api.gbif.org/v1"


class GbifError(RuntimeError):


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
    def taxon_concept_id(self) -> str:

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




class GbifClient:
    def __init__(self, *, client: httpx.Client | None = None, cache_dir: Path | None = None):
        self._client = client or httpx.Client(timeout=TIMEOUT)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

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
        return GbifMatch.from_raw(self._cache[cache_key])

    def species_by_key(self, key: int) -> dict | None:
        cache_key = f"species:{key}"
        if cache_key not in self._cache:
            api_usage.record("gbif_species_by_key")


__all__ = ["CONFIDENT_MATCH_TYPES", "GbifClient", "GbifError", "GbifMatch"]
