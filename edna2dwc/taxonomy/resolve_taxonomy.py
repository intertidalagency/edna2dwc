from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import TypeVar

import httpx

from edna2dwc.common import progress
from edna2dwc.common.findings import FindingsLog
from edna2dwc.common.result import CommandResult, lines, render_findings
from edna2dwc.common.tsv import write_tsv
from edna2dwc.conversion.answers import REGISTERS, TaxonomySettings
from edna2dwc.conversion.intermediate import RANK_COLUMNS
from edna2dwc.taxonomy.derive_lineage import UNRANKED_COLUMN
from edna2dwc.taxonomy.gbif import GbifClient, GbifMatch, species_url
from edna2dwc.taxonomy.label_refresh import refresh_labels
from edna2dwc.taxonomy.plausibility import (
    domains_implausible,
    has_organelle_marker,
    is_kingdom_uninformative,
    kingdom_group,
    kingdoms_implausible,
)
from edna2dwc.taxonomy.taxon_normalize import (
    COMPOUND_SEPARATOR_RE,
    NCBI_TAXIDS_NAMING_NO_TAXON,
    is_rank_word,
    ncbi_taxid_digits,
    normalize_name,
)
from edna2dwc.taxonomy.unassigned import is_no_assignment, is_placeholder_taxon
from edna2dwc.taxonomy.worms import (
    BIOTA_APHIA_ID,
    BIOTA_INCERTAE_SEDIS,
    BIOTA_INCERTAE_SEDIS_APHIA_ID,
    AphiaRecord,
    WormsClient,
    WormsError,
)

RANKS_FROM_GENUS_UP = tuple(reversed(RANK_COLUMNS))
MASS_COLLAPSE_MIN_NAMES = 5

STAGE = "resolve-taxonomy"
TERMINAL_PASS = f"{STAGE} terminal names"
RANK_BACKOFF_PASS = f"{STAGE} rank backoff"
LINEAGE_PASS = f"{STAGE} lineages"


OpenRegisters = Callable[[TaxonomySettings], tuple[WormsClient, GbifClient | None]]


def register_clients(
    cache_dir: Path | None, *, client: httpx.Client | None = None
) -> OpenRegisters:
    def open_registers(settings: TaxonomySettings) -> tuple[WormsClient, GbifClient | None]:
        worms = WormsClient(
            client=client, cache_dir=cache_dir, marine_only=settings.marine_only, stage=STAGE
        )
        gbif = (
            GbifClient(client=client, cache_dir=cache_dir)
            if "gbif" in settings.registers
            else None
        )
        return worms, gbif

    return open_registers


class HomonymTiebreakError(RuntimeError):
    pass


@dataclass
class ResolvedTaxon:
    lineage_key: str
    scientific_name: str
    scientific_name_id: str
    taxon_rank: str
    scientific_name_authorship: str
    taxonomic_status: str
    aphia_id: str
    taxon_concept_id: str
    kingdom: str = ""
    phylum: str = ""
    class_: str = ""
    order: str = ""
    family: str = ""
    genus: str = ""
    resolution_path: str = ""
    needs_review: bool = False
    review_reason: str = ""
    candidate_ids: str = ""
    authority: str = ""
    provenance: str = ""
    confirmed: str = ""
    gbif_usage_key: str = ""
    findings: list[str] = field(default_factory=list)
    settings: str = ""

    def to_row(self) -> dict[str, str]:
        return {
            "lineage_key": self.lineage_key,
            "scientificName": self.scientific_name,
            "scientificNameID": self.scientific_name_id,
            "taxonRank": self.taxon_rank,
            "scientificNameAuthorship": self.scientific_name_authorship,
            "taxonomicStatus": self.taxonomic_status,
            "aphia_id": self.aphia_id,
            "taxonConceptID": self.taxon_concept_id,
            "kingdom": self.kingdom,
            "phylum": self.phylum,
            "class": self.class_,
            "order": self.order,
            "family": self.family,
            "genus": self.genus,
            "resolution_path": self.resolution_path,
            "needs_review": "true" if self.needs_review else "false",
            "review_reason": self.review_reason,
            "candidate_ids": self.candidate_ids,
            "authority": self.authority,
            "provenance": self.provenance,
            "confirmed": self.confirmed,
            "gbif_usage_key": self.gbif_usage_key,
            FINDINGS_COLUMN: ", ".join(self.findings),
            SETTINGS_COLUMN: self.settings,
        }


def _from_worms_record(r: AphiaRecord, *, resolution_path: str) -> ResolvedTaxon:
    return ResolvedTaxon(
        lineage_key="",
        scientific_name=r.scientificname,
        scientific_name_id=r.lsid,
        taxon_rank=r.rank,
        scientific_name_authorship=r.authority,
        taxonomic_status=r.status,
        aphia_id=str(r.aphia_id),
        taxon_concept_id="",
        kingdom=r.kingdom,
        phylum=r.phylum,
        class_=r.class_,
        order=r.order,
        family=r.family,
        genus=r.genus,
        resolution_path=resolution_path,
        authority="worms",
    )


