from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import gzip
import json
import math
from pathlib import Path

_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "boundaries.json.gz"
_ISO_3166_ALPHA2_PATH = _DATA_PATH.with_name("iso3166_alpha2.txt")

NEARBY_COUNTRY_KM = 25.0
_EARTH_RADIUS_KM = 6371.0088
_KM_PER_DEGREE = math.radians(1) * _EARTH_RADIUS_KM
_SEAM_SHIFTS = (-360.0, 0.0, 360.0)


@dataclass(frozen=True, eq=False)
class BoundaryPolygon:
    iso_a2: str
    bbox: tuple[float, float, float, float]
    rings: tuple[tuple[tuple[float, float], ...], ...]

    def contains(self, lat: float, lon: float) -> bool:
        return sum(_crossings(lon, lat, ring) for ring in self.rings) % 2 == 1


@lru_cache(maxsize=1)
def _load_boundaries() -> tuple[BoundaryPolygon, ...]:
    if not _DATA_PATH.exists():
        raise FileNotFoundError(
            f"{_DATA_PATH} is missing, so the install is incomplete. Reinstall edna2dwc, or in a checkout run `python -I maintenance/boundaries.py`"
        )
    raw = json.loads(gzip.decompress(_DATA_PATH.read_bytes()))
    return tuple(
        BoundaryPolygon(
            iso_a2=r["iso_a2"],
            bbox=tuple(r["bbox"]),
            rings=tuple(tuple((p[0], p[1]) for p in ring) for ring in r["rings"]),
        )
        for r in raw
    )


@lru_cache(maxsize=1)
def valid_country_codes() -> frozenset[str]:
    assigned = _ISO_3166_ALPHA2_PATH.read_text(encoding="utf-8").split()
    return frozenset(assigned) | {p.iso_a2 for p in _load_boundaries()}


def _crossings(lon: float, lat: float, ring: tuple[tuple[float, float], ...]) -> int:
    crossings = 0
    x1, y1 = ring[-1]
    for x2, y2 in ring:
        if (y1 > lat) != (y2 > lat) and lon < x1 + (lat - y1) * (x2 - x1) / (y2 - y1):
            crossings += 1
        x1, y1 = x2, y2
    return crossings


def _normalize_longitude(lon: float) -> float:
    return ((lon + 180) % 360) - 180


@lru_cache(maxsize=4096)
def candidate_polygons_for(lat: float, lon: float) -> tuple[BoundaryPolygon, ...]:
    lon = _normalize_longitude(lon)
    return tuple(
        poly
        for poly in _load_boundaries()
        if poly.bbox[0] <= lon <= poly.bbox[2] and poly.bbox[1] <= lat <= poly.bbox[3]
    )


@lru_cache(maxsize=4096)
def country_code_for(lat: float, lon: float) -> str | None:
    lon = _normalize_longitude(lon)
    return next(
        (poly.iso_a2 for poly in candidate_polygons_for(lat, lon) if poly.contains(lat, lon)),
        None,
    )


@dataclass(frozen=True)
class Placement:
    iso_a2: str
    distance_km: float


def place_in_country(lat: float, lon: float) -> Placement | None:
    lon = _normalize_longitude(lon)
    if code := country_code_for(lat, lon):
        return Placement(code, 0.0)
    distance, code = min(
        (
            (min(distance_to_nearby_ring_km(lat, lon, ring) for ring in poly.rings), poly.iso_a2)
            for poly in _polygons_within(lat, lon, NEARBY_COUNTRY_KM)
        ),
        default=(math.inf, ""),
    )
    return Placement(code, distance) if distance <= NEARBY_COUNTRY_KM else None


def _polygons_within(lat: float, lon: float, km: float) -> list[BoundaryPolygon]:
    dlat = km / _KM_PER_DEGREE
    dlon = dlat / max(math.cos(math.radians(min(abs(lat) + dlat, 90.0))), dlat / 180)
    return [
        poly
        for poly in _load_boundaries()
        if poly.bbox[1] - dlat <= lat <= poly.bbox[3] + dlat
        and any(
            poly.bbox[0] - dlon <= lon + shift <= poly.bbox[2] + dlon for shift in _SEAM_SHIFTS
        )
    ]


def distance_to_nearby_ring_km(
    lat: float, lon: float, ring: tuple[tuple[float, float], ...]
) -> float:
    scale = max(math.cos(math.radians(lat)), 1e-9)
    reach = NEARBY_COUNTRY_KM / _KM_PER_DEGREE
    nearest = math.inf
    x1, y1 = _plane_offset(lat, lon, ring[-1], scale)
    for vertex in ring:
        x2, y2 = _plane_offset(lat, lon, vertex, scale)
        if not (
            min(x1, x2) > reach
            or max(x1, x2) < -reach
            or min(y1, y2) > reach
            or max(y1, y2) < -reach
        ):
            x, y = _nearest_on_segment(x1, y1, x2, y2)
            nearest = min(nearest, _haversine_km(lat, lon, lat + y, lon + x / scale))
        x1, y1 = x2, y2
    return nearest


def _plane_offset(
    lat: float, lon: float, vertex: tuple[float, float], scale: float
) -> tuple[float, float]:
    return _normalize_longitude(vertex[0] - lon) * scale, vertex[1] - lat


def _nearest_on_segment(x1: float, y1: float, x2: float, y2: float) -> tuple[float, float]:
    dx, dy = x2 - x1, y2 - y1
    length_squared = dx * dx + dy * dy
    t = 0.0 if length_squared == 0 else max(0.0, min(1.0, -(x1 * dx + y1 * dy) / length_squared))
    return x1 + t * dx, y1 + t * dy


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    half_chord = (
        math.sin((phi2 - phi1) / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(min(1.0, half_chord)))
