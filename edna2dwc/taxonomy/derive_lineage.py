from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import hashlib
import re

from edna2dwc.common.table import ROW, Table, column, from_rows, internal, literals
from edna2dwc.conversion.intermediate import NAME_COLUMNS, RANK_COLUMNS, REQUIRED_COLUMNS
from edna2dwc.taxonomy.taxon_normalize import is_rank_word
from edna2dwc.taxonomy.unassigned import is_no_assignment

_PREFIX_TO_RANK = {
    "d": "kingdom",
    "k": "kingdom",
    "p": "phylum",
    "c": "class",
    "o": "order",
    "f": "family",
    "g": "genus",
}
_RANK_PREFIX_RE = re.compile(r"^([dkpcofgs])__(.*)$")
_LABEL_TO_RANK = {
    "domain": "kingdom",
    "superkingdom": "kingdom",
    "kingdom": "kingdom",
    "phylum": "phylum",
    "division": "phylum",
    "class": "class",
    "order": "order",
    "family": "family",
    "genus": "genus",
}
_LINEAGE_SEPARATOR_RE = re.compile(r"[|;]")
_LABELLED_SEGMENT_RE = re.compile(r"([A-Za-z]+)\s*:(.*)", re.DOTALL)
_ONE_LETTER_LABEL_RE = re.compile(r"^[A-Za-z]:\s*(.*)$", re.DOTALL)

TAXONOMY_COLUMN = "taxonomy"
VERBATIM_COLUMN = "verbatimIdentification"
UNRANKED_COLUMN = "unranked_lineage"

_SCRUBBED_COLUMNS = frozenset(NAME_COLUMNS)


@dataclass
class LineageEntry:
    lineage_key: str
    terminal_name: str
    source_ranks: dict[str, str]
    row_count: int = 0
    ncbi_taxid: str = ""
    source_taxon_id: str = ""
    taxonomy_scope: str = ""
    unranked: tuple[str, ...] = ()
    source_names: set[str] = field(default_factory=set)

    def to_row(self) -> dict[str, str]:
        row = {"lineage_key": self.lineage_key, "terminal_name": self.terminal_name}
        for rank in RANK_COLUMNS:
            row[f"source_{rank}"] = self.source_ranks.get(rank, "")
        row["row_count"] = str(self.row_count)
        row["ncbi_taxid"] = self.ncbi_taxid
        row["source_taxon_id"] = self.source_taxon_id
        row["taxonomy_scope"] = self.taxonomy_scope
        row[UNRANKED_COLUMN] = ";".join(self.unranked)
        return row


