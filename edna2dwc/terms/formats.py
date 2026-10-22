from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date, datetime, time, timedelta
import math
import re
from typing import Any
from zoneinfo import ZoneInfo

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
GBIF_TAXON_RANK_VOCABULARY = frozenset(
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

SYNONYMS_BY_TERM: dict[str, dict[str, str]] = {
    "taxonRank": {"phylum (division)": "phylum", "subphylum (subdivision)": "subphylum"},
}

VOCABULARY_BY_TERM: dict[str, frozenset[str]] = {
    "basisOfRecord": BASIS_OF_RECORD_VOCABULARY,
    "occurrenceStatus": OCCURRENCE_STATUS_VOCABULARY,
    "taxonRank": GBIF_TAXON_RANK_VOCABULARY,
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
    "annealingTemp": "number_with_unit",
    "scientificNameID": "uri",
    "taxonConceptID": "uri",
    "license": "uri",
    "identificationReferences": "pipe_list",
    "footprintWKT": "wkt",
    "DNA_sequence": "dna_sequence",
    "associatedSequences": "pipe_list",
    "recordedBy": "pipe_list",
}

FORMAT_DESCRIPTIONS = {
    "iso8601_date": "an ISO 8601 date such as 2021-06-01, or an interval of two",
    "decimal_degrees": "a number of decimal degrees within range",
    "iso3166_alpha2": "a two-letter ISO 3166 country code such as US",
    "controlled": "a value from its controlled vocabulary",
    "nonneg_number": "a number of zero or more, with no unit",
    "number_with_unit": "a number, optionally followed by its unit",
    "uri": "a URI such as https://... or urn:...",
    "wkt": "WKT geometry such as POINT(-123.1 49.2)",
    "dna_sequence": "a DNA sequence of IUPAC nucleotide letters",
    "pipe_list": "a list separated by ' | '",
}
SPELLED_OUT_VOCABULARY_SIZE = 12

_LAT_MAX = 90.0
_LON_MAX = 180.0

_ZONE = r"(Z|[+-]\d{2}(:?\d{2})?)"
_ISO_DATE_RE = re.compile(
    rf"^\d{{4}}(-\d{{2}}(-\d{{2}}(T\d{{2}}:\d{{2}}(:\d{{2}}(\.\d+)?)?{_ZONE}?)?)?)?$"
)
_LENIENT_ISO_DATE_RE = re.compile(
    r"^(?P<year>\d{4})"
    r"(-(?P<month>\d{1,2})"
    r"(-(?P<day>\d{1,2})"
    r"([T ](?P<hour>\d{1,2}):(?P<minute>\d{1,2})(?P<second>:\d{1,2}(\.\d+)?)?"
    rf"(?P<zone>{_ZONE})?)?)?)?$"
)
_DECIMAL_RE = re.compile(r"^-?\d+(\.\d+)?$")
_ISO3166_ALPHA2_RE = re.compile(r"^[A-Z]{2}$")
_DNA_RE = re.compile(r"[ACGTRYSWKMBDHVN]*[ACGT][ACGTRYSWKMBDHVN]*")
_NOT_IN_A_SEQUENCE_RE = re.compile(r"[\s.-]")
_URI_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:\S+$")
_NCBI_SCHEME_RE = re.compile(r"^NCBI:", re.IGNORECASE)
_NCBI_TAXID_CURIE_RE = re.compile(r"^NCBI:txid[1-9]\d*$")


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
        parts += f"T{match.group('hour').zfill(2)}:{match.group('minute').zfill(2)}"
        if second := match.group("second"):
            whole, _, fraction = second[1:].partition(".")
            parts += f":{whole.zfill(2)}" + (f".{fraction}" if fraction else "")
        parts += match.group("zone") or ""
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
        return bool(value)
    return value in vocabulary


def convert_controlled(
    value: str, *, vocabulary: frozenset[str] | None, synonyms: Mapping[str, str] | None = None
) -> str | None:
    value = value.strip()
    if vocabulary is None:
        return value or None
    if value in vocabulary:
        return value
    by_casefold = {v.casefold(): v for v in vocabulary}
    return by_casefold.get(value.casefold()) or (synonyms or {}).get(value.casefold())


def validate_nonneg_number(value: str) -> bool:
    if not _DECIMAL_RE.match(value):
        return False
    return float(value) >= 0


def convert_nonneg_number(value: str) -> str | None:
    value = value.strip()
    return value if validate_nonneg_number(value) else None


def validate_uri(value: str) -> bool:
    if _NCBI_SCHEME_RE.match(value):
        return bool(_NCBI_TAXID_CURIE_RE.match(value))
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
    return bool(_DNA_RE.fullmatch(value))


def convert_dna_sequence(value: str) -> str | None:
    candidate = _NOT_IN_A_SEQUENCE_RE.sub("", value).upper().replace("U", "T")
    return candidate if validate_dna_sequence(candidate) else None


def validate_pipe_list(value: str) -> bool:
    if not value or value.startswith(" | ") or value.endswith(" | "):
        return False
    return " || " not in value


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


def _local_stamp(local: str | date) -> date:
    if isinstance(local, datetime):
        return local.date() if local.time() == time() and local.tzinfo is None else local
    if isinstance(local, date):
        return local
    try:
        return date.fromisoformat(local)
    except ValueError:
        return datetime.fromisoformat(local)


def utc_from_local(local: str | date, *, lat: float, lon: float) -> str:
    stamp = _local_stamp(local)
    if not isinstance(stamp, datetime):
        return stamp.isoformat()
    if stamp.tzinfo is None:
        tz_name = TimezoneFinder().timezone_at(lat=lat, lng=lon)
        if tz_name is None:
            raise ValueError(f"no IANA time zone found for ({lat}, {lon})")
        stamp = stamp.replace(tzinfo=ZoneInfo(tz_name))
    return stamp.astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z")


def nad83_to_wgs84(lat: float, lon: float) -> tuple[float, float]:
    transformer = pyproj.Transformer.from_crs("NAD83", "WGS84", always_xy=True)
    new_lon, new_lat = transformer.transform(lon, lat)
    return new_lat, new_lon


def _identity_transform(value):
    return value


SINGLE_VALUE_TRANSFORMS: dict[str, Callable[[Any], Any]] = {
    "ddmm": ddmm_to_decimal,
    "decimal": _identity_transform,
    "excel_date": excel_serial_to_iso_date,
    "iso_date": _identity_transform,
    "none": _identity_transform,
}

PAIRED_TRANSFORMS = {
    "utc_from_local": utc_from_local,
    "nad83_to_wgs84": nad83_to_wgs84,
}


def describe_format(term: str, fmt: str) -> str:
    vocabulary = VOCABULARY_BY_TERM.get(term)
    if fmt == "controlled" and vocabulary and len(vocabulary) <= SPELLED_OUT_VOCABULARY_SIZE:
        return f"one of {', '.join(sorted(vocabulary))}"
    return FORMAT_DESCRIPTIONS[fmt]
