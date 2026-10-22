from __future__ import annotations

from dataclasses import dataclass, field
import re


_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")


def _normalize(header: str) -> str:
    return _NORMALIZE_RE.sub("", header.casefold())


def _sanitize_field(value: str) -> str:
    return value.replace("\t", " ").replace("\r", " ").replace("\n", " ")


_INTERNAL_BOOKKEEPING_COLUMNS = frozenset(
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
    "eventDate": ("date", "collection_date", "sample_date", "sampling_date"),
    "eventTime": ("time", "collection_time", "sample_time", "sampling_time"),
    "minimumDepthInMeters": ("depth", "depth_m", "sampling_depth"),
    "recordedBy": ("collector", "collected_by", "sampled_by", "recorded_by"),
    "samplingProtocol": ("protocol", "method", "sampling_method"),
    "habitat": ("habitat_type", "microhabitat"),
    "verbatimIdentification": ("taxonomy", "classification", "raw_taxonomy"),
}

_MATCH_STRENGTH = {"exact": 3, "case_insensitive": 2, "alias": 1}


@dataclass
class MappingProposal:
    source_column: str


def propose_mapping(
) -> tuple[list[MappingProposal], FindingsLog]:
    term_names = {name for name in terms_table if not name.startswith("_")}
    normalized_terms = {_normalize(name): name for name in term_names}
    normalized_aliases: dict[str, str] = {}
    for target, aliases in ALIAS_TABLE.items():
        for alias in aliases:
            normalized_aliases[_normalize(alias)] = target

    proposals = []
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
            collisions.add(
                "TERM_TARGET_COLLISION",
                f"{column!r} and {winner_column!r} both proposed {target!r}; kept "
                f"{winner_column!r} ({winner_basis}), rerouted {column!r} for review",
            )

    return proposals, collisions


        proposals,
    )
    return "\n".join(lines) + "\n"


def read_mapping_tsv(text: str) -> list[MappingProposal]:
    proposals = []
    for i, line in enumerate(text.split("\n"), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = line.split("\t")
            raise ValueError(
            )
    return proposals


@dataclass
class ApplyMappingResult:
    findings: FindingsLog = field(default_factory=FindingsLog)


def apply_mapping(
    proposals: list[MappingProposal],
    terms_table: dict,
    *,
) -> ApplyMappingResult:
    findings = FindingsLog()
    constants = constants or {}

    dropped_internal = {p.source_column for p in proposals if p.basis == "internal"}
    mapped_by_column = {
        p.source_column: p
        for p in proposals
        if p.target and p.source_column not in dropped_internal
    }
    unmapped = [p for p in proposals if not p.target and p.source_column not in dropped_internal]

    missing_rows = sorted(row_columns - proposed_columns)
    if missing_rows:
        findings.add(
            "MAPPING_ROW_MISSING",
            f"{', '.join(missing_rows)}",
            count=len(missing_rows),
        )

    known_terms = {name for name in terms_table if not name.startswith("_")}
    for p in list(mapped_by_column.values()):
            continue
        del mapped_by_column[p.source_column]
        findings.add(
            "TERM_NOT_DARWIN_CORE",
        )



        findings.add(
            "DYNAMIC_PROPERTIES_KEY_COLLISION",
            f"{len(collision_keys)} key(s) set by both an existing dynamicProperties blob and "
            count=len(collision_keys),
        )
    if unmapped:


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



