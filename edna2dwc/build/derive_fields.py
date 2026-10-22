from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import math

from edna2dwc.build.sheets import LISTED_ROWS, RowsChanged
from edna2dwc.common.findings import ERROR, FindingsLog
from edna2dwc.common.table import (
    ROW,
    Table,
    column,
    from_rows,
    internal,
    literal,
    literals,
    lookup,
    matching,
)
from edna2dwc.common.text import first_few
from edna2dwc.conversion import artifacts
from edna2dwc.conversion.provenance import (
    ANSWER_COLUMNS,
    CONFIRMED,
    PROVENANCE,
    SheetRefused,
    refuse_unprovenanced,
)
from edna2dwc.taxonomy.unassigned import is_no_assignment, is_placeholder_taxon
from edna2dwc.terms.country_code import (
    NEARBY_COUNTRY_KM,
    Placement,
    place_in_country,
    valid_country_codes,
)
from edna2dwc.terms.formats import convert_iso3166_alpha2
from edna2dwc.terms.map_terms import source_gave, unless_given

PROPOSED_SAMPLES = 20
READS = "DNA sequence reads"
EXCLUSION_CODES = ("CONTROL_EXCLUDED", "HUMAN_EXCLUDED", "CONTAMINANT_EXCLUDED")

SAMPLE = internal("sampleID")
FEATURE = internal("featureID")
MARKER = internal("marker")
CLASS = internal("class")
TOTAL = internal("total")
RESULT = internal("result")
NUMBER = internal("number")
MAX_DECIMAL_PLACES = 18

Library = tuple[str, str]


def _library_name(key: Library) -> str:
    sample_id, marker = key
    return f"{sample_id}/{marker}" if marker else sample_id


def _quantity(total: Decimal) -> str:
    return (
        str(int(total)) if total == total.to_integral_value() else format(total.normalize(), "f")
    )


def _to_float(value: str) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _to_decimal(value: str) -> Decimal | None:
    try:
        number = Decimal(value.strip())
    except (AttributeError, InvalidOperation):
        return None
    return number if number.is_finite() else None


def _comparable_size(value: str) -> str:
    number = _to_float(value)
    return value if number is None else repr(number)


def total_reads(counts: list[tuple[str, str, int]], quantity_types: dict[str, str]) -> str:
    if not all(quantity_types.get(marker, READS) == READS for marker, _, _ in counts):
        return ""
    numbers = [(n, rows) for _, count, rows in counts if (n := _to_decimal(count)) is not None]
    return _quantity(sum((n * rows for n, rows in numbers), Decimal(0))) if numbers else ""


@dataclass(frozen=True)
class _Libraries:
    sample: str
    marker: str

    @classmethod
    def of(cls, table: Table, has_marker: bool) -> _Libraries:
        return cls(table.text("sampleID"), table.text("marker") if has_marker else "''")


def _read_totals(
    table: Table, libraries: _Libraries, quantity_types: dict[str, str], where: str = "TRUE"
) -> dict[Library, Decimal]:
    count = table.text("count")
    numbers = lookup(table, f"{table.name}_numbers", [count], {NUMBER: "VARCHAR"}, _fixed_point)
    (places,) = numbers.one(
        f"SELECT coalesce(max(length(split_part({NUMBER}, '.', 2))), 0) FROM {numbers.name}"
    )
    totals = table.rows(
        f"SELECT {libraries.sample}, {libraries.marker}, "
        f"sum({NUMBER}::DECIMAL(38, {min(places, MAX_DECIMAL_PLACES)})) "
        f"FROM {table.name} JOIN {numbers.name} ON {matching(numbers, [count])} "
        f"WHERE {where} AND {_quantity_type(table, quantity_types)} = {literal(READS)} "
        "GROUP BY ALL"
    )
    return {(sample, marker): total for sample, marker, total in totals if total is not None}


def _fixed_point(value: str) -> tuple[str | None]:
    number = _to_decimal(value)
    return (None if number is None else format(number, "f"),)


def _has_marker(table: Table) -> bool:
    (found,) = table.one(f"SELECT bool_or({table.text('marker')} <> '') FROM {table.name}")
    return bool(found)


