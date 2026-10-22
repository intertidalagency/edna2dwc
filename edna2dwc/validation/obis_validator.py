from __future__ import annotations

from dataclasses import dataclass
import math
import re


DEFAULT_BUFFER_DEGREES = 0.01

NEARSHORE_HABITAT_KEYWORDS = (
    "intertidal",
    "nearshore",
    "coastal",
    "estuary",
    "estuarine",
    "beach",
    "tidal",
    "harbor",
    "harbour",
    "bay",
    "inlet",
    "lagoon",
    "mudflat",
    "marsh",
    "littoral",
    "mangrove",
    "reef",
    "shoreline",
)

_SHORE_WORD_RE = re.compile(r"\bshore\b")


def is_nearshore_habitat_hint(habitat: str) -> bool:
    lowered = habitat.lower()
    if _SHORE_WORD_RE.search(lowered):
        return True
    return any(keyword in lowered for keyword in NEARSHORE_HABITAT_KEYWORDS)


def _point_segment_distance(
    px: float, py: float, x1: float, y1: float, x2: float, y2: float
) -> float:
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def _near_a_boundary_edge(lat: float, lon: float, buffer_degrees: float) -> bool:


def check_onland(
    lat: float,
    lon: float,
    *,
    habitat: str | None = None,
    buffer_degrees: float = DEFAULT_BUFFER_DEGREES,
) -> str:
    if country_code_for(lat, lon) is None:
        return "water"
    if habitat and is_nearshore_habitat_hint(habitat):
        return "ambiguous"
    if _near_a_boundary_edge(lat, lon, buffer_degrees):
        return "ambiguous"
    return "land"


@dataclass(frozen=True)
class OnLandSummary:
    land_count: int
    ambiguous_count: int


RECOMMENDED_FIELDS = ("minimumDepthInMeters", "maximumDepthInMeters")


def check_recommended_fields(header: list[str]) -> FindingsLog:
    log = FindingsLog()
    for name in RECOMMENDED_FIELDS:
        if name not in header:
            log.add(
                "OBIS_VALIDATOR_ISSUE",
                f"OBIS recommends {name!r}, which this archive does not have",
                severity="warning",
            )
    return log


def run_obis_validation(
    header: list[str],
    *,
    adjudications: dict[str, str] | None = None,
    issues_out: list[str] | None = None,
) -> FindingsLog:
    log = check_recommended_fields(header)
    adjudications = adjudications or {}

    if summary.land_count:
        if adjudications.get("ON_LAND") == "accepted":
            log.add(
                "STRUCTURAL_COST_DISCLOSED",
                f"OBIS ON_LAND: {summary.land_count} record(s), accepted as a disclosed "
                "structural cost",
                count=summary.land_count,
            )
        else:
            if issues_out is not None:
                issues_out.append("ON_LAND")
            log.add(
                count=summary.land_count,
            )
    if summary.ambiguous_count:
        log.add(
            "OBIS_VALIDATOR_ISSUE",
            f"OBIS ON_LAND: {summary.ambiguous_count} record(s) are ambiguous (a nearshore "
            "habitat hint or proximity to the boundary, not definite land)",
            severity="warning",
            count=summary.ambiguous_count,
        )
    return log
