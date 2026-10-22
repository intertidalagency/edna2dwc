from __future__ import annotations

from dataclasses import dataclass
import math
import re

from edna2dwc.common.findings import FindingsLog
from edna2dwc.common.table import ROW, Table, internal, literal, lookup, matching
from edna2dwc.common.text import first_few
from edna2dwc.terms.country_code import candidate_polygons_for, country_code_for

CLASSIFICATION = internal("classification")
LABEL = internal("label")

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
    return any(
        _point_segment_distance(lon, lat, *ring[i - 1], *ring[i]) <= buffer_degrees
        for polygon in candidate_polygons_for(lat, lon)
        for ring in polygon.rings
        for i in range(len(ring))
    )


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
    land_samples: tuple[str, ...] = ()


def _placed(lat_text: str, lon_text: str, habitat: str) -> tuple[str | None, str]:
    try:
        lat, lon = float(lat_text), float(lon_text)
    except ValueError:
        return None, ""
    return check_onland(lat, lon, habitat=habitat), f"{lat},{lon}"


def check_onland_for_rows(table: Table) -> OnLandSummary:
    latitude, longitude = table.text("decimalLatitude"), table.text("decimalLongitude")
    keys = [latitude, longitude, table.text("habitat")]
    placed = lookup(
        table.view(
            "onland_candidates",
            f"SELECT * FROM {table.name} WHERE {latitude} <> '' AND {longitude} <> ''",
        ),
        "onland",
        keys,
        {CLASSIFICATION: "VARCHAR", LABEL: "VARCHAR"},
        _placed,
    )
    classification = f"{placed.name}.{CLASSIFICATION}"
    sample = (
        f"coalesce(nullif({table.text('materialSampleID')}, ''), "
        f"nullif({table.text('eventID')}, ''), {placed.name}.{LABEL})"
    )
    land_count, ambiguous_count, land_samples = table.one(
        f"SELECT count(*) FILTER (WHERE {classification} = 'land'), "
        f"count(*) FILTER (WHERE {classification} = 'ambiguous'), "
        f"list(DISTINCT {sample}) FILTER (WHERE {classification} = 'land') "
        f"FROM {table.name} JOIN {placed.name} ON {matching(placed, keys)}"
    )
    return OnLandSummary(
        land_count=land_count,
        land_samples=tuple(sorted(land_samples or [])),
        ambiguous_count=ambiguous_count,
    )


RECOMMENDED_FIELDS = ("minimumDepthInMeters", "maximumDepthInMeters")
WORMS_LSID_PREFIX = "urn:lsid:marinespecies.org:taxname:"


def check_names_tie_to_worms(table: Table) -> FindingsLog:
    log = FindingsLog()
    name_id = table.text("scientificNameID")
    elsewhere, first = table.one(
        f"SELECT count(*), arg_min({name_id}, {ROW}) FROM {table.name} "
        f"WHERE {name_id} <> '' AND NOT starts_with({name_id}, {literal(WORMS_LSID_PREFIX)})"
    )
    if elsewhere:
        log.add(
            "OBIS_VALIDATOR_ISSUE",
            f"OBIS NO_MATCH: {elsewhere} record(s) have a scientificNameID that isn't a "
            f"WoRMS LSID, such as {first}, because only the GBIF backbone resolved "
            "their name. OBIS keeps only records it can tie to WoRMS, so it drops these unless "
            "its own name match finds them. GBIF publishes them either way",
            severity="warning",
            count=elsewhere,
        )
    return log


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
    table: Table,
    *,
    adjudications: dict[str, str] | None = None,
    issues_out: list[str] | None = None,
) -> FindingsLog:
    log = check_recommended_fields(header)
    log.findings.extend(check_names_tie_to_worms(table).findings)
    adjudications = adjudications or {}

    summary = check_onland_for_rows(table)
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
                "ADJUDICATION_NEEDED",
                f"OBIS ON_LAND: {summary.land_count} record(s), in sample(s) "
                f"{first_few(summary.land_samples, 5)}, fall on the bundled land "
                "boundary set with no nearshore habitat hint. Shoreline and intertidal "
                "sampling puts real records on land, so this is a judgment call rather than "
                "necessarily a defect: to accept it, add ON_LAND: {status: accepted, provenance: "
                "<why the records are right>, confirmed: <the person's reply>} under "
                "adjudications: in answers.yaml, or correct the "
                "coordinates",
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