def report_reads_excluded_from_totals(
    rows: Table, excluded: Table, quantity_types: dict[str, str]
) -> FindingsLog:
    log = FindingsLog()
    has_marker = _has_marker(rows)
    published = _read_totals(
        rows,
        _Libraries.of(rows, has_marker),
        quantity_types,
        where=f"NOT {source_gave(rows, 'sampleSizeValue')}",
    )
    removed = {
        key: total
        for key, total in _read_totals(
            excluded, _Libraries.of(excluded, has_marker), quantity_types
        ).items()
        if total and key in published
    }
    if removed:
        examples = [
            f"{_library_name(key)}: {_quantity(published[key] + removed[key])} sequenced, "
            f"{_quantity(published[key])} published"
            for key in sorted(removed)
        ]
        log.add(
            "SAMPLE_SIZE_AFTER_EXCLUSIONS",
            f"sampleSizeValue counts the reads published, after exclusions removed reads from "
            f"{len(removed)} library(s): {first_few(examples, 3)}",
            count=len(removed),
        )
    return log


def _marker_findings(rows: Table, has_marker: bool, has_totals: bool) -> FindingsLog:
    findings = FindingsLog()
    marker, sample = rows.text("marker"), rows.text("sampleID")
    if has_marker:
        blank, samples = rows.one(
            f"SELECT count(*), list(DISTINCT {sample}) FROM {rows.name} WHERE {marker} = ''"
        )
        if blank:
            findings.add(
                "MARKER_INCOMPLETE",
                f"{blank} row(s) leave marker blank while other rows set it, in "
                f"sampleID(s) {first_few(sorted(samples), 3)}. A blank marker is a missing "
                "value rather than a library, so each such row's sampleSizeValue is a total over "
                "the blank-marker rows alone, and no markers: answer reaches them: no marker "
                "constant, and no exclude_kingdoms scoped by a marker's target. Set the marker "
                "those rows were sequenced with",
                count=blank,
            )
    (multi_marker_samples,) = rows.one(
        f"SELECT count(*) FROM (SELECT {sample} FROM {rows.name} WHERE {marker} <> '' "
        f"GROUP BY 1 HAVING count(DISTINCT {marker}) > 1)"
    )
    if multi_marker_samples and has_totals:
        findings.add(
            "SAMPLE_SIZE_PER_MARKER",
            f"{multi_marker_samples} sampleID(s) have more than one marker. "
            "sampleSizeValue is the total for that marker's library",
            count=multi_marker_samples,
        )
    elif not has_marker and has_totals:
        findings.add(
            "SAMPLE_SIZE_UNGROUPED",
            "No marker column, so sampleSizeValue is a sum per sampleID. If this table "
            "merges several markers under one sampleID, set marker on every row, so that "
            "each library's total is the reads of that marker alone",
        )
    return findings


def _count_class(value: str) -> tuple[str]:
    number = _to_float(value)
    if number is None:
        return ("missing",)
    return ("present" if number > 0 else "zero",)


def _quantity_type(table: Table, quantity_types: dict[str, str]) -> str:
    cases = "".join(
        f"WHEN {literal(marker)} THEN {literal(kind)} " for marker, kind in quantity_types.items()
    )
    if not cases:
        return literal(READS)
    return f"CASE {table.text('marker')} {cases}ELSE {literal(READS)} END"


def check_zero_counts(table: Table, emit_absences: bool) -> FindingsLog:
    log = FindingsLog()
    count = f"try_cast(trim({table.text('count')}) AS DOUBLE)"
    zeros = 0 if emit_absences else table.count(f"isfinite({count}) AND {count} <= 0")
    if zeros:
        log.add(
            "ZERO_COUNTS_KEPT",
            f"{zeros} row(s) left after exclusions have a zero count, and a zero read count "
            "is not evidence of absence. Run edna2dwc assemble without --keep-zeros to drop "
            "them, or, for a targeted assay with a recorded limit of detection, set "
            "derive_fields.emit_absences in answers.yaml to publish them as absent",
            count=zeros,
        )
    return log


