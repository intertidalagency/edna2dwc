from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, field
import difflib
import re

from edna2dwc.common.findings import FindingsLog
from edna2dwc.common.table import ROW, Table, internal, is_json_object, literal, lookup, matching
from edna2dwc.common.table import column as identifier
from edna2dwc.conversion.provenance import ANSWER_COLUMNS
from edna2dwc.dwca import emof
from edna2dwc.terms import formats
from edna2dwc.terms.country_code import valid_country_codes
from edna2dwc.terms.dynamic_properties import BLOB, DynamicProperties, value_column
from edna2dwc.terms.dynamic_properties import COLUMN as DYNAMIC_PROPERTIES

RESULT = internal("result")
FOLDED_TARGETS = (DYNAMIC_PROPERTIES, emof.EMOF_TARGET)

_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")


JOINED_FIELDS = (
    "scientificName",
    "scientificNameID",
    "taxonRank",
    "scientificNameAuthorship",
    "taxonomicStatus",
    "taxonConceptID",
    "kingdom",
    "phylum",
    "class",
    "order",
    "family",
    "genus",
    "resolution_path",
)


def _normalize(header: str) -> str:
    return _NORMALIZE_RE.sub("", header.casefold())


def _sanitize_field(value: str) -> str:
    return value.replace("\t", " ").replace("\r", " ").replace("\n", " ")


_INTERNAL_BOOKKEEPING_COLUMNS = frozenset(
    {
        "lineage_key",
        "resolution_path",
        "authority",
        "provenance",
        "confirmed",
        "ncbi_taxid",
        "source_taxon_id",
    }
)

ALIAS_TABLE: dict[str, tuple[str, ...]] = {
    "materialSampleID": ("sample_id", "sample_name", "biosample"),
    "eventID": ("event_id",),
    "locationID": (
        "site",
        "location",
        "station",
        "site_name",
        "sampling_site",
        "station_id",
        "station_name",
    ),
    "decimalLatitude": ("latitude", "lat", "decimal_lat", "degrees_latitude", "lat_dd"),
    "decimalLongitude": ("longitude", "lon", "long", "decimal_lon", "degrees_longitude", "lon_dd"),
    "eventDate": ("date", "collection_date", "sample_date", "sampling_date"),
    "eventTime": ("time", "collection_time", "sample_time", "sampling_time"),
    "minimumDepthInMeters": ("depth", "depth_m", "sampling_depth"),
    "maximumDepthInMeters": (),
    "recordedBy": ("collector", "collected_by", "sampled_by", "recorded_by"),
    "samplingProtocol": ("protocol", "method", "sampling_method"),
    "habitat": ("habitat_type", "microhabitat"),
    "verbatimIdentification": ("taxonomy", "classification", "raw_taxonomy"),
    "DNA_sequence": (
        "sequence",
        "rep_seq",
        "representative_sequence",
        "asv_sequence",
        "otu_sequence",
    ),
}

_MATCH_STRENGTH = {"exact": 3, "case_insensitive": 2, "alias": 1}


@dataclass
class MappingProposal:
    source_column: str
    target: str
    basis: str
    provenance: str = ""
    confirmed: str = ""
    measurement: str = ""