def _biota_incertae_sedis(*, resolution_path: str) -> ResolvedTaxon:
    return ResolvedTaxon(
        lineage_key="",
        scientific_name=BIOTA_INCERTAE_SEDIS,
        scientific_name_id=f"urn:lsid:marinespecies.org:taxname:{BIOTA_INCERTAE_SEDIS_APHIA_ID}",
        taxon_rank="Kingdom",
        scientific_name_authorship="",
        taxonomic_status="accepted",
        aphia_id=str(BIOTA_INCERTAE_SEDIS_APHIA_ID),
        taxon_concept_id="",
        kingdom=BIOTA_INCERTAE_SEDIS,
        resolution_path=resolution_path,
        authority="worms",
    )


def _biota(*, resolution_path: str) -> ResolvedTaxon:
    return ResolvedTaxon(
        lineage_key="",
        scientific_name="Biota",
        scientific_name_id=f"urn:lsid:marinespecies.org:taxname:{BIOTA_APHIA_ID}",
        taxon_rank="Kingdom",
        scientific_name_authorship="",
        taxonomic_status="accepted",
        aphia_id=str(BIOTA_APHIA_ID),
        taxon_concept_id="",
        kingdom="",
        resolution_path=resolution_path,
        authority="worms",
    )


_APHIA_LSID_RE = re.compile(r"^urn:lsid:marinespecies\.org:taxname:(\d+)$")


def _parse_aphia_id(source_taxon_id: str) -> int | None:
    match = _APHIA_LSID_RE.match(source_taxon_id.strip())
    digits = match.group(1) if match else source_taxon_id.strip()
    return int(digits) if digits.isdigit() and int(digits) else None


def _comparable_name(name: str) -> str:
    return " ".join(re.sub(r"\([^)]*\)", " ", name.replace("_", " ")).split()).casefold()


_Candidate = TypeVar("_Candidate", AphiaRecord, GbifMatch)


def _is_confident(candidate: AphiaRecord | GbifMatch, query: str) -> bool:
    return candidate.is_confident_match_type and _comparable_name(
        candidate.name
    ) == _comparable_name(query)


def _confident_accepted(candidates: Iterable[_Candidate], query: str) -> list[_Candidate]:
    return [c for c in candidates if _is_confident(c, query) and c.is_accepted]


def _rejection_reason(
    candidate: AphiaRecord | GbifMatch, query: str, source_ranks: dict[str, str]
) -> str | None:
    source_kingdom = source_ranks.get("kingdom", "")
    if has_organelle_marker(
        source_ranks.get("genus", ""),
        source_ranks.get("family", ""),
        source_ranks.get("order", ""),
        source_ranks.get("class", ""),
    ):
        if candidate.kingdom.casefold() == source_kingdom.casefold():
            return None
        return "TAXON_REJECTED_ORGANELLE"
    implausible = domains_implausible if _is_confident(candidate, query) else kingdoms_implausible
    if implausible(source_kingdom, candidate.kingdom):
        return "TAXON_REJECTED_KINGDOM"
    return None


def _from_gbif_match(m: GbifMatch, *, resolution_path: str) -> ResolvedTaxon:
    return ResolvedTaxon(
        lineage_key="",
        scientific_name=m.canonical_name or m.scientific_name,
        scientific_name_id=m.taxon_concept_id,
        taxon_rank=m.rank,
        scientific_name_authorship="",
        taxonomic_status=m.status.lower(),
        aphia_id="",
        taxon_concept_id=m.taxon_concept_id,
        kingdom=m.kingdom,
        phylum=m.phylum,
        class_=m.class_,
        order=m.order,
        family=m.family,
        genus=m.genus,
        resolution_path=resolution_path,
        authority="gbif",
        gbif_usage_key="" if m.usage_key is None else str(m.usage_key),
    )


def _from_gbif_species_record(raw: dict, *, resolution_path: str) -> ResolvedTaxon:
    usage_key = raw.get("key")
    return ResolvedTaxon(
        lineage_key="",
        scientific_name=raw.get("canonicalName") or raw.get("scientificName") or "",
        scientific_name_id=species_url(usage_key),
        taxon_rank=raw.get("rank") or "",
        scientific_name_authorship=raw.get("authorship") or "",
        taxonomic_status=(raw.get("taxonomicStatus") or "").lower(),
        aphia_id="",
        taxon_concept_id=species_url(usage_key),
        kingdom=raw.get("kingdom") or "",
        phylum=raw.get("phylum") or "",
        class_=raw.get("class") or "",
        order=raw.get("order") or "",
        family=raw.get("family") or "",
        genus=raw.get("genus") or "",
        resolution_path=resolution_path,
        authority="gbif",
        gbif_usage_key="" if usage_key is None else str(usage_key),
    )


def _from_candidate(candidate: AphiaRecord | GbifMatch, *, resolution_path: str) -> ResolvedTaxon:
    if isinstance(candidate, AphiaRecord):
        return _from_worms_record(candidate, resolution_path=resolution_path)
    return _from_gbif_match(candidate, resolution_path=resolution_path)