@dataclass
class DeriveLineageResult:
    occurrences: Table
    lineage_rows: list[dict[str, str]] = field(default_factory=list)
    source_names: dict[str, set[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedTaxonomy:
    ranks: dict[str, str]
    terminal: str
    verbatim: str = ""
    unranked: tuple[str, ...] = ()


def _segment_name(segment: str) -> str:
    token = segment.strip()
    if "=" in token:
        return ""
    labelled = _ONE_LETTER_LABEL_RE.match(token)
    return (labelled[1] if labelled else token).replace("+", " ").strip()


def _prefixed_tokens(taxonomy: str) -> list[tuple[str | None, str]]:
    tokens = []
    for raw_token in _LINEAGE_SEPARATOR_RE.split(taxonomy):
        token = raw_token.strip()
        match = _RANK_PREFIX_RE.match(token)
        tokens.append(
            (_PREFIX_TO_RANK.get(match[1]), match[2].strip())
            if match
            else (None, _segment_name(token))
        )
    return tokens


def _unless_rank_placeholder(name: str) -> str:
    head, underscore, _ = name.partition("_")
    return "" if underscore and is_rank_word(head) else name


def _labelled_tokens(taxonomy: str) -> list[tuple[str | None, str]] | None:
    segments = [s.strip() for s in _LINEAGE_SEPARATOR_RE.split(taxonomy) if s.strip()]
    matches = [_LABELLED_SEGMENT_RE.fullmatch(segment) for segment in segments]
    labelled = [match for match in matches if match and is_rank_word(match[1])]
    if not labelled or len(labelled) < len(segments):
        return None
    return [
        (_LABEL_TO_RANK.get(match[1].casefold()), _unless_rank_placeholder(match[2].strip()))
        for match in labelled
    ]


def parse_taxonomy_string(taxonomy: str) -> ParsedTaxonomy:
    ranks: dict[str, str] = {}
    names: list[str] = []
    saw_sentinel = False
    for rank, value in _labelled_tokens(taxonomy) or _prefixed_tokens(taxonomy):
        if is_no_assignment(value):
            saw_sentinel = True
            continue
        if not value:
            continue
        if rank is not None:
            ranks[rank] = value
        names.append(value)
    terminal = names[-1] if names else ""
    verbatim = taxonomy.strip() if saw_sentinel and not terminal else ""
    unranked = () if ranks else tuple(names[:-1])
    return ParsedTaxonomy(ranks, terminal, verbatim, unranked)


def _binomial(species: str, genus: str) -> str:
    if not species or not genus or " " in species or not species[:1].islower():
        return species
    if species.casefold().startswith(genus.casefold()):
        return species
    return f"{genus} {species}"


def _rank_cells(source: SourceLineage) -> dict[str, str]:
    cells = {rank: raw.strip() for rank, raw in zip(RANK_COLUMNS, source.ranks, strict=True)}
    return {rank: value for rank, value in cells.items() if value and not is_no_assignment(value)}


def _extract_source_lineage(source: SourceLineage) -> ParsedTaxonomy:
    ranks = _rank_cells(source)
    if source.taxonomy:
        parsed = parse_taxonomy_string(source.taxonomy)
        if parsed.ranks or not ranks:
            return parsed

    name_cells = [source.species.strip(), source.scientific_name.strip()]
    species, scientific_name = ("" if is_no_assignment(v) else v for v in name_cells)
    terminal = _binomial(species, ranks.get("genus", "")) or scientific_name
    if not terminal:
        for rank in reversed(RANK_COLUMNS):
            if ranks.get(rank):
                terminal = ranks[rank]
                break
    if not terminal:
        verbatim = source.verbatim.strip()
        if not is_no_assignment(verbatim):
            terminal = verbatim
    unassigned = "" if terminal else next((v for v in name_cells if is_no_assignment(v)), "")
    return ParsedTaxonomy(ranks, terminal, scientific_name or unassigned)


def lineage_key(terminal_name: str, source_ranks: dict[str, str], *qualifiers: str) -> str:
    ordered_ranks = "|".join(source_ranks.get(rank, "") for rank in RANK_COLUMNS)
    parts = [terminal_name, ordered_ranks]
    if any(qualifiers):
        parts.extend(qualifiers)
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:16]


@dataclass(frozen=True)
class SourceLineage:
    taxonomy: str
    ranks: tuple[str, ...]
    species: str
    scientific_name: str
    verbatim: str
    ncbi_taxid: str
    source_taxon_id: str
    marker: str


KEY = internal("lineage_key")
VERBATIM = internal("verbatim")
_CASE_INSENSITIVE_INPUTS = (*NAME_COLUMNS, "verbatimidentification")


def _last_named(table: Table, lowered: str) -> str:
    return next((c for c in reversed(table.columns) if c.lower() == lowered), "")


def _source_inputs(table: Table) -> list[str]:
    return [
        table.text(TAXONOMY_COLUMN),
        *(table.text(_last_named(table, name)) for name in _CASE_INSENSITIVE_INPUTS),
        table.text("ncbi_taxid"),
        table.text("source_taxon_id"),
        table.text("marker"),
    ]


def _parsed(inputs: tuple[str, ...], scopes: Mapping[str, str]) -> tuple[LineageEntry, str]:
    taxonomy, *ranks, species, scientific_name, verbatim, ncbi, source_id, marker = inputs
    source = SourceLineage(
        taxonomy, tuple(ranks), species, scientific_name, verbatim, ncbi, source_id, marker
    )
    parsed = _extract_source_lineage(source)
    ncbi_taxid, source_taxon_id = ncbi.strip(), source_id.strip()
    scope = scopes.get(marker, "")
    key = lineage_key(
        parsed.terminal, parsed.ranks, ncbi_taxid, source_taxon_id, scope, *parsed.unranked
    )
    entry = LineageEntry(
        key, parsed.terminal, parsed.ranks, 0, ncbi_taxid, source_taxon_id, scope, parsed.unranked
    )
    entry.source_names = _source_names(source)
    return entry, parsed.verbatim


def _source_names(source: SourceLineage) -> set[str]:
    segments = [segment.strip() for segment in _LINEAGE_SEPARATOR_RE.split(source.taxonomy)]
    names = [
        _segment_name(_RANK_PREFIX_RE.sub(r"\2", _LABELLED_SEGMENT_RE.sub(r"\2", segment)))
        for segment in segments
    ]
    names += [*source.ranks, source.species, source.scientific_name]
    return {name.casefold() for name in names if name.strip()}


def _scrubbed(table: Table, name: str) -> str:
    if name.lower() not in _SCRUBBED_COLUMNS:
        return column(name)
    values = table.rows(f"SELECT DISTINCT {column(name)} FROM {table.name}")
    sentinels = [value for (value,) in values if value and is_no_assignment(value)]
    if not sentinels:
        return column(name)
    return f"CASE WHEN {column(name)} IN {literals(sentinels)} THEN '' ELSE {column(name)} END"


def _verbatim_name(table: Table) -> str:
    return next(
        (c for c in table.columns if c.lower() == VERBATIM_COLUMN.lower()), VERBATIM_COLUMN
    )


def _with_verbatim(table: Table) -> str:
    name = _verbatim_name(table)
    current = f"source.{column(name)}" if table.has(name) else "NULL"
    return (
        f"CASE WHEN lineage.{VERBATIM} <> '' AND coalesce({current}, '') = '' "
        f"THEN lineage.{VERBATIM} ELSE {current} END AS {column(name)}"
    )


def derive_lineage(
    table: Table, *, scopes: Mapping[str, str] | None = None
) -> DeriveLineageResult:
    inputs = _source_inputs(table)
    grouped = table.rows(f"SELECT {', '.join(inputs)}, count(*) FROM {table.name} GROUP BY ALL")
    entries: dict[str, LineageEntry] = {}
    lookup = []
    for *values, row_count in grouped:
        entry, verbatim = _parsed(tuple(values), scopes or {})
        kept = entries.setdefault(entry.lineage_key, entry)
        kept.row_count += row_count
        kept.source_names |= entry.source_names
        lookup.append((*values, entry.lineage_key, verbatim))
    names = [internal(f"input{i}") for i in range(len(inputs))]
    from_rows(
        table.con,
        "lineage_of",
        {**dict.fromkeys(names, "VARCHAR"), KEY: "VARCHAR", VERBATIM: "VARCHAR"},
        lookup,
    )
    kept = [c for c in table.columns if c not in (_verbatim_name(table), "lineage_key")]
    matches = " AND ".join(
        f"{expression} = lineage.{name}" for expression, name in zip(inputs, names, strict=True)
    )
    occurrences = table.view(
        "lineages_joined",
        f"SELECT source.{ROW}, "
        + "".join(f"{_scrubbed(table, c)} AS {column(c)}, " for c in kept)
        + f"{_with_verbatim(table)}, lineage.{KEY} AS {column('lineage_key')} "
        f"FROM {table.name} AS source JOIN lineage_of AS lineage ON {matches}",
    )
    lineage_rows = [e.to_row() for e in sorted(entries.values(), key=lambda e: e.lineage_key)]
    return DeriveLineageResult(
        occurrences.settled("lineages", required=REQUIRED_COLUMNS),
        lineage_rows,
        {key: entry.source_names for key, entry in entries.items()},
    )
