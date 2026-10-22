from __future__ import annotations

from dataclasses import dataclass, field
import re

from edna2dwc.build.filter_controls import EXCLUDED, KEYWORD, SAMPLE, control_findings
from edna2dwc.common.findings import FindingsLog
from edna2dwc.common.table import ROW, Table, column, from_rows, internal
from edna2dwc.conversion.intermediate import RANK_COLUMNS

HOMO_SAPIENS_WORMS_LSID = "urn:lsid:marinespecies.org:taxname:1455977"
HOMO_SAPIENS_GBIF_TAXON_CONCEPT_ID = "https://www.gbif.org/species/2436436"
HUMAN_IDS = frozenset(
    {
        HOMO_SAPIENS_WORMS_LSID,
        "urn:lsid:marinespecies.org:taxname:1455976",
        HOMO_SAPIENS_GBIF_TAXON_CONCEPT_ID,
        "https://www.gbif.org/species/2436435",
        "NCBI:txid9606",
        "NCBI:txid9605",
    }
)

_PARENTHETICAL_RE = re.compile(r"\s*\([^)]*\)")


def _strip_authorship(name: str) -> str:
    stripped = _PARENTHETICAL_RE.sub("", name)
    return re.sub(r"\s+", " ", stripped).strip()


def _is_homo_sapiens(scientific_name: str) -> bool:
    return _strip_authorship(scientific_name).casefold().split()[:2] == ["homo", "sapiens"]


def _is_human_name(scientific_name: str) -> bool:
    return _strip_authorship(scientific_name).casefold() == "homo" or _is_homo_sapiens(
        scientific_name
    )


def is_human(
    *, scientific_name: str, scientific_name_id: str = "", taxon_concept_id: str = ""
) -> bool:
    return bool({scientific_name_id, taxon_concept_id} & HUMAN_IDS) or _is_human_name(
        scientific_name
    )


HUMAN_FIELDS = ("scientificName", "scientificNameID", "taxonConceptID")
HOMO_SAPIENS = internal("homo_sapiens")
STEP = internal("step")
REASON = internal("reason")
_HUMAN_KEYS = tuple(internal(name) for name in HUMAN_FIELDS)


def human_taxa(table: Table) -> Table:
    fields = ", ".join(table.text(name) for name in HUMAN_FIELDS)
    found = [
        (*taxon, _is_homo_sapiens(taxon[0]))
        for taxon in table.rows(f"SELECT DISTINCT {fields} FROM {table.name}")
        if is_human(
            scientific_name=taxon[0], scientific_name_id=taxon[1], taxon_concept_id=taxon[2]
        )
    ]
    return from_rows(
        table.con,
        "human_taxa",
        {**dict.fromkeys(_HUMAN_KEYS, "VARCHAR"), HOMO_SAPIENS: "BOOLEAN"},
        found,
    )


def is_human_taxon(table: Table, alias: str, humans: Table) -> str:
    return " AND ".join(
        f"{table.text(name, alias)} = {humans.name}.{key}"
        for name, key in zip(HUMAN_FIELDS, _HUMAN_KEYS, strict=True)
    )


@dataclass
class Exclusion:
    kept: Table
    excluded: Table
    findings: FindingsLog = field(default_factory=FindingsLog)


def _excluded_kingdoms(table: Table, by_marker: dict[str, set[str]] | None) -> Table:
    pairs = [
        (marker, kingdom) for marker, kingdoms in (by_marker or {}).items() for kingdom in kingdoms
    ]
    return from_rows(
        table.con, "excluded_kingdoms", {MARKER: "VARCHAR", KINGDOM: "VARCHAR"}, pairs
    )


MARKER = internal("marker")
KINGDOM = internal("kingdom")
LINEAGE = internal("lineage_key")
TAXON = internal("taxon")
RESOLVED_NAMES = (*RANK_COLUMNS, "scientificName")


def _excluded_taxa(
    table: Table, by_marker: dict[str, tuple[str, ...]], source_names: dict[str, set[str]]
) -> Table:
    names = {key: set(found) for key, found in source_names.items()}
    resolved = ", ".join(table.text(name) for name in RESOLVED_NAMES)
    for key, *values in table.rows(
        f"SELECT DISTINCT {table.text('lineage_key')}, {resolved} FROM {table.name}"
    ):
        names.setdefault(key, set()).update(v.casefold() for v in values if v)
    triples = [
        (marker, key, next(taxon for taxon in taxa if taxon.casefold() in found))
        for marker, taxa in by_marker.items()
        for key, found in names.items()
        if any(taxon.casefold() in found for taxon in taxa)
    ]
    return from_rows(
        table.con,
        "excluded_taxa",
        {MARKER: "VARCHAR", LINEAGE: "VARCHAR", TAXON: "VARCHAR"},
        triples,
    )


