from __future__ import annotations

from pathlib import Path
import re

import duckdb

from edna2dwc.common.findings import FindingsLog
from edna2dwc.common.table import ROW, Table, column, from_rows, internal
from edna2dwc.conversion.provenance import Answer, refuse_unprovenanced, sheet_answer
from edna2dwc.taxonomy.gbif import species_url
from edna2dwc.terms.map_terms import JOINED_FIELDS

LINEAGE_KEY = internal("lineage_key")
NAME = internal("scientificName")
NAME_ID = internal("scientificNameID")
REMARKS = internal("remarks")

_PLACEHOLDER_REMARKS = {
    "biota_fallback": "placeholder taxon: no rank of the source lineage resolved",
    "incertae_sedis_placeholder": (
        "placeholder taxon: the source named no taxon and no rank of its lineage resolved"
    ),
}


_REVIEW_REASONS = {
    "ambiguous_homonym": (
        "the name has several accepted homonyms that the source's phylum and class don't tell "
        "apart, and the first is published"
    ),
    "homonym_source_mismatch": (
        "the name has several accepted homonyms, none in the source's phylum or class, and the "
        "first is published"
    ),
    "compound_name_unresolved": "no part of the compound name resolved",
    "compound_name_common_ancestor": (
        "the source named several taxa, published as the lowest taxon they share"
    ),
    "compound_name_no_shared_rank": "the source named several taxa that share no rank",
    "gbif_synonym_resolved_to_accepted": (
        "the GBIF backbone lists the name as a synonym, and its accepted name is published"
    ),
    "gbif_synonym_accepted_lookup_failed": (
        "the GBIF backbone lists the name as a synonym, and its accepted name could not be "
        "looked up"
    ),
    "gbif_higher_rank_match": "the GBIF backbone matched only a rank above the name",
}

_REVIEW_REASONS_WITH_VALUE = {
    "name_mismatch": lambda name: f"the register matched {name}, which differs from the name",
    "non_confident_match_type": lambda match_type: (
        f"the register matched the name only approximately ({match_type.lower()})"
    ),
    "unaccepted_status": lambda status: f"WoRMS gives this name the status {status.lower()}",
    "gbif_status": lambda status: f"the GBIF backbone gives this name the status {status.lower()}",
    "compound_name_part_unresolved": lambda parts: (
        f"the source named several taxa, and {', '.join(parts.split('|'))} did not resolve"
    ),
}

_CANDIDATE_IDS = re.compile(r"\d+(?:\|\d+)+")


class JoinAuditError(RuntimeError):
    pass


def _is_review_code(reason: str) -> bool:
    return reason in _REVIEW_REASONS or reason.partition(":")[0] in _REVIEW_REASONS_WITH_VALUE


def _are_review_codes(reasons: str) -> bool:
    return all(_is_review_code(reason) for reason in reasons.split(","))


def _plain_review_codes(reasons: str) -> str:
    sentences = []
    for reason in reasons.split(","):
        code, _, value = reason.partition(":")
        explain = _REVIEW_REASONS_WITH_VALUE.get(code)
        sentences.append(explain(value) if explain else _REVIEW_REASONS[reason])
    return "; ".join(sentences)


def _tied_candidates(ids: str) -> str:
    return f"tied candidates: {', '.join(ids.split('|'))}"


def _plain_review_note(note: str) -> str:
    if _are_review_codes(note):
        return _plain_review_codes(note)
    part, _, reasons = note.partition(":")
    head, _, ids = reasons.rpartition(":")
    if head and _CANDIDATE_IDS.fullmatch(ids):
        reasons = head
    else:
        ids = ""
    if not _are_review_codes(reasons):
        return note
    plain = f"{part}: {_plain_review_codes(reasons)}"
    return f"{plain} ({_tied_candidates(ids)})" if ids else plain


def _plain_review_reason(review_reason: str) -> str:
    return "; ".join(_plain_review_note(note) for note in review_reason.split("; "))