def status_and_quantities(
    rows: Table,
    name: str,
    *,
    quantity_types: dict[str, str] | None = None,
) -> tuple[Table, FindingsLog]:
    quantity_types = quantity_types or {}
    has_marker = _has_marker(rows)
    libraries = _Libraries.of(rows, has_marker)
    totals = _read_totals(rows, libraries, quantity_types)
    findings = _marker_findings(rows, has_marker, bool(totals))
    count = rows.text("count")
    classes = lookup(rows, f"{name}_classes", [count], {CLASS: "VARCHAR"}, _count_class)
    library_totals = from_rows(
        rows.con,
        f"{name}_totals",
        {SAMPLE: "VARCHAR", MARKER: "VARCHAR", TOTAL: "VARCHAR"},
        [(*key, _quantity(total)) for key, total in totals.items()],
    )
    counted = rows.view(
        f"{name}_counted",
        f"SELECT {rows.name}.*, {classes.name}.{CLASS}, {library_totals.name}.{TOTAL} "
        f"FROM {rows.name} JOIN {classes.name} ON {matching(classes, [count])} "
        f"LEFT JOIN {library_totals.name} ON {libraries.sample} = {library_totals.name}.{SAMPLE} "
        f"AND {libraries.marker} = {library_totals.name}.{MARKER}",
    )
    size, unit = counted.get("sampleSizeValue"), counted.get("sampleSizeUnit")
    size_given = source_gave(counted, "sampleSizeValue")
    takes_total = f"NOT {size_given} AND {TOTAL} IS NOT NULL"
    replaced = counted.star(
        "occurrenceStatus",
        "organismQuantity",
        "organismQuantityType",
        "sampleSizeValue",
        "sampleSizeUnit",
        CLASS,
        TOTAL,
    )
    status = f"CASE {CLASS} WHEN 'missing' THEN '' WHEN 'present' THEN 'present' ELSE 'absent' END"
    derived = counted.view(
        f"{name}_quantities",
        f"SELECT {replaced}, {unless_given(counted, 'occurrenceStatus', status)}, "
        f"{unless_given(counted, 'organismQuantity', count)}, "
        f"{unless_given(counted, 'organismQuantityType', _quantity_type(counted, quantity_types))}, "
        f"CASE WHEN {takes_total} THEN {TOTAL} ELSE {size} END AS {column('sampleSizeValue')}, "
        f"CASE WHEN {takes_total} THEN {literal(READS)} ELSE {unit} END "
        f"AS {column('sampleSizeUnit')} FROM {counted.name}",
    )
    missing_status, supplied_sizes = counted.one(
        f"SELECT count(*) FILTER (WHERE {CLASS} = 'missing'), "
        f"count(*) FILTER (WHERE {size_given}) FROM {counted.name}"
    )
    if missing_status:
        findings.add(
            "TERM_MISSING_PRIORITY",
            f"{missing_status} row(s) had a non-numeric or missing count, so occurrenceStatus "
            "was left blank",
            count=missing_status,
        )
    if supplied_sizes:
        findings.add(
            "SAMPLE_SIZE_SUPPLIED",
            f"{supplied_sizes} row(s) arrived with a sampleSizeValue, kept as supplied along "
            "with its sampleSizeUnit: this tool does not state the unit of a value it did "
            "not compute",
            count=supplied_sizes,
        )
    findings.findings += _check_one_denominator_per_library(derived, name, has_marker).findings
    findings.findings += _check_every_size_carries_its_unit(derived).findings
    return derived, findings


def _check_one_denominator_per_library(table: Table, name: str, has_marker: bool) -> FindingsLog:
    log = FindingsLog()
    size = table.text("sampleSizeValue")
    sizes = lookup(
        table, f"{name}_sizes", [size], {RESULT: "VARCHAR"}, lambda v: (_comparable_size(v),)
    )
    libraries = _Libraries.of(table, has_marker)
    disagreeing = sorted(
        table.rows(
            f"SELECT {libraries.sample}, {libraries.marker} FROM {table.name} "
            f"JOIN {sizes.name} ON {matching(sizes, [size])} WHERE {size} <> '' "
            f"GROUP BY 1, 2 HAVING count(DISTINCT {sizes.name}.{RESULT}) > 1"
        )
    )
    if disagreeing:
        log.add(
            "SAMPLE_SIZE_DISAGREEMENT",
            f"{len(disagreeing)} sequencing library(s) ship more than one sampleSizeValue: "
            f"{first_few([_library_name(key) for key in disagreeing], 3)}. One library is one "
            "denominator, so a reader computing a relative abundance gets a different answer "
            "depending on which row they read it from",
            count=len(disagreeing),
        )
    return log


