from __future__ import annotations

from dataclasses import dataclass, field
import hashlib

from edna2dwc.common.findings import FindingsLog
from edna2dwc.common.table import Table, internal, literal, lookup, matching
from edna2dwc.conversion.answers import validate_dataset_id
from edna2dwc.terms.formats import convert_dna_sequence
from edna2dwc.terms.map_terms import ALIAS_TABLE, source_gave, unless_given


@dataclass
class SynthesizeIdsResult:
    table: Table
    findings: FindingsLog = field(default_factory=FindingsLog)


COUNT_COLUMN = "count"
_MD5_PATTERN = "[0-9a-f]{32}"
SEQUENCE_COLUMNS = ("DNA_sequence", *ALIAS_TABLE["DNA_sequence"])
CONSUMED_COLUMNS = frozenset({"sampleID", "featureID", COUNT_COLUMN})
DIGEST = internal("digest")
DISAGREES = internal("disagrees")


def sequence_hash(sequence: str | None) -> str:
    return hashlib.md5(sequence.encode("ascii")).hexdigest() if sequence else ""


def _hashed(sequence_text: str) -> tuple[str]:
    return (sequence_hash(convert_dna_sequence(sequence_text)),)


def _disagrees(sequence_text: str, *others: str) -> tuple[bool]:
    sequence = convert_dna_sequence(sequence_text)
    return (
        bool(sequence)
        and any(other and convert_dna_sequence(other) != sequence for other in others),
    )


def check_sequence_columns(table: Table, sequence_column: str) -> FindingsLog:
    findings = FindingsLog()
    others = [c for c in SEQUENCE_COLUMNS if c != sequence_column and table.has(c)]
    if not (sequence_column and others):
        return findings
    keys = [table.text(sequence_column), *(table.text(c) for c in others)]
    compared = lookup(table, "sequence_columns", keys, {DISAGREES: "BOOLEAN"}, _disagrees)
    (disagreeing,) = table.one(
        f"SELECT count(*) FROM {table.name} JOIN {compared.name} ON {matching(compared, keys)} "
        f"WHERE {compared.name}.{DISAGREES} AND {table.text('sampleID')} <> '' "
        f"AND {table.text('featureID')} <> ''"
    )
    if disagreeing:
        findings.add(
            "SEQUENCE_COLUMNS_DISAGREE",
            f"{disagreeing} row(s) give a different sequence in another sequence column "
            f"than in {sequence_column!r}, the one published as DNA_sequence",
            count=disagreeing,
        )
    return findings


def synthesize_ids(table: Table, *, dataset_id: str) -> SynthesizeIdsResult:
    validate_dataset_id(dataset_id)
    findings = FindingsLog()
    sample, feature = table.text("sampleID"), table.text("featureID")
    keys = [table.text("DNA_sequence")]
    hashes = lookup(table, "sequence_hashes", keys, {DIGEST: "VARCHAR"}, _hashed)
    given = source_gave(table, "taxonID")
    digest = f"{hashes.name}.{DIGEST}"
    joined = (
        f"FROM {table.name} JOIN {hashes.name} ON {matching(hashes, keys)} "
        f"WHERE {sample} <> '' AND {feature} <> ''"
    )
    blank, mismatched = table.one(
        f"SELECT count(*) FILTER (WHERE NOT {given} AND {digest} = ''), "
        f"count(*) FILTER (WHERE NOT {given} AND {digest} <> '' "
        f"AND regexp_full_match({feature}, '{_MD5_PATTERN}') AND {feature} <> {digest}) "
        f"{joined}"
    )
    if blank:
        findings.add(
            "TAXON_ID_BLANK",
            f"{blank} row(s) have no DNA_sequence to hash, so taxonID is blank",
            count=blank,
        )
    if mismatched:
        findings.add(
            "FEATURE_ID_NOT_SEQUENCE_HASH",
            f"{mismatched} row(s) have an MD5-shaped featureID that is not the MD5 "
            "of the row's sequence; taxonID was built from the sequence",
            count=mismatched,
        )
    occurrence_id = f"{literal(dataset_id + ':')} || {sample} || ':' || {feature}"
    taxon_id = f"CASE WHEN {digest} <> '' THEN 'ASV:' || {digest} ELSE '' END"
    with_ids = table.view(
        "with_ids",
        f"SELECT {table.star(*CONSUMED_COLUMNS, 'occurrenceID', 'taxonID', 'materialSampleID')}, "
        f"{unless_given(table, 'occurrenceID', occurrence_id)}, "
        f"{unless_given(table, 'taxonID', taxon_id)}, "
        f"{unless_given(table, 'materialSampleID', sample)} {joined}",
    )
    return SynthesizeIdsResult(with_ids, findings)