def propose_mapping(
    header: list[str],
    terms_table: dict,
    *,
    written_later: frozenset[str] = frozenset(),
    settled: frozenset[str] = frozenset(),
) -> tuple[list[MappingProposal], FindingsLog]:
    term_names = {name for name in terms_table if not name.startswith("_")}
    normalized_terms = {_normalize(name): name for name in term_names}
    normalized_aliases: dict[str, str] = {}
    for target, aliases in ALIAS_TABLE.items():
        for alias in aliases:
            normalized_aliases[_normalize(alias)] = target

    proposals = []
    target_claims: dict[str, list[tuple[str, str]]] = {}
    for column in header:
        if column in _INTERNAL_BOOKKEEPING_COLUMNS:
            proposals.append(MappingProposal(column, "", "internal"))
            continue
        if column in term_names:
            proposals.append(MappingProposal(column, column, "exact"))
            target_claims.setdefault(column, []).append((column, "exact"))
            continue
        normalized = _normalize(column)
        if normalized in normalized_terms:
            target = normalized_terms[normalized]
            proposals.append(MappingProposal(column, target, "case_insensitive"))
            target_claims.setdefault(target, []).append((column, "case_insensitive"))
            continue
        if normalized in normalized_aliases:
            target = normalized_aliases[normalized]
            proposals.append(MappingProposal(column, target, "alias"))
            target_claims.setdefault(target, []).append((column, "alias"))
            continue
        proposals.append(MappingProposal(column, "", "unmapped"))

    collisions = FindingsLog()
    by_column = {p.source_column: p for p in proposals}
    for target, claims in target_claims.items():
        if len(claims) < 2:
            continue
        ranked = sorted(claims, key=lambda c: _MATCH_STRENGTH[c[1]], reverse=True)
        winner_column, winner_basis = ranked[0]
        for column, basis in ranked[1:]:
            by_column[column].target = ""
            by_column[column].basis = "ambiguous"
            if column in settled:
                continue
            collisions.add(
                "TERM_TARGET_COLLISION",
                f"{column!r} and {winner_column!r} both proposed {target!r}; kept "
                f"{winner_column!r} ({winner_basis}), rerouted {column!r} for review",
            )
    for proposal in proposals:
        if proposal.target in written_later:
            proposal.target, proposal.basis = "", "internal"

    return proposals, collisions


CONSTANT_SOURCE_COLUMN = "(constant)"
MAPPING_COLUMNS = ("source_column", "target", "basis")
MEASUREMENT_COLUMN = "measurement"
MEASUREMENT_BASIS = "measurement"
CONSTANT_BASIS = "constant"


def propose_measurements(proposals: list[MappingProposal], measured: dict[str, str]) -> None:
    for proposal in proposals:
        if proposal.basis == "unmapped" and proposal.source_column in measured:
            proposal.target = emof.EMOF_TARGET
            proposal.basis = MEASUREMENT_BASIS
            proposal.measurement = measured[proposal.source_column]


def routed_to(proposals: list[MappingProposal], target: str) -> frozenset[str]:
    return frozenset(p.source_column for p in proposals if p.target == target)


def marker_constant_source_column(marker: str) -> str:
    return f"(constant {marker})" if marker else CONSTANT_SOURCE_COLUMN


def is_constant_row(source_column: str) -> bool:
    return source_column.startswith(CONSTANT_SOURCE_COLUMN[:-1])


def review_order(proposals: list[MappingProposal]) -> list[MappingProposal]:
    return sorted(
        proposals,
        key=lambda p: (
            0 if p.basis in ("ambiguous", "unmapped", MEASUREMENT_BASIS) else 1,
            p.source_column,
        ),
    )


def review_findings(
    proposals: list[MappingProposal], settled: frozenset[str] = frozenset()
) -> FindingsLog:
    log = FindingsLog()
    for p in proposals:
        if p.basis == "ambiguous" and p.source_column not in settled:
            log.add(
                "TERM_AMBIGUOUS",
                f"{p.source_column!r}: no confident target, so it goes to dynamicProperties "
                "until confirmed/term_mapping.tsv names its term",
            )
    return log


def write_mapping_tsv(proposals: list[MappingProposal]) -> str:
    lines = ["\t".join((*MAPPING_COLUMNS, *ANSWER_COLUMNS, MEASUREMENT_COLUMN))]
    for p in review_order(proposals):
        fields = (p.source_column, p.target, p.basis, p.provenance, p.confirmed, p.measurement)
        lines.append("\t".join(_sanitize_field(field) for field in fields))
    return "\n".join(lines) + "\n"