def _check_every_size_carries_its_unit(table: Table) -> FindingsLog:
    log = FindingsLog()
    size, unit = table.text("sampleSizeValue"), table.text("sampleSizeUnit")
    unitless, samples = table.one(
        f"SELECT count(*), list(DISTINCT {table.text('sampleID')}) FROM {table.name} "
        f"WHERE {size} <> '' AND {unit} = ''"
    )
    if unitless:
        log.add(
            "TERM_PAIR_INCOMPLETE",
            f"{unitless} row(s) have a sampleSizeValue with no sampleSizeUnit, in "
            f"sampleID(s) {first_few(sorted(samples), 3)}. The number cannot be read without its "
            "unit, and this tool does not invent the unit of a value it did not compute. "
            "Supply sampleSizeUnit alongside sampleSizeValue in the source table",
            severity=ERROR,
            count=unitless,
        )
    return log


@dataclass(frozen=True)
class _Place:
    country_code: str | None = None
    outcome: str | None = None
    label: str | None = None
    footprint: str | None = None
    srs: str = ""

    def values(self) -> tuple:
        return tuple(vars(self).values())


def _placer() -> Callable[..., tuple]:
    placements: dict[tuple[float, float], Placement | None] = {}

    def place(lat_text: str, lon_text: str, given: str, country_given: str, datum: str):
        lat, lon = _to_float(lat_text), _to_float(lon_text)
        srs = datum.strip()
        if lat is None or lon is None:
            outcome = None if country_given == "true" else "without_coordinates"
            return _Place(outcome=outcome, srs=srs).values()
        if (lat, lon) not in placements:
            placements[(lat, lon)] = place_in_country(lat, lon)
        placement = placements[(lat, lon)]
        footprint = f"POINT ({lon} {lat})"
        if country_given == "true":
            code = convert_iso3166_alpha2(given, valid_codes=valid_country_codes())
            if code and placement and placement.distance_km == 0 and code != placement.iso_a2:
                label = f"({lat}, {lon}) is given {code} and lies in {placement.iso_a2}"
                return _Place(None, "contradicted", label, footprint, srs).values()
            return _Place(footprint=footprint, srs=srs).values()
        if placement is None:
            return _Place(None, "offshore", f"({lat}, {lon})", footprint, srs).values()
        if placement.distance_km:
            label = f"({lat}, {lon}) is {placement.distance_km:.1f} km from {placement.iso_a2}"
            return _Place(placement.iso_a2, "nearby", label, footprint, srs).values()
        return _Place(placement.iso_a2, footprint=footprint, srs=srs).values()

    return place


_PLACE_RESULTS = {internal(name): "VARCHAR" for name in vars(_Place())}


def country_and_footprint(rows: Table, name: str) -> tuple[Table, FindingsLog]:
    keys = [
        rows.text("decimalLatitude"),
        rows.text("decimalLongitude"),
        rows.text("countryCode"),
        f"{source_gave(rows, 'countryCode')}::VARCHAR",
        rows.text("geodeticDatum"),
    ]
    places = lookup(rows, f"{name}_places", keys, _PLACE_RESULTS, _placer())
    place = {name: f"{places.name}.{internal(name)}" for name in vars(_Place())}
    footprint = (
        f"CASE WHEN {place['footprint']} IS NOT NULL AND NOT {source_gave(rows, 'footprintWKT')} "
        f"THEN {place['footprint']} ELSE {rows.get('footprintWKT')} END"
    )
    srs = (
        f"CASE WHEN {place['srs']} <> '' AND coalesce({footprint}, '') <> '' "
        f"AND NOT {source_gave(rows, 'footprintSRS')} THEN {place['srs']} "
        f"ELSE {rows.get('footprintSRS')} END"
    )
    derived = rows.view(
        f"{name}_placed",
        f"SELECT {rows.star('countryCode', 'footprintWKT', 'footprintSRS')}, "
        f"coalesce({place['country_code']}, {rows.get('countryCode')}) "
        f"AS {column('countryCode')}, {footprint} AS {column('footprintWKT')}, "
        f"{srs} AS {column('footprintSRS')} FROM {rows.name} JOIN {places.name} "
        f"ON {matching(places, keys)}",
    )
    outcomes: dict[str, list[str]] = {}
    for outcome, label, found in rows.rows(
        f"SELECT {place['outcome']}, {place['label']}, count(*) FROM {rows.name} "
        f"JOIN {places.name} ON {matching(places, keys)} WHERE {place['outcome']} IS NOT NULL "
        "GROUP BY ALL"
    ):
        outcomes.setdefault(outcome, []).extend([label] * found)
    return derived, _country_findings(outcomes)