_UNACCEPTED_STATUS_REASON = {"worms": "unaccepted_status", "gbif": "gbif_status"}


def _for_review(result: ResolvedTaxon, review_reason: str) -> ResolvedTaxon:
    result.needs_review = True
    result.review_reason = review_reason
    return result


def _homonym_tiebreak(
    candidates: list[_Candidate], source_phylum: str, source_class: str
) -> tuple[_Candidate | None, str]:
    if len(candidates) < 2:
        raise HomonymTiebreakError(
            f"_homonym_tiebreak needs >=2 candidates, got {len(candidates)}"
        )

    surviving = candidates
    phylum_matched = False
    class_matched = False

    if source_phylum:
        phylum_agreeing = [c for c in surviving if c.phylum.casefold() == source_phylum.casefold()]
        if phylum_agreeing:
            surviving = phylum_agreeing
            phylum_matched = True

    if source_class:
        class_agreeing = [c for c in surviving if c.class_.casefold() == source_class.casefold()]
        if class_agreeing:
            surviving = class_agreeing
            class_matched = True

    if len(surviving) == 1:
        return surviving[0], "homonym_disambiguated"

    any_signal_supplied = bool(source_phylum or source_class)
    any_signal_matched = phylum_matched or class_matched
    if any_signal_supplied and not any_signal_matched:
        return None, "homonym_source_mismatch"
    return None, "ambiguous_homonym"


def _expand_compound_parts(name: str) -> list[str]:
    parts = [p.strip() for p in COMPOUND_SEPARATOR_RE.split(name) if p.strip()]
    last_genus = ""
    expanded = []
    for part in parts:
        tokens = part.split()
        if len(tokens) == 1 and last_genus and tokens[0].islower():
            expanded.append(f"{last_genus} {tokens[0]}")
        else:
            expanded.append(part)
            if len(tokens) >= 2:
                last_genus = tokens[0]
    return expanded


def _flag_for_review(result: ResolvedTaxon, reason: str) -> None:
    result.needs_review = True
    result.review_reason = "; ".join(filter(None, (result.review_reason, reason)))


def _is_sendable(name: str) -> bool:
    return bool(name) and not is_no_assignment(name) and not is_rank_word(name)


def _names_a_rank_word(
    normalized: str, source_ranks: Mapping[str, str], unranked: Sequence[str]
) -> bool:
    names = (*COMPOUND_SEPARATOR_RE.split(normalized), *source_ranks.values(), *unranked)
    return any(is_rank_word(name) for name in names)


def _single_terminal_name(lineage_row: Mapping[str, str]) -> str:
    terminal = normalize_name(lineage_row.get("terminal_name", ""))
    if not _is_sendable(terminal) or COMPOUND_SEPARATOR_RE.search(terminal):
        return ""
    return terminal


def _terminal_lookup_names(lineage_row: Mapping[str, str]) -> list[str]:
    single = _single_terminal_name(lineage_row)
    if single:
        return [single]
    terminal = normalize_name(lineage_row.get("terminal_name", ""))
    if not _is_sendable(terminal):
        return []
    parts = (normalize_name(part) for part in _expand_compound_parts(terminal))
    return [part for part in parts if _is_sendable(part)]


def _terminal_prefetch_names(lineage_rows: Iterable[Mapping[str, str]]) -> Iterator[str]:
    return (name for row in lineage_rows for name in _terminal_lookup_names(row))


def _rank_backoff_ceiling_names(lineage_rows: Iterable[Mapping[str, str]]) -> Iterator[str]:
    return (
        name
        for row in lineage_rows
        if _single_terminal_name(row) or _backs_off_without_a_terminal_lookup(row)
        for name in _lineage_backoff_names(row)
    )


def _backs_off_without_a_terminal_lookup(lineage_row: Mapping[str, str]) -> bool:
    return not _is_sendable(normalize_name(lineage_row.get("terminal_name", "")))


def _backoff_names(source_ranks: Mapping[str, str], unranked: Sequence[str]) -> list[str]:
    values = (
        reversed(unranked)
        if unranked
        else (source_ranks.get(rank, "") for rank in RANKS_FROM_GENUS_UP)
    )
    names = (normalize_name(value) for value in values)
    return [name for name in names if _is_sendable(name)]


def _unranked_names(lineage_row: Mapping[str, str]) -> tuple[str, ...]:
    return tuple(name for name in lineage_row.get(UNRANKED_COLUMN, "").split(";") if name)


def _with_unranked_kingdom(
    source_ranks: dict[str, str], unranked: Sequence[str]
) -> dict[str, str]:
    if source_ranks.get("kingdom") or not unranked or kingdom_group(unranked[0]) is None:
        return source_ranks
    return {**source_ranks, "kingdom": unranked[0]}


def _source_ranks(lineage_row: Mapping[str, str]) -> dict[str, str]:
    return {rank: lineage_row.get(f"source_{rank}", "") for rank in RANK_COLUMNS}