def _derived_remarks(taxon: dict[str, str]) -> str:
    parts = [_PLACEHOLDER_REMARKS.get(taxon.get("resolution_path", ""), "")]
    if taxon.get("needs_review") == "true" and taxon.get("review_reason"):
        parts.append(_plain_review_reason(taxon["review_reason"]))
    if taxon.get("candidate_ids"):
        parts.append(_tied_candidates(taxon["candidate_ids"]))
    gbif_url = species_url(taxon.get("gbif_usage_key", ""))
    if gbif_url not in ("", taxon.get("taxonConceptID", ""), taxon.get("scientificNameID", "")):
        parts.append(f"name from the GBIF backbone: {gbif_url}")
    return "; ".join(part for part in parts if part)


def _taxa_table(con: duckdb.DuckDBPyConnection, taxa_by_key: dict[str, dict[str, str]]) -> Table:
    return from_rows(
        con,
        "taxa",
        {LINEAGE_KEY: "VARCHAR", **dict.fromkeys(JOINED_FIELDS, "VARCHAR"), REMARKS: "VARCHAR"},
        [
            (key, *(taxon.get(name, "") for name in JOINED_FIELDS), _derived_remarks(taxon))
            for key, taxon in taxa_by_key.items()
        ],
    )


def _remarks(occurrences: Table) -> str:
    given = occurrences.text("identificationRemarks", "occurrence")
    derived = f"taxon.{REMARKS}"
    return (
        f"CASE WHEN {given} <> '' AND {derived} <> '' THEN {given} || '; ' || {derived} "
        f"WHEN {given} <> '' THEN {given} WHEN {derived} <> '' THEN {derived} END"
    )


def join_taxonomy(occurrences: Table, taxa_by_key: dict[str, dict[str, str]]) -> Table:
    _taxa_table(occurrences.con, taxa_by_key)
    key = column("lineage_key")
    missing = [
        found
        for (found,) in occurrences.rows(
            f"SELECT DISTINCT occurrence.{key} FROM {occurrences.name} AS occurrence "
            f"ANTI JOIN taxa ON occurrence.{key} = taxa.{LINEAGE_KEY}"
        )
    ]
    if missing:
        raise JoinAuditError(
            f"{len(missing)} lineage_key(s) on the occurrence table have no matching "
            f"resolved_taxonomy.tsv row: {sorted(missing)}"
        )
    joined = ", ".join(f"taxon.{column(name)}" for name in JOINED_FIELDS)
    kept = occurrences.without(*JOINED_FIELDS, "identificationRemarks")
    return occurrences.view(
        "taxonomy_joined",
        f"SELECT occurrence.{kept}, {joined}, {_remarks(occurrences)} AS "
        f"{column('identificationRemarks')} FROM {occurrences.name} AS occurrence "
        f"JOIN taxa AS taxon ON occurrence.{key} = taxon.{LINEAGE_KEY}",
    )


_NAME_BOUND_FIELDS = ("scientificNameID", "scientificNameAuthorship")


def _same_taxon(row: dict[str, str], locked: dict[str, str]) -> bool:
    return all(row.get(field, "") == locked.get(field, "") for field in JOINED_FIELDS)


def _kept_from_the_old_name(row: dict[str, str], locked: dict[str, str]) -> list[str]:
    name, old_name = row.get("scientificName", ""), locked.get("scientificName", "")
    if name == old_name:
        return []
    kept = [
        field for field in _NAME_BOUND_FIELDS if row.get(field) and row[field] == locked.get(field)
    ]
    same_shape = len(name.split()) == len(old_name.split())
    if row.get("taxonRank") and row["taxonRank"] == locked.get("taxonRank") and not same_shape:
        kept.append("taxonRank")
    return kept


def confirmed_answers(taxa: dict[str, dict[str, str]]) -> dict[str, Answer]:
    return {key: sheet_answer(taxon) for key, taxon in taxa.items() if taxon.get("provenance")}