def _country_findings(outcomes: dict[str, list[str]]) -> FindingsLog:
    findings = FindingsLog()
    if without_coordinates := len(outcomes.get("without_coordinates", [])):
        findings.add(
            "TERM_MISSING_PRIORITY",
            f"countryCode: {without_coordinates} row(s) have no coordinates in a "
            "decimalLatitude/decimalLongitude, latitude/longitude or lat/lon column, so their "
            "countryCode was left blank",
            count=without_coordinates,
        )
    if offshore := outcomes.get("offshore"):
        findings.add(
            "TERM_MISSING_PRIORITY",
            f"countryCode: {len(offshore)} row(s) have coordinates more than "
            f"{NEARBY_COUNTRY_KM:g} km from every bundled land polygon (open water, or a "
            "disputed-status unit with no ISO code), so their countryCode was left blank: "
            f"{first_few(sorted(set(offshore)), 3)}",
            count=len(offshore),
        )
    if nearby := outcomes.get("nearby"):
        findings.add(
            "COUNTRY_CODE_FROM_NEARBY_COAST",
            f"countryCode: {len(nearby)} row(s) have coordinates in no bundled land polygon but "
            f"within {NEARBY_COUNTRY_KM:g} km of one, so each took the code of the nearest "
            f"country: {first_few(sorted(set(nearby)), 3)}. Check a point near a border or "
            "between two coasts",
            count=len(nearby),
        )
    if contradicted := outcomes.get("contradicted"):
        findings.add(
            "COUNTRY_CODE_CONTRADICTS_COORDINATES",
            f"{len(contradicted)} row(s) give a countryCode that the boundary set places in "
            "another country, and each was kept as given: "
            f"{first_few(sorted(set(contradicted)), 3)}. "
            "Check the coordinates and the code against the source",
            count=len(contradicted),
        )
    return findings


def resolve_conflicting_timestamps(
    rows: Table, name: str, *, col_a: str, col_b: str
) -> tuple[Table, FindingsLog]:
    findings = FindingsLog()
    a, b = rows.text(col_a), rows.text(col_b)
    conflict = f"{a} <> '' AND {b} <> '' AND {a} <> {b}"
    if conflicts := rows.count(conflict):
        findings.add(
            "TIMESTAMP_CONFLICT",
            f"{conflicts} row(s) have disagreeing {col_a}/{col_b} timestamps",
            count=conflicts,
        )
    if rows.has("verbatimEventDate"):
        return rows, findings
    stamps = lookup(
        rows,
        f"{name}_stamps",
        [a, b],
        {RESULT: "VARCHAR"},
        lambda first, second: (f"{col_a}={first!r} vs {col_b}={second!r}",),
    )
    disclosed = rows.view(
        f"{name}_timestamps",
        f"SELECT {rows.name}.*, CASE WHEN {conflict} THEN {stamps.name}.{RESULT} END "
        f"AS {column('verbatimEventDate')} FROM {rows.name} "
        f"JOIN {stamps.name} ON {matching(stamps, [a, b])}",
    )
    return disclosed, findings


def _published_at(row: dict[str, str]) -> str:
    rank = (row.get("taxonRank") or "").lower()
    return " ".join(part for part in (rank, row.get("scientificName") or "") if part)