def _lineage_backoff_names(lineage_row: Mapping[str, str]) -> list[str]:
    return _backoff_names(_source_ranks(lineage_row), _unranked_names(lineage_row))


FINDINGS_COLUMN = "findings"
SETTINGS_COLUMN = "settings"

_LOCK_FINDINGS = {
    "TAXON_UNRESOLVED": (
        "lineage(s) matched nothing in the registers asked, neither at the terminal name nor at "
        "any name above it in the source lineage, so the placeholder taxon was used. Sentinels "
        "and rank words are never looked up, nor is a name with an underscore, such as the clade "
        "label SAR11_clade or the strain label Cyanobium_PCC-6307"
    ),
    "TAXON_FUZZY": "lineage(s) kept a non-confident match rather than being left unresolved",
    "TAXON_RANK_WORD_REFUSED": (
        "lineage(s) named a bare rank word such as Genus or Species where a taxon belongs, so "
        "that name was never looked up. A rank label was read as a name: fix the step that "
        "wrote the taxonomy column or rank columns of occurrence_long.tsv, then rerun "
        "resolve-taxonomy"
    ),
    "TAXON_FUZZY_REJECTED": (
        "non-confident match(es) were refused because a confident one was required, so "
        "resolution backed off to a higher rank; a lineage refused at several ranks counts once "
        "per rank, so this is not a count of lineages"
    ),
    "SOURCE_KINGDOM_UNINFORMATIVE": (
        "lineage(s) had a source kingdom too coarse to contradict anything (a domain, not a "
        "kingdom), so the cross-kingdom check could not discriminate and only confident matches "
        "were accepted for them"
    ),
    "TAXON_REJECTED_KINGDOM": (
        "candidate(s) rejected because their kingdom contradicted the source classifier's"
    ),
    "TAXON_REJECTED_ORGANELLE": (
        "candidate(s) rejected as an organelle marker whose kingdom didn't match the source's"
    ),
    "TAXON_AMBIGUOUS_HOMONYM": (
        "name(s) had two or more exact, accepted candidates that the phylum/class tiebreak could "
        "not narrow to one"
    ),
    "TAXON_HOMONYM_DISAMBIGUATED": (
        "name(s) had a homonym tie broken confidently using the source's phylum/class"
    ),
    "TAXON_ID_CONTRADICTS_SOURCE": (
        "lineage(s) kept a source_taxon_id that the terminal name's WoRMS match contradicts; "
        "review_reason names both IDs"
    ),
    "TAXON_ID_UNCHECKED": (
        "lineage(s) kept a source_taxon_id that WoRMS didn't answer to check against the terminal "
        "name; run resolve-taxonomy again to check them"
    ),
    "NCBI_TAXID_MALFORMED": (
        "lineage(s) had an ncbi_taxid that is malformed or names no taxon, so it wasn't "
        "published; review_reason names it"
    ),
    "TAXON_MASS_COLLAPSE": (
        f"lineage(s) resolved to a taxon that {MASS_COLLAPSE_MIN_NAMES} or more differently "
        "named lineages share, though no name in their source lineages is that taxon. This "
        "usually means the source names were misread: compare scientificName with the source "
        "in resolved_taxonomy.tsv, then fix the taxonomy column of occurrence_long.tsv and "
        "rerun resolve-taxonomy, or correct the rows in confirmed/taxa.tsv"
    ),
    "TAXON_LABEL_STALE": "lineage(s) had their label refreshed from the register",
    "TAXON_LABEL_REFRESH_INCOMPLETE": (
        "lineage(s) kept the label they resolved with, because WoRMS didn't answer the label "
        "refresh"
    ),
}


def lock_findings(lock_rows: Iterable[Mapping[str, str]]) -> FindingsLog:
    counts = Counter(
        code for row in lock_rows for code in row.get(FINDINGS_COLUMN, "").split(", ") if code
    )
    log = FindingsLog()
    for code, description in _LOCK_FINDINGS.items():
        if counts[code]:
            log.add(
                code,
                f"{counts[code]} {description}. The {FINDINGS_COLUMN} column of the taxonomy lock "
                "names each lineage",
                count=counts[code],
            )
    return log


def _names_in_lineage(lineage_row: Mapping[str, str]) -> set[str]:
    terminal = normalize_name(lineage_row.get("terminal_name", ""))
    names = (terminal, *_source_ranks(lineage_row).values(), *_unranked_names(lineage_row))
    return {_comparable_name(name) for name in names if name}


def _lands_outside_its_lineage(lineage_row: Mapping[str, str], locked: Mapping[str, str]) -> bool:
    name = locked.get("scientificName", "")
    return (
        bool(name)
        and not is_placeholder_taxon(name)
        and _comparable_name(name) not in _names_in_lineage(lineage_row)
    )