def read_mapping_tsv(text: str) -> list[MappingProposal]:
    proposals = []
    positions: dict[str, int] = {}
    width = 0
    for i, line in enumerate(text.split("\n"), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = line.split("\t")
        if not positions:
            optional = (*ANSWER_COLUMNS, MEASUREMENT_COLUMN)
            if sorted(name for name in fields if name not in optional) != sorted(MAPPING_COLUMNS):
                raise ValueError(
                    f"term_mapping.tsv line {i}: expected the header "
                    f"{', '.join(MAPPING_COLUMNS)} in any order, and optionally "
                    f"{' and '.join(optional)}, got {line!r}"
                )
            positions = {
                name: fields.index(name)
                for name in (*MAPPING_COLUMNS, *ANSWER_COLUMNS)
                if name in fields
            }
            width = len(fields)
            continue
        if len(fields) != width:
            raise ValueError(
                f"term_mapping.tsv line {i}: expected {width} tab-separated fields, "
                f"one per header column, got {len(fields)}: {line!r}"
            )
        proposals.append(
            MappingProposal(**{name: fields[position] for name, position in positions.items()})
        )
    return proposals


def _derived_column_rows(
    proposals: list[MappingProposal], header: list[str], terms_table: dict
) -> list[MappingProposal]:
    proposed = {p.source_column for p in proposals}
    derived = [column for column in header if column not in proposed]
    fresh, _collisions = propose_mapping(derived, terms_table)
    return [p for p in fresh if p.basis in ("exact", "internal")]


def merge_constant_rows(
    proposals: list[MappingProposal],
    constants: dict[str, tuple[str, str]],
    marker_constants: dict[str, dict[str, tuple[str, str]]] | None = None,
) -> list[MappingProposal]:
    rows = {(CONSTANT_SOURCE_COLUMN, term): tag for term, (_value, tag) in constants.items()}
    for marker, by_term in (marker_constants or {}).items():
        column = marker_constant_source_column(marker)
        rows.update({(column, term): tag for term, (_value, tag) in by_term.items()})
    kept = [p for p in proposals if (p.source_column, p.target) not in rows]
    kept.extend(
        MappingProposal(column, term, CONSTANT_BASIS, tag)
        for (column, term), tag in sorted(rows.items())
    )
    return kept


@dataclass
class ApplyMappingResult:
    table: Table
    dynamic: DynamicProperties
    findings: FindingsLog = field(default_factory=FindingsLog)
    unconvertible: list[str] = field(default_factory=list)
    applied_constants: dict[str, tuple[str, str]] = field(default_factory=dict)
    applied_marker_constants: dict[str, dict[str, tuple[str, str]]] = field(default_factory=dict)


CONVERTED = "converted"
FAILED = "failed"


def unconvertible(term: str) -> str:
    return internal(f"unconvertible {term}")


def source_gave(table: Table, term: str) -> str:
    flag = unconvertible(term)
    failed = f" OR coalesce({flag}, FALSE)" if table.holds(flag) else ""
    return f"({table.text(term)} <> ''{failed})"


def unless_given(table: Table, term: str, derived: str) -> str:
    return (
        f"CASE WHEN {source_gave(table, term)} THEN {table.get(term)} ELSE {derived} END "
        f"AS {identifier(term)}"
    )


def _assign(current: str | None, value: str) -> str:
    if current is None:
        return value
    return (
        f"CASE WHEN {value} <> '' OR coalesce({current}, '') = '' THEN {value} ELSE {current} END"
    )


def _set_default(current: str | None, value: str, condition: str) -> str:
    unset = "TRUE" if current is None else f"coalesce({current}, '') = ''"
    return f"CASE WHEN {unset} AND {condition} THEN {value} ELSE {current or 'NULL'} END"


@dataclass(frozen=True)
class _Conversions:
    table: Table
    columns: list[str]
    targets: dict[str, str]

    def converted(self, name: str) -> str:
        return internal(f"{CONVERTED}{self.columns.index(name)}")

    def failed(self, name: str) -> str:
        return internal(f"{FAILED}{self.columns.index(name)}")


def _converted(table: Table, i: int, name: str, target: str, term_format: str) -> Table:
    return lookup(
        table,
        f"converted_{i}",
        [table.text(name)],
        {RESULT: "VARCHAR"},
        lambda value: (_convert_value(value, term_format, target) if value else value,),
        keep=lambda values, converted: converted != values,
    )


def _convert(table: Table, mapped: dict[str, MappingProposal], terms_table: dict) -> _Conversions:
    columns = sorted(mapped)
    unchanged, changed, joins, sources = [], [], [], []
    for i, name in enumerate(columns):
        target = mapped[name].target
        term_format = terms_table.get(target, {}).get("format")
        found = _converted(table, i, name, target, term_format) if term_format else None
        if found is None or not found.count():
            unchanged.append(
                f"{table.text(name, 'row')} AS {internal(f'{CONVERTED}{i}')}, "
                f"FALSE AS {internal(f'{FAILED}{i}')}"
            )
            continue
        value = table.text(name, "source")
        result, key = f"{found.name}.{RESULT}", f"{found.name}.{internal(f'converted_{i}_key0')}"
        changed.append(
            f"CASE WHEN {key} IS NULL THEN {value} ELSE coalesce({result}, '') END "
            f"AS {internal(f'{CONVERTED}{i}')}, "
            f"{key} IS NOT NULL AND {result} IS NULL AS {internal(f'{FAILED}{i}')}"
        )
        joins.append(f"LEFT JOIN {found.name} ON {matching(found, [value])}")
        sources.append(identifier(name))
    selected = "".join(", " + s for s in unchanged)
    if not changed:
        view = table.view("mapping_converted", f"SELECT row.*{selected} FROM {table.name} AS row")
    else:
        conversions = table.save(
            "mapping_conversions",
            f"SELECT source.{ROW}, {', '.join(changed)} FROM "
            f"(SELECT {ROW}, {', '.join(sources)} FROM {table.name}) AS source {' '.join(joins)}",
        )
        view = table.view(
            "mapping_converted",
            f"SELECT row.*{selected}, conversions.* EXCLUDE ({ROW}) FROM {table.name} AS row "
            f"JOIN {conversions.name} AS conversions ON row.{ROW} = conversions.{ROW}",
        )
    return _Conversions(view, columns, {name: mapped[name].target for name in columns})


def _mapped_terms(conversions: _Conversions) -> dict[str, str]:
    table = conversions.table
    had_verbatim_date = f"{table.text('verbatimEventDate')} <> ''"
    terms: dict[str, str] = {}
    for name in conversions.columns:
        target = conversions.targets[name]
        if target in FOLDED_TARGETS:
            continue
        value = conversions.converted(name)
        if target == "minimumDepthInMeters":
            terms["maximumDepthInMeters"] = _set_default(
                terms.get("maximumDepthInMeters"), value, f"{value} <> ''"
            )
        if target == "eventDate":
            raw = table.text(name)
            terms["verbatimEventDate"] = _set_default(
                terms.get("verbatimEventDate"),
                raw,
                f"{value} <> {raw} AND NOT ({had_verbatim_date})",
            )
        terms[target] = _assign(terms.get(target), value)
    return terms


def _constant_by_marker(
    table: Table,
    valid: dict[str, tuple[str, str]],
    by_marker: dict[str, dict[str, tuple[str, str]]],
) -> dict[str, str]:
    marker = table.text("marker")
    constants: dict[str, str] = {}
    for term in dict.fromkeys([*valid, *(t for terms in by_marker.values() for t in terms)]):
        cases = "".join(
            f"WHEN {literal(m)} THEN {literal(terms[term][0])} "
            for m, terms in by_marker.items()
            if term in terms
        )
        fallback = literal(valid[term][0]) if term in valid else "NULL"
        constants[term] = f"CASE {marker} {cases}ELSE {fallback} END" if cases else fallback
    return constants


def _row_constant_order(
    valid: dict[str, tuple[str, str]], by_marker: dict[str, dict[str, tuple[str, str]]]
) -> dict[str, list[str]]:
    return {marker: list({**valid, **terms}) for marker, terms in by_marker.items()}


def _unconvertible(conversions: _Conversions, terms_table: dict) -> FindingsLog:
    findings = FindingsLog()
    table = conversions.table
    failing = [
        n for n in conversions.columns if terms_table.get(conversions.targets[n], {}).get("format")
    ]
    if not failing:
        return findings
    counts = table.one(
        "SELECT "
        + ", ".join(
            f"count(*) FILTER (WHERE {conversions.failed(n)} AND {table.text(n)} <> ''), "
            f"min({ROW}) FILTER (WHERE {conversions.failed(n)} AND {table.text(n)} <> '')"
            for n in failing
        )
        + f" FROM {table.name}"
    )
    by_target: dict[str, tuple[tuple[int, int], int, list[str]]] = {}
    for i, name in enumerate(failing):
        found, first = counts[2 * i], counts[2 * i + 1]
        if not found:
            continue
        values = [
            value
            for (value,) in table.rows(
                f"SELECT DISTINCT {table.text(name)} FROM {table.name} "
                f"WHERE {conversions.failed(name)} AND {table.text(name)} <> ''"
            )
        ]
        target = conversions.targets[name]
        earliest, total, examples = by_target.get(target, ((first, i), 0, []))
        by_target[target] = (min(earliest, (first, i)), total + found, examples + values)
    for target, (_, total, values) in sorted(by_target.items(), key=lambda item: item[1][0]):
        examples = ", ".join(repr(value) for value in sorted(set(values))[:3])
        verbatim = ", each kept in verbatimEventDate" if target == "eventDate" else ""
        findings.add(
            "TERM_FORMAT_UNCONVERTIBLE",
            f"{target}: {total} value(s) could not be converted to "
            f"{terms_table[target]['format']}, so they were left blank{verbatim}: {examples}",
            count=total,
        )
    return findings


def _overwritten_by_constants(
    table: Table,
    terms: dict[str, str],
    constants: dict[str, str],
    order: dict[str, list[str]],
    valid: dict[str, tuple[str, str]],
) -> FindingsLog:
    findings = FindingsLog()
    overwritten = [term for term in constants if term in terms]
    if not overwritten:
        return findings
    conditions = {
        term: f"{constants[term]} IS NOT NULL AND coalesce({terms[term]}, '') <> '' "
        f"AND {terms[term]} <> {constants[term]}"
        for term in overwritten
    }
    counts = table.one(
        "SELECT "
        + ", ".join(
            f"count(*) FILTER (WHERE {c}), arg_min({terms[t]}, {ROW}) FILTER (WHERE {c}), "
            f"min({ROW}) FILTER (WHERE {c}), arg_min({table.text('marker')}, {ROW}) FILTER (WHERE {c})"
            for t, c in conditions.items()
        )
        + f" FROM {table.name}"
    )
    found = []
    for i, term in enumerate(overwritten):
        count, value, first, marker = counts[4 * i : 4 * i + 4]
        if count:
            position = order.get(marker, list(valid)).index(term)
            found.append(((first, position), term, count, value))
    for _, term, count, value in sorted(found):
        findings.add(
            "CONSTANT_OVERWROTE_MAPPED_VALUE",
            f"a constant for {term} would replace {count} value(s) the data gives, such "
            f"as {value!r}. A constant fills a term the data leaves blank: remove it, or "
            "change the column in the data",
            count=count,
        )
    return findings


def apply_mapping(
    table: Table,
    proposals: list[MappingProposal],
    terms_table: dict,
    *,
    constants: dict[str, tuple[str, str]] | None = None,
    marker_constants: dict[str, dict[str, tuple[str, str]]] | None = None,
    carried: Collection[str] = (),
) -> ApplyMappingResult:
    findings = FindingsLog()
    constants = constants or {}
    marker_constants = marker_constants or {}

    proposed_columns = {p.source_column for p in proposals}
    unproposed_carried = set(carried) - proposed_columns
    dropped_internal = {p.source_column for p in proposals if p.basis == "internal"}
    mapped_by_column = {
        p.source_column: p
        for p in proposals
        if p.target and p.source_column not in dropped_internal
    }
    unmapped = [p for p in proposals if not p.target and p.source_column not in dropped_internal]

    row_columns = set(table.present()) - {DYNAMIC_PROPERTIES} - unproposed_carried
    missing_rows = sorted(row_columns - proposed_columns)
    if missing_rows:
        findings.add(
            "MAPPING_ROW_MISSING",
            f"{len(missing_rows)} column(s) present in the data have no row in proposed/term_mapping.tsv: "
            f"{', '.join(missing_rows)}",
            count=len(missing_rows),
        )

    known_terms = {name for name in terms_table if not name.startswith("_")}
    for p in list(mapped_by_column.values()):
        if p.target in known_terms or p.target in FOLDED_TARGETS:
            continue
        del mapped_by_column[p.source_column]
        findings.add(
            "TERM_NOT_DARWIN_CORE",
            f"{p.source_column!r} is mapped to {p.target!r}, but "
            f"{_not_a_term(p.target, known_terms)}",
        )

    valid_constants = _known_constants(constants, known_terms, findings)
    valid_by_marker = {
        marker: _known_constants(by_term, known_terms, findings)
        for marker, by_term in marker_constants.items()
    }

    columns = sorted(
        c
        for c in table.columns
        if c not in dropped_internal | unproposed_carried and c != DYNAMIC_PROPERTIES
    )
    mapped = {c: mapped_by_column[c] for c in columns if c in mapped_by_column}
    conversions = _convert(table, mapped, terms_table)
    converted = conversions.table
    terms = _mapped_terms(conversions)
    dynamic_columns = [c for c in columns if c not in mapped or mapped[c].target in FOLDED_TARGETS]
    dynamic = DynamicProperties(tuple(dynamic_columns))
    by_constant = _constant_by_marker(converted, valid_constants, valid_by_marker)
    findings.findings += _unconvertible(conversions, terms_table).findings
    blob = converted.text(DYNAMIC_PROPERTIES)
    findings.findings += _overwritten_by_constants(
        converted,
        {**terms, DYNAMIC_PROPERTIES: blob},
        by_constant,
        _row_constant_order(valid_constants, valid_by_marker),
        valid_constants,
    ).findings
    if constant := by_constant.pop(DYNAMIC_PROPERTIES, None):
        blob = f"coalesce({constant}, {blob})"
    published = {**terms}
    for term, constant in by_constant.items():
        published[term] = f"coalesce({constant}, {terms[term]})" if term in terms else constant
    malformed = converted.count(f"{blob} <> '' AND NOT {is_json_object(blob)}")
    hidden = [
        f"CASE WHEN {is_json_object(blob)} THEN {blob} ELSE '' END AS {BLOB}",
        *(
            f"{conversions.converted(c) if c in mapped else converted.text(c)} AS {value_column(i)}"
            for i, c in enumerate(dynamic_columns)
        ),
    ]
    flags = _unconvertible_flags(conversions, terms_table)
    hidden += [f"{failed} AS {flag}" for flag, failed in flags.items()]
    selected = [
        *hidden,
        *(f"{converted.get(c)} AS {identifier(c)}" for c in carried if c not in published),
        *(f"{sql} AS {identifier(term)}" for term, sql in published.items()),
    ]
    result = converted.save("mapped", f"SELECT {ROW}, {', '.join(selected)} FROM {converted.name}")

    if malformed:
        findings.add(
            "DYNAMIC_PROPERTIES_MALFORMED",
            f"{malformed} row(s) had a dynamicProperties value that is not a "
            "JSON object with one value per key, and each was ignored",
            count=malformed,
        )
    if collision_keys := dynamic.colliding_keys(result):
        findings.add(
            "DYNAMIC_PROPERTIES_KEY_COLLISION",
            f"{len(collision_keys)} key(s) set by both an existing dynamicProperties blob and "
            f"an unmapped column of the same name, on at least one row: {collision_keys}",
            count=len(collision_keys),
        )
    if unmapped:
        findings.add(
            "TERM_UNMAPPED",
            _unmapped_message([p.source_column for p in unmapped]),
            count=len(unmapped),
        )
    return ApplyMappingResult(
        table=result,
        dynamic=dynamic,
        findings=findings,
        unconvertible=list(flags),
        applied_constants=valid_constants,
        applied_marker_constants={marker: c for marker, c in valid_by_marker.items() if c},
    )


def _unconvertible_flags(conversions: _Conversions, terms_table: dict) -> dict[str, str]:
    by_term: dict[str, list[str]] = {}
    for name in conversions.columns:
        target = conversions.targets[name]
        if target not in FOLDED_TARGETS and terms_table.get(target, {}).get("format"):
            by_term.setdefault(target, []).append(conversions.failed(name))
    return {unconvertible(term): " OR ".join(failed) for term, failed in by_term.items()}


def convert_formats(
    table: Table, columns: Collection[str], terms_table: dict
) -> tuple[Table, FindingsLog]:
    formatted = {
        name: MappingProposal(name, name, "exact")
        for name in columns
        if table.has(name) and terms_table.get(name, {}).get("format")
    }
    if not formatted:
        return table, FindingsLog()
    conversions = _convert(table, formatted, terms_table)
    working = ", ".join(
        f"{conversions.converted(name)}, {conversions.failed(name)}"
        for name in conversions.columns
    )
    replaced = ", ".join(
        f"{conversions.converted(name)} AS {identifier(name)}" for name in conversions.columns
    )
    converted = conversions.table.save(
        f"{table.name}_formatted",
        f"SELECT * EXCLUDE ({working}) REPLACE ({replaced}) FROM {conversions.table.name}",
    )
    return converted, _unconvertible(conversions, terms_table)


def _not_a_term(name: str, known_terms: set[str]) -> str:
    closest = difflib.get_close_matches(name, known_terms, n=1)
    hint = f" Did you mean `{closest[0]}`? Rename it to the term you mean." if closest else ""
    return f"{name!r} is no Darwin Core or extension term, so the build stops.{hint}"


def _known_constants(
    constants: dict[str, tuple[str, str]], known_terms: set[str], findings: FindingsLog
) -> dict[str, tuple[str, str]]:
    for term in sorted(constants.keys() - known_terms - {DYNAMIC_PROPERTIES}):
        findings.add("TERM_NOT_DARWIN_CORE", f"The constant {_not_a_term(term, known_terms)}")
    return {
        term: value
        for term, value in constants.items()
        if term in known_terms or term == DYNAMIC_PROPERTIES
    }


def _unmapped_message(columns: list[str]) -> str:
    return (
        f"{len(columns)} column(s) left unmapped: {', '.join(columns)} "
        f"{'stays' if len(columns) == 1 else 'stay'} in dynamicProperties. A row of "
        "confirmed/term_mapping.tsv maps any of them to a term, or to extendedmeasurementorfact"
    )


def _convert_value(value: str, term_format: str, term: str) -> str | None:
    if term_format == "iso8601_date":
        return formats.convert_iso8601_date(value)
    if term_format == "decimal_degrees":
        max_abs = 90.0 if term == "decimalLatitude" else 180.0
        return formats.convert_decimal_degrees(value, max_abs=max_abs)
    if term_format == "iso3166_alpha2":
        return formats.convert_iso3166_alpha2(value, valid_codes=valid_country_codes())
    if term_format == "controlled":
        vocabulary = formats.VOCABULARY_BY_TERM.get(term)
        return formats.convert_controlled(
            value, vocabulary=vocabulary, synonyms=formats.SYNONYMS_BY_TERM.get(term)
        )
    if term_format == "nonneg_number":
        return formats.convert_nonneg_number(value)
    if term_format == "uri":
        return formats.convert_uri(value)
    if term_format == "wkt":
        return formats.convert_wkt(value)
    if term_format == "dna_sequence":
        return formats.convert_dna_sequence(value)
    if term_format == "pipe_list":
        return formats.convert_pipe_list(value)
    if term_format == "number_with_unit":
        value = value.strip()
        return value if formats.validate_number_with_unit(value) else None
    return value


DEFAULTED_TERMS = {"basisOfRecord": "MaterialSample"}


def apply_defaults(table: Table) -> Table:
    defaults = ", ".join(
        f"coalesce({table.get(term)}, {literal(value)}) AS {identifier(term)}"
        for term, value in DEFAULTED_TERMS.items()
    )
    return table.view(
        f"{table.name}_defaulted",
        f"SELECT {table.star(*DEFAULTED_TERMS)}, {defaults} FROM {table.name}",
    )


@dataclass
class AppliedMapping:
    table: Table
    proposals: list[MappingProposal]
    findings: FindingsLog
    dynamic: DynamicProperties
    unconvertible: list[str] = field(default_factory=list)

    def hidden(self) -> list[str]:
        return [*self.dynamic.hidden(), *self.unconvertible]


def apply(
    table: Table,
    proposals: list[MappingProposal],
    terms_table: dict,
    *,
    constants: dict[str, tuple[str, str]],
    marker_constants: dict[str, dict[str, tuple[str, str]]],
    carried: Collection[str] = (),
) -> AppliedMapping:
    proposals = with_derived_rows(proposals, table.columns, terms_table)
    result = apply_mapping(
        table,
        proposals,
        terms_table,
        constants=constants,
        marker_constants=marker_constants,
        carried=carried,
    )
    merged = merge_constant_rows(
        proposals, result.applied_constants, result.applied_marker_constants
    )
    return AppliedMapping(
        table=apply_defaults(result.table),
        proposals=review_order(merged),
        findings=result.findings,
        dynamic=result.dynamic,
        unconvertible=result.unconvertible,
    )


def with_derived_rows(
    proposals: list[MappingProposal], columns: Collection[str], terms_table: dict
) -> list[MappingProposal]:
    return [*proposals, *_derived_column_rows(proposals, sorted(columns), terms_table)]
