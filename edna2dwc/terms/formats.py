from __future__ import annotations

import math
import re

import pyproj
from timezonefinder import TimezoneFinder

BASIS_OF_RECORD_VOCABULARY = frozenset(
    {
        "MaterialEntity",
        "PreservedSpecimen",
        "FossilSpecimen",
        "LivingSpecimen",
        "MaterialSample",
        "Event",
        "HumanObservation",
        "MachineObservation",
        "Taxon",
        "Occurrence",
        "MaterialCitation",
    }
)
OCCURRENCE_STATUS_VOCABULARY = frozenset({"present", "absent"})
    {
        "domain",
        "superkingdom",
        "kingdom",
        "subkingdom",
        "infrakingdom",
        "superphylum",
        "phylum",
        "subphylum",
        "infraphylum",
        "superclass",
        "class",
        "subclass",
        "infraclass",
        "parvclass",
        "superlegion",
        "legion",
        "sublegion",
        "infralegion",
        "supercohort",
        "cohort",
        "subcohort",
        "infracohort",
        "magnorder",
        "superorder",
        "grandorder",
        "order",
        "suborder",
        "infraorder",
        "parvorder",
        "superfamily",
        "family",
        "subfamily",
        "infrafamily",
        "supertribe",
        "tribe",
        "subtribe",
        "infratribe",
        "suprageneric_name",
        "genus",
        "subgenus",
        "infragenus",
        "species_aggregate",
        "species",
        "subspecific_aggregate",
        "subspecies",
        "variety",
        "subvariety",
        "form",
        "subform",
        "cultivar_group",
        "cultivar",
        "strain",
        "other",
        "unranked",
    }
)

VOCABULARY_BY_TERM: dict[str, frozenset[str]] = {
    "basisOfRecord": BASIS_OF_RECORD_VOCABULARY,
    "occurrenceStatus": OCCURRENCE_STATUS_VOCABULARY,
}
FORMAT_BY_TERM: dict[str, str] = {
    "eventDate": "iso8601_date",
    "decimalLatitude": "decimal_degrees",
    "decimalLongitude": "decimal_degrees",
    "countryCode": "iso3166_alpha2",
    "basisOfRecord": "controlled",
    "occurrenceStatus": "controlled",
    "taxonRank": "controlled",
    "taxonomicStatus": "controlled",
    "seq_meth": "controlled",
    "otu_class_appr": "controlled",
    "organismQuantity": "nonneg_number",
    "sampleSizeValue": "nonneg_number",
    "coordinateUncertaintyInMeters": "nonneg_number",
    "minimumDepthInMeters": "nonneg_number",
    "maximumDepthInMeters": "nonneg_number",
    "ampliconSize": "nonneg_number",
    "scientificNameID": "uri",
    "taxonConceptID": "uri",
    "license": "uri",
    "footprintWKT": "wkt",
    "DNA_sequence": "dna_sequence",
    "associatedSequences": "pipe_list",
    "recordedBy": "pipe_list",
}

_LAT_MAX = 90.0
_LON_MAX = 180.0

_LENIENT_ISO_DATE_RE = re.compile(
    r"^(?P<year>\d{4})"
    r"(-(?P<month>\d{1,2})"
    r"(-(?P<day>\d{1,2})"
)
_DECIMAL_RE = re.compile(r"^-?\d+(\.\d+)?$")
_ISO3166_ALPHA2_RE = re.compile(r"^[A-Z]{2}$")


def _single_or_interval(value: str, validate_one) -> bool:
    if "/" in value:
        start, _, end = value.partition("/")
        return validate_one(start) and validate_one(end)
    return validate_one(value)


def validate_iso8601_date(value: str) -> bool:
    return bool(value) and _single_or_interval(value, lambda v: bool(_ISO_DATE_RE.match(v)))


def _zero_pad_iso_component(value: str) -> str:
    match = _LENIENT_ISO_DATE_RE.match(value)
    if not match:
        return value
    parts = match.group("year")
    if match.group("month"):
        parts += f"-{match.group('month').zfill(2)}"
    if match.group("day"):
        parts += f"-{match.group('day').zfill(2)}"
    if match.group("hour"):
    return parts