def mass_collapsed_keys(
    lineage_rows: Iterable[Mapping[str, str]], lock_rows: Iterable[Mapping[str, str]]
) -> set[str]:
    lock_by_key = {row["lineage_key"]: row for row in lock_rows}
    outside = {
        row["lineage_key"]: (
            _comparable_name(normalize_name(row["terminal_name"])),
            _comparable_name(lock_by_key[row["lineage_key"]]["scientificName"]),
        )
        for row in lineage_rows
        if _lands_outside_its_lineage(row, lock_by_key[row["lineage_key"]])
    }
    names_by_taxon: dict[str, set[str]] = {}
    for source_name, taxon in outside.values():
        names_by_taxon.setdefault(taxon, set()).add(source_name)
    return {
        key
        for key, (_, taxon) in outside.items()
        if len(names_by_taxon[taxon]) >= MASS_COLLAPSE_MIN_NAMES
    }


class TaxonResolver:
    def __init__(
        self,
        worms: WormsClient,
        *,
        gbif: GbifClient | None = None,
        registers: tuple[str, ...] = REGISTERS,
        terminal_fallback: str = "incertae_sedis",
        require_confident: bool = True,
    ):
        self._worms = worms
        self._gbif = gbif
        self._registers = tuple(r for r in registers if r == "worms" or gbif is not None)
        self._terminal_fallback = terminal_fallback
        self._require_confident = require_confident
        self._findings: list[str] = []

    def _asks_worms(self) -> bool:
        return "worms" in self._registers

    def prefetch(self, lineage_rows: Iterable[Mapping[str, str]]) -> None:
        if not self._asks_worms():
            return
        rows = list(lineage_rows)
        terminal_names = list(dict.fromkeys(_terminal_prefetch_names(rows)))
        progress.report_lookups(
            self._worms.cache_status(terminal_names),
            stage=TERMINAL_PASS,
            follow_up_ceiling=len(set(_rank_backoff_ceiling_names(rows))),
        )
        candidates = self._match_all(terminal_names, stage=TERMINAL_PASS)
        backing_off = [
            row
            for row in rows
            if _backs_off_without_a_terminal_lookup(row)
            or (_single_terminal_name(row) and not candidates.get(_single_terminal_name(row)))
        ]
        backoff_names = list(
            dict.fromkeys(name for row in backing_off for name in _lineage_backoff_names(row))
        )
        if backoff_names:
            progress.report_lookups(
                self._worms.cache_status(backoff_names), stage=RANK_BACKOFF_PASS
            )
        self._match_all(backoff_names, stage=RANK_BACKOFF_PASS)

    def _match_all(self, names: Iterable[str], *, stage: str | None = None) -> dict[str, list]:
        return self._worms.match_names(
            list(dict.fromkeys(names)), isolate_failures=True, stage=stage
        )

    def _bump(self, code: str) -> None:
        self._findings.append(code)

    def _terminal(self) -> ResolvedTaxon:
        if self._terminal_fallback == "biota":
            return _biota(resolution_path="biota_fallback")
        return _biota_incertae_sedis(resolution_path="biota_fallback")

    def _plausible(
        self, candidates: Iterable[_Candidate], name: str, source_ranks: dict[str, str]
    ) -> list[_Candidate]:
        candidates = [c for c in candidates if not is_rank_word(c.name)]
        plausible = []
        for candidate in candidates:
            rejection = _rejection_reason(candidate, name, source_ranks)
            if rejection is None:
                plausible.append(candidate)
            else:
                self._bump(rejection)
        return plausible

    def _break_homonym_tie(
        self, confident: list[_Candidate], source_ranks: dict[str, str]
    ) -> ResolvedTaxon:
        winner, reason = _homonym_tiebreak(
            confident, source_ranks.get("phylum", ""), source_ranks.get("class", "")
        )
        if winner is not None:
            self._bump("TAXON_HOMONYM_DISAMBIGUATED")
            return _from_candidate(winner, resolution_path=reason)
        self._bump("TAXON_AMBIGUOUS_HOMONYM")
        result = _for_review(_from_candidate(confident[0], resolution_path="leaf"), reason)
        result.candidate_ids = "|".join(str(c.register_id) for c in confident)
        return result

    def _kept_despite_doubt(
        self, candidate: AphiaRecord | GbifMatch, name: str, *, require_confident: bool
    ) -> ResolvedTaxon | None:
        reasons = []
        if not _is_confident(candidate, name):
            if require_confident:
                self._bump("TAXON_FUZZY_REJECTED")
                return None
            reasons.append(
                f"name_mismatch:{candidate.name}"
                if candidate.is_confident_match_type
                else f"non_confident_match_type:{candidate.match_type}"
            )
            self._bump("TAXON_FUZZY")
        result = _from_candidate(candidate, resolution_path="leaf")
        if not candidate.is_accepted:
            reasons.append(f"{_UNACCEPTED_STATUS_REASON[result.authority]}:{candidate.status}")
        return _for_review(result, ",".join(reasons))

    def _resolve_at_worms(
        self, name: str, source_ranks: dict[str, str], *, require_confident: bool
    ) -> ResolvedTaxon | None:
        plausible = self._plausible(self._worms.match_one(name), name, source_ranks)
        confident = _confident_accepted(plausible, name)
        if len(confident) >= 2:
            return self._break_homonym_tie(confident, source_ranks)
        if len(confident) == 1:
            return _from_worms_record(confident[0], resolution_path="leaf")
        if len(plausible) == 1:
            return self._kept_despite_doubt(
                plausible[0], name, require_confident=require_confident
            )
        return None

    def _resolve_compound(
        self, name: str, source_ranks: dict[str, str], *, require_confident: bool
    ) -> ResolvedTaxon:
        expanded = _expand_compound_parts(name)
        resolved_by_part = [
            (
                part,
                self._resolve_at_registers(
                    normalize_name(part), source_ranks, require_confident=require_confident
                ),
            )
            for part in expanded
        ]
        resolved = [r for _, r in resolved_by_part if r is not None]
        unresolved_parts = [part for part, r in resolved_by_part if r is None]
        if unresolved_parts:
            reason = (
                f"compound_name_part_unresolved:{'|'.join(unresolved_parts)}"
                if resolved
                else "compound_name_unresolved"
            )
            return self._compound_placeholder(reason)

        part_notes = []
        for part, r in resolved_by_part:
            if r is not None and r.needs_review:
                note = f"{part}:{r.review_reason}"
                if r.candidate_ids:
                    note += f":{r.candidate_ids}"
                part_notes.append(note)

        for rank in RANKS_FROM_GENUS_UP:
            attr = "class_" if rank == "class" else rank
            values = {getattr(r, attr) for r in resolved}
            if len(values) == 1 and (shared_name := next(iter(values))):
                ancestor = self._resolve_at_registers(
                    normalize_name(shared_name),
                    source_ranks,
                    require_confident=require_confident,
                )
                if ancestor is None:
                    continue
                ancestor.resolution_path = "compound_common_ancestor"
                return _for_review(
                    ancestor, "; ".join(["compound_name_common_ancestor", *part_notes])
                )

        return self._compound_placeholder("; ".join(["compound_name_no_shared_rank", *part_notes]))

    def _compound_placeholder(self, review_reason: str) -> ResolvedTaxon:
        result = self._terminal()
        result.resolution_path = "compound_common_ancestor"
        return _for_review(result, review_reason)

    def _check_id_against_source(
        self, id_result: ResolvedTaxon, source_record: AphiaRecord, terminal_name: str
    ) -> None:
        normalized = normalize_name(terminal_name)
        if not _is_sendable(normalized):
            return
        try:
            candidates = self._worms.match_one(normalized)
        except WormsError:
            _flag_for_review(
                id_result,
                f"WoRMS didn't answer, so the source's taxon ID {id_result.aphia_id} wasn't "
                "checked against the name",
            )
            self._bump("TAXON_ID_UNCHECKED")
            return
        confident = _confident_accepted(candidates, normalized)
        agreeing = {source_record.aphia_id, source_record.valid_aphia_id}
        contradicting = sorted({c.aphia_id for c in confident} - agreeing)
        if contradicting:
            _flag_for_review(
                id_result,
                f"the source's taxon ID {id_result.aphia_id} disagrees with the WoRMS match "
                f"for the name, {', '.join(map(str, contradicting))}",
            )
            self._bump("TAXON_ID_CONTRADICTS_SOURCE")

    def resolve(
        self,
        terminal_name: str,
        source_ranks: dict[str, str],
        *,
        source_taxon_id: str = "",
        ncbi_taxid: str = "",
        unranked: Sequence[str] = (),
    ) -> ResolvedTaxon:
        self._findings = []
        result = self._resolve(
            terminal_name,
            _with_unranked_kingdom(source_ranks, unranked),
            unranked,
            source_taxon_id=source_taxon_id,
            ncbi_taxid=ncbi_taxid,
        )
        result.findings = self._findings
        return result

    def _resolve(
        self,
        terminal_name: str,
        source_ranks: dict[str, str],
        unranked: Sequence[str],
        *,
        source_taxon_id: str,
        ncbi_taxid: str,
    ) -> ResolvedTaxon:
        if _names_a_rank_word(normalize_name(terminal_name), source_ranks, unranked):
            self._bump("TAXON_RANK_WORD_REFUSED")
        aphia_id = _parse_aphia_id(source_taxon_id) if self._asks_worms() else None
        if aphia_id is not None:
            record = self._worms.record_by_aphia_id(aphia_id)
            if record is not None:
                result = _from_worms_record(record, resolution_path="leaf")
                self._check_id_against_source(result, record, terminal_name)
                self._apply_ncbi_precedence(result, ncbi_taxid)
                return result

        result = self._resolve_by_name_chain(normalize_name(terminal_name), source_ranks, unranked)
        self._apply_ncbi_precedence(result, ncbi_taxid)
        return result

    def _apply_ncbi_precedence(self, result: ResolvedTaxon, ncbi_taxid: str) -> None:
        if not ncbi_taxid.strip() or is_no_assignment(ncbi_taxid):
            return
        digits = ncbi_taxid_digits(ncbi_taxid)
        if digits and digits not in NCBI_TAXIDS_NAMING_NO_TAXON:
            result.taxon_concept_id = f"NCBI:txid{digits}"
            return
        problem = (
            f"names {NCBI_TAXIDS_NAMING_NO_TAXON[digits]}, not a taxon"
            if digits
            else "is not a number or NCBI:txid<number>"
        )
        kept = (
            f"taxonConceptID keeps {result.taxon_concept_id}"
            if result.taxon_concept_id
            else "taxonConceptID was left blank"
        )
        self._bump("NCBI_TAXID_MALFORMED")
        result.needs_review = True
        result.review_reason = "; ".join(
            filter(
                None,
                (
                    result.review_reason,
                    f"the source's NCBI taxid {ncbi_taxid!r} {problem}, so {kept}",
                ),
            )
        )

    def _resolve_by_name_chain(
        self, normalized: str, source_ranks: dict[str, str], unranked: Sequence[str]
    ) -> ResolvedTaxon:
        require_confident = self._require_confident or is_kingdom_uninformative(
            source_ranks.get("kingdom", "")
        )
        if require_confident and not self._require_confident:
            self._bump("SOURCE_KINGDOM_UNINFORMATIVE")

        if not _is_sendable(normalized):
            resolved = self._resolve_by_rank_backoff(
                source_ranks, unranked, require_confident=require_confident
            )
            if resolved is not None:
                return resolved
            return _biota_incertae_sedis(resolution_path="incertae_sedis_placeholder")

        if COMPOUND_SEPARATOR_RE.search(normalized):
            return self._resolve_compound(
                normalized, source_ranks, require_confident=require_confident
            )

        resolved = self._resolve_at_registers(
            normalized, source_ranks, require_confident=require_confident
        )
        if resolved is not None:
            if resolved.resolution_path == "leaf" and resolved.authority != self._registers[0]:
                resolved.resolution_path = f"{resolved.authority}_fallback"
            return resolved

        resolved = self._resolve_by_rank_backoff(
            source_ranks, unranked, require_confident=require_confident
        )
        if resolved is not None:
            return resolved

        self._bump("TAXON_UNRESOLVED")
        return self._terminal()

    def _resolve_by_rank_backoff(
        self,
        source_ranks: dict[str, str],
        unranked: Sequence[str],
        *,
        require_confident: bool,
    ) -> ResolvedTaxon | None:
        for name in _backoff_names(source_ranks, unranked):
            resolved = self._resolve_at_registers(
                name, source_ranks, require_confident=require_confident
            )
            if resolved is not None:
                if resolved.resolution_path == "leaf":
                    resolved.resolution_path = "rank_backoff"
                return resolved
        return None

    def _resolve_at_registers(
        self, name: str, source_ranks: dict[str, str], *, require_confident: bool
    ) -> ResolvedTaxon | None:
        if not _is_sendable(name):
            return None
        for register in self._registers:
            resolve_at = self._resolve_at_worms if register == "worms" else self._resolve_at_gbif
            resolved = resolve_at(name, source_ranks, require_confident=require_confident)
            if resolved is not None:
                return resolved
        return None

    def _resolve_at_gbif(
        self, name: str, source_ranks: dict[str, str], *, require_confident: bool
    ) -> ResolvedTaxon | None:
        gbif = self._gbif
        if gbif is None:
            return None
        match = gbif.match(name, kingdom=source_ranks.get("kingdom", ""))
        if match.is_no_match or not self._plausible([match], name, source_ranks):
            return None
        result = self._resolve_gbif_match(
            gbif, match, name, source_ranks, require_confident=require_confident
        )
        if result is None or not self._asks_worms():
            return result
        return self._with_worms_lsid(result, name)

    def _resolve_gbif_match(
        self,
        gbif: GbifClient,
        match: GbifMatch,
        name: str,
        source_ranks: dict[str, str],
        *,
        require_confident: bool,
    ) -> ResolvedTaxon | None:
        alternatives = [GbifMatch.from_raw(a) for a in match.alternatives]
        confident = _confident_accepted([match, *alternatives], name)
        if len(confident) >= 2:
            return self._break_homonym_tie(confident, source_ranks)
        if _is_confident(match, name) and match.is_accepted:
            return _from_gbif_match(match, resolution_path="leaf")
        if (
            _is_confident(match, name)
            and match.status == "SYNONYM"
            and match.accepted_usage_key is not None
        ):
            accepted = gbif.species_by_key(match.accepted_usage_key)
            if accepted is None:
                return _for_review(
                    _from_gbif_match(match, resolution_path="leaf"),
                    "gbif_synonym_accepted_lookup_failed",
                )
            return _for_review(
                _from_gbif_species_record(accepted, resolution_path="leaf"),
                "gbif_synonym_resolved_to_accepted",
            )
        if match.match_type == "HIGHERRANK":
            return _for_review(
                _from_gbif_match(match, resolution_path="leaf"), "gbif_higher_rank_match"
            )
        return self._kept_despite_doubt(match, name, require_confident=require_confident)

    def _with_worms_lsid(self, result: ResolvedTaxon, name: str) -> ResolvedTaxon:
        lsid_name = result.scientific_name or name
        worms_confident = [
            c
            for c in _confident_accepted(self._worms.match_one(lsid_name), lsid_name)
            if c.kingdom.casefold() == result.kingdom.casefold()
        ]
        confirmed = worms_confident[0] if len(worms_confident) == 1 else None
        if len(worms_confident) >= 2:
            confirmed, _ = _homonym_tiebreak(worms_confident, result.phylum, result.class_)
        if confirmed is not None:
            result.scientific_name_id = confirmed.lsid
            result.aphia_id = str(confirmed.aphia_id)
        return result