def _generalization(row: dict[str, str]) -> str:
    path = row.get("resolution_path")
    placeholder = is_placeholder_taxon(row.get("scientificName") or "")
    if path == "rank_backoff":
        return (
            "No register confirmed the name the source gave for this record, so it is "
            f"published at {_published_at(row)}, the deepest rank of its source lineage "
            "that resolved."
        )
    if path == "compound_common_ancestor" and not placeholder:
        return (
            "The source named more than one taxon for this record, so it is published at "
            f"{_published_at(row)}, the deepest rank those names share."
        )
    if not placeholder:
        return ""
    if is_no_assignment(row.get("verbatimIdentification") or ""):
        return (
            "The source recorded no taxonomic assignment for this record, so it has the "
            "placeholder taxon that OBIS and GBIF publish for an unassigned sequence; the "
            "source's wording is kept in verbatimIdentification."
        )
    remarks = " (see identificationRemarks)" if row.get("identificationRemarks") else ""
    return (
        "This record could not be confidently identified below a generic placeholder "
        f"taxon{remarks}."
    )


_GENERALIZATION_INPUTS = (
    "resolution_path",
    "scientificName",
    "taxonRank",
    "verbatimIdentification",
    "identificationRemarks",
)


def disclose_generalizations(rows: Table, name: str) -> Table:
    keys = [rows.text(input_name) for input_name in _GENERALIZATION_INPUTS]
    generalizations = lookup(
        rows,
        f"{name}_generalizations",
        keys,
        {RESULT: "VARCHAR"},
        lambda *values: (_generalization(dict(zip(_GENERALIZATION_INPUTS, values, strict=True))),),
    )
    found = f"nullif({generalizations.name}.{RESULT}, '')"
    return rows.view(
        f"{name}_disclosed",
        f"SELECT {rows.star('dataGeneralizations')}, "
        f"{unless_given(rows, 'dataGeneralizations', found)} "
        f"FROM {rows.name} JOIN {generalizations.name} ON {matching(generalizations, keys)}",
    )


def _sign(value: str) -> tuple[str | None]:
    number = _to_float(value)
    if number is None or number == 0.0:
        return (None,)
    return ("+" if number > 0 else "-",)


def check_coordinate_signs(table: Table) -> FindingsLog:
    findings = FindingsLog()
    for axis in ("decimalLatitude", "decimalLongitude"):
        value = table.text(axis)
        signs = lookup(table, f"signs_{axis}", [value], {RESULT: "VARCHAR"}, _sign)
        positive, negative = table.one(
            f"SELECT count(*) FILTER (WHERE {RESULT} = '+'), "
            f"count(*) FILTER (WHERE {RESULT} = '-') "
            f"FROM {table.name} JOIN {signs.name} ON {matching(signs, [value])}"
        )
        signed = positive + negative
        if signed < 5 or positive == 0 or negative == 0:
            continue
        majority_positive = positive >= negative
        minority = negative if majority_positive else positive
        if minority / signed < 0.2:
            findings.add(
                "COORDINATE_SIGN_SUSPECT",
                f"{axis}: {minority} row(s) have a sign contradicting the dataset's "
                f"{'positive' if majority_positive else 'negative'}-majority convention",
                count=minority,
            )
    return findings


CHANGED = internal("changed")
MATCHED = internal("matched")
LATEST = internal("latest")
DERIVED_VALUES_SHEET = artifacts.CONFIRMED_DIR / "derived_values.tsv"


@dataclass
class Corrections:
    changes: Table | None = None
    to_source: list[str] = field(default_factory=list)
    to_derived: list[str] = field(default_factory=list)
    rows: RowsChanged = field(default_factory=RowsChanged)
    findings: FindingsLog = field(default_factory=FindingsLog)


def _refuse_unknown_columns(
    named: list[str], derived: Table, terms_of_source: dict[str, str]
) -> None:
    unknown = sorted(c for c in named if not derived.has(c))
    if not unknown:
        return
    renames = [f"name {c!r} as {terms_of_source[c]}" for c in unknown if c in terms_of_source]
    raise SheetRefused(
        f"{DERIVED_VALUES_SHEET.as_posix()}: names column(s) "
        f"{', '.join(map(repr, unknown))}, which "
        f"{(artifacts.PROPOSED_DIR / 'derived_values.tsv').as_posix()} doesn't have, because it "
        f"names each value by its term{': ' + '; '.join(renames) if renames else ''}. Correct "
        "the header, then build again"
    )


def _stripped(text: str) -> str:
    return f"trim({text}, ' \t\r\n')"