def apply_confirmed_taxa(
    resolved_by_key: dict[str, dict[str, str]],
    confirmed_rows: list[dict[str, str]],
    *,
    source: Path,
) -> tuple[dict[str, dict[str, str]], FindingsLog]:
    log = FindingsLog()
    merged = dict(resolved_by_key)
    unmatched, unattributed, inconsistent, overridden = [], [], [], []
    for row in confirmed_rows:
        key = row.get("lineage_key", "")
        locked = resolved_by_key.get(key)
        if locked is None:
            unmatched.append(key)
        elif _same_taxon(row, locked):
            continue
        elif not sheet_answer(row).provenance:
            unattributed.append(key)
        elif kept := _kept_from_the_old_name(row, locked):
            inconsistent.append(f"{key} keeps {locked['scientificName']}'s {', '.join(kept)}")
        else:
            merged[key] = row
            overridden.append(f"{key} ({row['provenance']})")
    refuse_unprovenanced(source, unattributed)
    if overridden:
        log.add(
            "TAXON_OVERRIDDEN",
            f"{len(overridden)} lineage(s) took their row from {source}: {', '.join(overridden)}",
            count=len(overridden),
        )
    if inconsistent:
        log.add(
            "TAXON_OVERRIDE_INCONSISTENT",
            f"{len(inconsistent)} row(s) of {source} change scientificName but keep what "
            f"belongs to the old name, so they were not applied: {'; '.join(inconsistent)}. "
            "Give the new name's scientificNameID, taxonRank and scientificNameAuthorship, "
            "or leave each you don't know blank",
            count=len(inconsistent),
        )
    if unmatched:
        log.add(
            "CONFIRMED_ROW_UNMATCHED",
            f"{len(unmatched)} row(s) of {source} name a lineage_key resolved_taxonomy.tsv does "
            f"not have: {', '.join(unmatched)}. Remove each row, or take its lineage_key from "
            "proposed/taxa.tsv, then build again",
            count=len(unmatched),
        )
    return merged, log


def taxa_for_join(
    lock_rows: list[dict[str, str]],
    confirmed_rows: list[dict[str, str]] | None,
    *,
    confirmed_source: Path,
) -> tuple[dict[str, dict[str, str]], FindingsLog]:
    resolved_by_key = {row["lineage_key"]: row for row in lock_rows}
    if confirmed_rows is None:
        return resolved_by_key, FindingsLog()
    return apply_confirmed_taxa(resolved_by_key, confirmed_rows, source=confirmed_source)


def check_published_taxa(table: Table, taxa_by_key: dict[str, dict[str, str]]) -> FindingsLog:
    log = FindingsLog()
    name_by_id = {
        t.get("scientificNameID", ""): t.get("scientificName", "") for t in taxa_by_key.values()
    }
    pairs = from_rows(
        table.con,
        "published_pairs",
        {NAME: "VARCHAR", NAME_ID: "VARCHAR"},
        list(
            {
                (t.get("scientificName", ""), t.get("scientificNameID", ""))
                for t in taxa_by_key.values()
            }
        ),
    )
    name, taxon_id = table.text("scientificName", "row"), table.text("scientificNameID", "row")
    stray, first_name, first_id = table.one(
        f"SELECT count(*), arg_min({name}, row.{ROW}), arg_min({taxon_id}, row.{ROW}) "
        f"FROM {table.name} AS row ANTI JOIN {pairs.name} AS pair "
        f"ON {name} = pair.{NAME} AND {taxon_id} = pair.{NAME_ID}"
    )
    if stray:
        log.add(
            "TAXON_NOT_FROM_LOCK",
            f"{stray} row(s) publish a scientificName the taxonomy join didn't write, such "
            f"as {first_name!r} with {first_id!r}, which resolved_taxonomy.tsv names "
            f"{name_by_id.get(first_id, '(no taxon)')!r}. Change a taxon in "
            "confirmed/taxa.tsv, never in another sheet",
            count=stray,
        )
    return log