def step(
    *,
    lineage_rows: list[dict[str, str]],
    output_path: Path,
    settings_by_scope: Mapping[str, TaxonomySettings],
    open_registers: OpenRegisters,
    as_json: bool = False,
) -> CommandResult:
    rows_by_scope: dict[str, list[dict[str, str]]] = {}
    for lineage_row in lineage_rows:
        rows_by_scope.setdefault(lineage_row.get("taxonomy_scope", ""), []).append(lineage_row)
    resolved_by_key = {
        resolved.lineage_key: resolved
        for scope, rows in rows_by_scope.items()
        for resolved in _resolve_scope(rows, settings_by_scope[scope], open_registers)
    }

    for key in mass_collapsed_keys(lineage_rows, lock_rows(lineage_rows, resolved_by_key)):
        resolved_by_key[key].needs_review = True
        resolved_by_key[key].findings.append("TAXON_MASS_COLLAPSE")

    resolved_rows = lock_rows(lineage_rows, resolved_by_key)
    write_tsv(resolved_rows, output_path, columns=lock_columns(resolved_rows))
    log = lock_findings(resolved_rows)
    return CommandResult.of(
        "resolve-taxonomy",
        log,
        outputs={"resolved_taxonomy": str(output_path)},
        text=lines(
            f"Resolved {len(resolved_rows)} distinct lineage(s) to {output_path}",
            render_findings(log),
        ),
        as_json=as_json,
    )