def exclude(
    table: Table,
    *,
    controls: Table,
    humans: Table,
    drop_human: bool,
    excluded_kingdoms_by_marker: dict[str, set[str]] | None,
    excluded_taxa_by_marker: dict[str, tuple[str, ...]] | None = None,
    source_names: dict[str, set[str]] | None = None,
    human_answer_confirmed: bool = True,
) -> Exclusion:
    kingdoms = _excluded_kingdoms(table, excluded_kingdoms_by_marker)
    taxa = _excluded_taxa(table, excluded_taxa_by_marker or {}, source_names or {})
    kingdom, marker = table.text("kingdom", "row"), table.text("marker", "row")
    is_human_row = f"{drop_human} AND {humans.name}.{HOMO_SAPIENS} IS NOT NULL"
    is_contaminant = f"{kingdoms.name}.{KINGDOM} IS NOT NULL"
    is_excluded_taxon = f"{taxa.name}.{TAXON} IS NOT NULL"
    table.save(
        "exclusions",
        f"SELECT row.{ROW}, "
        f"CASE WHEN {controls.name}.{EXCLUDED} THEN 1 WHEN {is_human_row} THEN 2 "
        f"WHEN {is_contaminant} THEN 3 WHEN {is_excluded_taxon} THEN 4 END AS {STEP}, "
        f"CASE WHEN {controls.name}.{EXCLUDED} THEN 'control:' || {controls.name}.{KEYWORD} "
        f"WHEN {is_human_row} THEN 'human' WHEN {is_contaminant} THEN 'kingdom:' || {kingdom} "
        f"WHEN {is_excluded_taxon} THEN 'taxon:' || {taxa.name}.{TAXON} "
        f"END AS {REASON}, {humans.name}.{HOMO_SAPIENS}, {kingdom} AS {KINGDOM}, "
        f"{marker} AS {MARKER}, {taxa.name}.{TAXON} "
        f"FROM {table.name} AS row "
        f"LEFT JOIN {controls.name} ON {table.text('sampleID', 'row')} = {controls.name}.{SAMPLE} "
        f"LEFT JOIN {humans.name} ON {is_human_taxon(table, 'row', humans)} "
        f"LEFT JOIN {kingdoms.name} ON {marker} = {kingdoms.name}.{MARKER} "
        f"AND {kingdom} = {kingdoms.name}.{KINGDOM} AND {kingdom} <> '' "
        f"LEFT JOIN {taxa.name} ON {marker} = {taxa.name}.{MARKER} "
        f"AND {table.text('lineage_key', 'row')} = {taxa.name}.{LINEAGE} "
        f"WHERE {REASON} IS NOT NULL",
    )
    excluded = table.view(
        "excluded",
        f"SELECT row.{table.without('exclusion_reason')}, exclusions.{REASON} AS "
        f"{column('exclusion_reason')}, exclusions.{STEP} FROM {table.name} AS row "
        f"JOIN exclusions ON row.{ROW} = exclusions.{ROW}",
    )
    kept = table.save(
        "kept",
        f"SELECT * FROM {table.name} AS row ANTI JOIN exclusions ON row.{ROW} = exclusions.{ROW}",
    )
    findings = control_findings(table, controls)
    findings.findings += (
        _human_findings(table).findings
        + _kingdom_findings(table).findings
        + _taxon_findings(table).findings
    )
    if not drop_human:
        findings.findings += _humans_published(kept, humans, human_answer_confirmed).findings
    return Exclusion(kept, excluded, findings)


def _humans_published(kept: Table, humans: Table, answer_confirmed: bool) -> FindingsLog:
    findings = FindingsLog()
    (published,) = kept.one(
        f"SELECT count(*) FROM {kept.name} AS row JOIN {humans.name} "
        f"ON {is_human_taxon(kept, 'row', humans)}"
    )
    if published:
        by = "" if answer_confirmed else ", on an answer no person confirmed"
        findings.add(
            "HUMAN_PUBLISHED",
            f"{published} human (Homo) row(s) published, as filters.exclude_human: false "
            f"asks{by}. Human DNA in an environmental sample is usually contamination",
            count=published,
        )
    return findings


def _human_findings(table: Table) -> FindingsLog:
    findings = FindingsLog()
    excluded, every_species = table.one(
        f"SELECT count(*), bool_and({HOMO_SAPIENS}) FROM exclusions WHERE {STEP} = 2"
    )
    if excluded:
        named = "Homo sapiens" if every_species else "human (Homo)"
        findings.add("HUMAN_EXCLUDED", f"{excluded} {named} row(s) excluded", count=excluded)
    return findings


def _kingdom_findings(table: Table) -> FindingsLog:
    findings = FindingsLog()
    by_kingdom = table.rows(
        f"SELECT {KINGDOM}, {MARKER}, count(*) FROM exclusions WHERE {STEP} = 3 GROUP BY ALL"
    )
    if by_kingdom:
        removed = [
            f"{count} {kingdom}" + (f" from {marker}" if marker else "")
            for kingdom, marker, count in sorted(by_kingdom)
        ]
        excluded = sum(count for _, _, count in by_kingdom)
        findings.add(
            "CONTAMINANT_EXCLUDED",
            f"{excluded} row(s) excluded by kingdom: {', '.join(removed)}",
            count=excluded,
        )
    return findings


def _taxon_findings(table: Table) -> FindingsLog:
    findings = FindingsLog()
    by_taxon = table.rows(
        f"SELECT {TAXON}, {MARKER}, count(*) FROM exclusions WHERE {STEP} = 4 GROUP BY ALL"
    )
    if by_taxon:
        removed = [
            f"{count} {taxon}" + (f" from {marker}" if marker else "")
            for taxon, marker, count in sorted(by_taxon)
        ]
        excluded = sum(count for _, _, count in by_taxon)
        findings.add(
            "CONTAMINANT_EXCLUDED",
            f"{excluded} row(s) excluded by a marker's exclude_taxa: {', '.join(removed)}",
            count=excluded,
        )
    return findings