def convert_iso8601_date(value: str) -> str | None:
    value = value.strip()
    if "/" in value:
        start, _, end = value.partition("/")
        padded = f"{_zero_pad_iso_component(start.strip())}/{_zero_pad_iso_component(end.strip())}"
    else:
        padded = _zero_pad_iso_component(value)
    return padded if validate_iso8601_date(padded) else None


def validate_decimal_degrees(value: str, *, max_abs: float) -> bool:
    if not _DECIMAL_RE.match(value):
        return False
    return abs(float(value)) <= max_abs


def convert_decimal_degrees(value: str, *, max_abs: float) -> str | None:
    value = value.strip()
    return value if validate_decimal_degrees(value, max_abs=max_abs) else None


def validate_iso3166_alpha2(value: str, *, valid_codes: frozenset[str]) -> bool:
    return bool(_ISO3166_ALPHA2_RE.match(value)) and value in valid_codes


def convert_iso3166_alpha2(value: str, *, valid_codes: frozenset[str]) -> str | None:
    candidate = value.strip().upper()
    return candidate if validate_iso3166_alpha2(candidate, valid_codes=valid_codes) else None


def validate_controlled(value: str, *, vocabulary: frozenset[str] | None) -> bool:
    if vocabulary is None:
    return value in vocabulary


    value = value.strip()
    if vocabulary is None:
        return value or None
    if value in vocabulary:
        return value
    by_casefold = {v.casefold(): v for v in vocabulary}


def validate_nonneg_number(value: str) -> bool:
    if not _DECIMAL_RE.match(value):
        return False
    return float(value) >= 0


def convert_nonneg_number(value: str) -> str | None:
    value = value.strip()
    return value if validate_nonneg_number(value) else None


def validate_uri(value: str) -> bool:
    return bool(_URI_RE.match(value))


def convert_uri(value: str) -> str | None:
    value = value.strip()
    return value if validate_uri(value) else None


def validate_wkt(value: str) -> bool:
    return bool(re.match(r"^(POINT|LINESTRING|POLYGON|MULTIPOINT)\s*\(.+\)$", value.strip()))


def convert_wkt(value: str) -> str | None:
    value = value.strip()
    return value if validate_wkt(value) else None


def validate_dna_sequence(value: str) -> bool:


def convert_dna_sequence(value: str) -> str | None:


def validate_pipe_list(value: str) -> bool:
    if not value or value.startswith(" | ") or value.endswith(" | "):
        return False


def convert_pipe_list(value: str) -> str | None:
    items = [item.strip() for item in value.split("|") if item.strip()]
    return " | ".join(items) if items else None


def validate_number_with_unit(value: str) -> bool:
    return bool(_DECIMAL_RE.match(value))


def ddmm_to_decimal(x: float) -> float:
    sign = -1.0 if x < 0 else 1.0
    ax = abs(x)
    degrees = math.floor(ax / 100)
    minutes = ax % 100
    return sign * (degrees + minutes / 60)


_EXCEL_EPOCHS = {
    "1900": date(1899, 12, 30),
    "1904": date(1904, 1, 1),
}


def excel_serial_to_iso_date(serial: float, epoch: str = "1900") -> str:
    if epoch not in _EXCEL_EPOCHS:
        raise ValueError(f"epoch must be one of {sorted(_EXCEL_EPOCHS)}, got {epoch!r}")
    base = _EXCEL_EPOCHS[epoch]
    days = int(serial)
    if epoch == "1900" and 0 < days < 60:
        days += 1
    return (base + timedelta(days=days)).isoformat()




def nad83_to_wgs84(lat: float, lon: float) -> tuple[float, float]:
    transformer = pyproj.Transformer.from_crs("NAD83", "WGS84", always_xy=True)
    new_lon, new_lat = transformer.transform(lon, lat)
    return new_lat, new_lon


def _identity_transform(value):
    return value


    "ddmm": ddmm_to_decimal,
    "decimal": _identity_transform,
    "excel_date": excel_serial_to_iso_date,
    "iso_date": _identity_transform,
    "none": _identity_transform,
}