def _library(sample: str, feature: str) -> str:
    return f"CASE WHEN {feature} <> '' THEN {sample} || '/' || {feature} ELSE {sample} END"


def _compared(sheet: Table, derived: Table, values: list[str]) -> Table:
    sample, feature = derived.text("sampleID"), derived.text("featureID")
    latest = (
        f"SELECT {sample} AS {SAMPLE}, {feature} AS {FEATURE}, "
        + ", ".join(
            f"coalesce(CAST({derived.get(c)} AS VARCHAR), '') AS {column(c)}" for c in values
        )
        + f" FROM {derived.name} QUALIFY row_number() OVER "
        f"(PARTITION BY {sample}, {feature} ORDER BY {ROW} DESC) = 1"
    )
    given = {c: f"coalesce({sheet.get(c, 's')}, '')" for c in values}
    changed = {
        c: f"CASE WHEN {given[c]} <> '' AND {given[c]} <> {LATEST}.{column(c)} THEN {given[c]} END"
        for c in values
    }
    any_changed = " OR ".join(f"{expression} IS NOT NULL" for expression in changed.values())
    return sheet.save(
        "derived_values_compared",
        f"SELECT s.{ROW}, {sheet.text('sampleID', 's')} AS {SAMPLE}, "
        f"{sheet.text('featureID', 's')} AS {FEATURE}, "
        f"{LATEST}.{SAMPLE} IS NOT NULL AS {MATCHED}, ({any_changed or 'FALSE'}) AS {CHANGED}, "
        f"{_stripped(sheet.text(PROVENANCE, 's'))} AS {column(PROVENANCE)}, "
        f"{_stripped(sheet.text(CONFIRMED, 's'))} AS {column(CONFIRMED)}"
        + "".join(f", {expression} AS {column(c)}" for c, expression in changed.items())
        + f" FROM {sheet.name} s LEFT JOIN ({latest}) {LATEST} "
        f"ON {LATEST}.{SAMPLE} = {sheet.text('sampleID', 's')} "
        f"AND {LATEST}.{FEATURE} = {sheet.text('featureID', 's')}",
    )


def read_corrections(
    sheet: Table | None,
    source: Table,
    derived: Table,
    terms_of_source: dict[str, str] | None = None,
) -> Corrections:
    if sheet is None or not sheet.count():
        return Corrections()
    values = [c for c in sheet.columns if c not in ("sampleID", "featureID", *ANSWER_COLUMNS)]
    _refuse_unknown_columns(values, derived, terms_of_source or {})
    compared = _compared(sheet, derived, values)
    library = _library(SAMPLE, FEATURE)
    unattributed, first_unattributed = compared.first(
        library, f"{MATCHED} AND {CHANGED} AND {column(PROVENANCE)} = ''", LISTED_ROWS
    )
    refuse_unprovenanced(DERIVED_VALUES_SHEET, first_unattributed, total=unattributed)
    changes = compared.save(
        "derived_values_changes",
        f"SELECT * FROM {compared.name} WHERE {MATCHED} AND {CHANGED} "
        f"QUALIFY row_number() OVER (PARTITION BY {SAMPLE}, {FEATURE} ORDER BY {ROW} DESC) = 1",
    )
    counts = ", ".join(f"count({column(c)})" for c in values) or "count(*)"
    replaced = dict(zip(values, changes.one(f"SELECT {counts} FROM {changes.name}")))
    corrections = Corrections(
        changes,
        [c for c in values if replaced[c] and source.has(c)],
        [c for c in values if replaced[c] and not source.has(c)],
        _rows_changed(changes, library),
    )
    _report_corrections(corrections, replaced, compared, library)
    return corrections


def _rows_changed(changes: Table, library: str) -> RowsChanged:
    unconfirmed, first_unconfirmed = changes.first(
        library, f"{column(CONFIRMED)} = ''", LISTED_ROWS
    )
    return RowsChanged(changes.count(), unconfirmed, first_unconfirmed or [])