def _source_lineage(lineage_row: Mapping[str, str]) -> str:
    ranks = [lineage_row.get(f"source_{rank}", "") for rank in RANK_COLUMNS]
    names = [name for name in (*_unranked_names(lineage_row), *ranks) if name]
    terminal = lineage_row.get("terminal_name", "")
    return "; ".join([*names, *([terminal] if terminal and terminal not in names else [])])


def lock_rows(
    lineage_rows: list[dict[str, str]], resolved_by_key: Mapping[str, ResolvedTaxon]
) -> list[dict[str, str]]:
    return [
        {
            "lineage_key": row["lineage_key"],
            "source_name": row.get("terminal_name", ""),
            "source_lineage": _source_lineage(row),
            **resolved_by_key[row["lineage_key"]].to_row(),
        }
        for row in lineage_rows
    ]


LEADING_LOCK_COLUMNS = ("lineage_key", "source_name", "source_lineage")


def lock_columns(rows: list[dict[str, str]]) -> list[str]:
    rest = sorted({name for row in rows for name in row} - set(LEADING_LOCK_COLUMNS))
    return [*LEADING_LOCK_COLUMNS, *rest]


def _resolve_scope(
    lineage_rows: list[dict[str, str]],
    settings: TaxonomySettings,
    open_registers: OpenRegisters,
) -> list[ResolvedTaxon]:
    worms, gbif_client = open_registers(settings)
    resolver = TaxonResolver(
        worms,
        gbif=gbif_client,
        registers=settings.registers,
        terminal_fallback=settings.terminal_fallback.replace("-", "_"),
        require_confident=settings.require_confident,
    )

    try:
        resolver.prefetch(lineage_rows)

        lineage_bar = progress.BatchProgress(
            total_batches=len(lineage_rows),
            stage=LINEAGE_PASS,
            unit="lineages",
        )
        resolved_taxa: list[ResolvedTaxon] = []
        for lineage_row in lineage_rows:
            resolved = resolver.resolve(
                lineage_row["terminal_name"],
                _source_ranks(lineage_row),
                source_taxon_id=lineage_row.get("source_taxon_id", ""),
                ncbi_taxid=lineage_row.get("ncbi_taxid", ""),
                unranked=_unranked_names(lineage_row),
            )
            resolved.lineage_key = lineage_row["lineage_key"]
            resolved.settings = settings.describe()
            resolved_taxa.append(resolved)
            lineage_bar.advance(1)
        lineage_bar.finish()

        if settings.refresh_labels and "worms" in settings.registers:
            try:
                refresh_labels(resolved_taxa, worms)
            except WormsError:
                for resolved in resolved_taxa:
                    if resolved.authority == "worms" and not resolved.provenance:
                        resolved.findings.append("TAXON_LABEL_REFRESH_INCOMPLETE")
    finally:
        worms.close()
        if gbif_client is not None:
            gbif_client.close()
    return resolved_taxa