def _report_corrections(
    corrections: Corrections, replaced: dict[str, int], compared: Table, library: str
) -> None:
    if applied := sum(replaced.values()):
        corrections.findings.add(
            "DERIVED_VALUE_REPLACED",
            f"{applied} value(s) in {', '.join(sorted(c for c, n in replaced.items() if n))} were "
            "taken from confirmed/derived_values.tsv in place of the derived value, and the "
            "values derived from them follow",
            count=applied,
        )
    unmatched = compared.count(f"NOT {MATCHED}")
    if unmatched:
        first_unmatched = [
            name
            for (name,) in compared.rows(
                f"SELECT {library} FROM {compared.name} WHERE NOT {MATCHED} "
                f"ORDER BY {SAMPLE}, {FEATURE} LIMIT 3"
            )
        ]
        corrections.findings.add(
            "DERIVED_CONFIRMED_UNMATCHED",
            f"{unmatched} row(s) of confirmed/derived_values.tsv match no sampleID and "
            f"featureID in this table, so they settle nothing: "
            f"{first_few(first_unmatched, 3, unmatched)}. Remove each "
            "row, or correct its sampleID and featureID, then build again",
            count=unmatched,
        )


def _with_changes(table: Table, changes: Table | None, changed: list[str], name: str) -> Table:
    if changes is None or not changed:
        return table
    replace = ", ".join(
        f"coalesce({changes.name}.{column(c)}, {table.name}.{column(c)}) AS {column(c)}"
        for c in changed
        if table.has(c)
    )
    added = "".join(f", {changes.name}.{column(c)}" for c in changed if not table.has(c))
    return table.view(
        name,
        f"SELECT {table.name}.* {f'REPLACE ({replace})' if replace else ''}{added} "
        f"FROM {table.name} LEFT JOIN {changes.name} "
        f"ON {table.text('sampleID', table.name)} = {changes.name}.{SAMPLE} "
        f"AND {table.text('featureID', table.name)} = {changes.name}.{FEATURE}",
    )


@dataclass
class DerivedFields:
    table: Table
    proposal: Table
    findings: FindingsLog
    rows: RowsChanged = field(default_factory=RowsChanged)
    corrected: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class Derivation:
    excluded: Table
    quantity_types: dict[str, str] = field(default_factory=dict)

    def run(self, source: Table, name: str) -> tuple[Table, FindingsLog]:
        log = report_reads_excluded_from_totals(source, self.excluded, self.quantity_types)
        table, found = status_and_quantities(source, name, quantity_types=self.quantity_types)
        log.findings += found.findings
        table = table.save(f"{name}_quantified", f"SELECT * FROM {table.name}")
        table, found = country_and_footprint(table, name)
        log.findings += found.findings
        table = table.save(f"{name}_placed_table", f"SELECT * FROM {table.name}")
        disclosed = disclose_generalizations(table, name)
        return disclosed.save(f"{name}_derived", f"SELECT * FROM {disclosed.name}"), log


def _proposal(derived: Table) -> Table:
    sample = derived.text("sampleID")
    samples = sorted(
        found for (found,) in derived.rows(f"SELECT DISTINCT {sample} FROM {derived.name}")
    )[:PROPOSED_SAMPLES]
    blank_columns = ", ".join(f"'' AS {column(name)}" for name in ANSWER_COLUMNS)
    return derived.view(
        "derived_proposal",
        f"SELECT {derived.star(*ANSWER_COLUMNS)}, {blank_columns} FROM {derived.name} "
        f"WHERE {sample} IN {literals(samples)}",
    )


def derive(
    rows: Table,
    derivation: Derivation,
    confirmed: Table | None = None,
    terms_of_source: dict[str, str] | None = None,
) -> DerivedFields:
    proposed, log = derivation.run(rows, "proposed")
    corrections = read_corrections(confirmed, rows, proposed, terms_of_source)
    derived = proposed
    if corrections.to_source:
        derived, log = derivation.run(
            _with_changes(rows, corrections.changes, corrections.to_source, "corrected_source"),
            "corrected",
        )
    published = _with_changes(derived, corrections.changes, corrections.to_derived, "published")
    if published is not derived:
        published = published.save("derived", f"SELECT * FROM {published.name}")
    log = FindingsLog(log.findings + corrections.findings.findings)
    log.findings.extend(check_coordinate_signs(published).findings)
    corrected = {*corrections.to_source, *corrections.to_derived}
    return DerivedFields(published, _proposal(proposed), log, corrections.rows, corrected)
