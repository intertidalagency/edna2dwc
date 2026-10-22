from __future__ import annotations

import re

    has_organelle_marker,
    is_kingdom_uninformative,
    kingdoms_implausible,
)
    BIOTA_APHIA_ID,
    BIOTA_INCERTAE_SEDIS,
    BIOTA_INCERTAE_SEDIS_APHIA_ID,
    AphiaRecord,
    WormsClient,
    WormsError,
)



class HomonymTiebreakError(RuntimeError):


@dataclass
class ResolvedTaxon:
    lineage_key: str
    scientific_name: str
    scientific_name_id: str
    taxon_rank: str
    scientific_name_authorship: str
    taxonomic_status: str
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

    def to_row(self) -> dict[str, str]:
        return {
            "lineage_key": self.lineage_key,
            "scientificName": self.scientific_name,
            "scientificNameID": self.scientific_name_id,
            "taxonRank": self.taxon_rank,
            "scientificNameAuthorship": self.scientific_name_authorship,
            "taxonomicStatus": self.taxonomic_status,
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
        }


    return ResolvedTaxon(
        lineage_key="",
        scientific_name=r.scientificname,
        scientific_name_id=r.lsid,
        taxon_rank=r.rank,
        scientific_name_authorship=r.authority,
        taxonomic_status=r.status,
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
        taxon_concept_id="",
        resolution_path=resolution_path,
        authority="worms",
    )


_APHIA_LSID_RE = re.compile(r"^urn:lsid:marinespecies\.org:taxname:(\d+)$")


def _parse_aphia_id(source_taxon_id: str) -> int | None:
    match = _APHIA_LSID_RE.match(source_taxon_id.strip())


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
        return "TAXON_REJECTED_KINGDOM"
    return None


def _from_gbif_match(m: GbifMatch, *, resolution_path: str) -> ResolvedTaxon:
    return ResolvedTaxon(
        lineage_key="",
        scientific_name=m.canonical_name or m.scientific_name,
        taxon_rank=m.rank,
        scientific_name_authorship="",
        taxonomic_status=m.status.lower(),
        taxon_concept_id=m.taxon_concept_id,
        kingdom=m.kingdom,
        phylum=m.phylum,
        class_=m.class_,
        order=m.order,
        family=m.family,
        genus=m.genus,
        resolution_path=resolution_path,
        authority="gbif",
    )


def _from_gbif_species_record(raw: dict, *, resolution_path: str) -> ResolvedTaxon:
    usage_key = raw.get("key")
    return ResolvedTaxon(
        lineage_key="",
        scientific_name=raw.get("canonicalName") or raw.get("scientificName") or "",
        taxon_rank=raw.get("rank") or "",
        scientific_name_authorship=raw.get("authorship") or "",
        taxonomic_status=(raw.get("taxonomicStatus") or "").lower(),
        kingdom=raw.get("kingdom") or "",
        phylum=raw.get("phylum") or "",
        class_=raw.get("class") or "",
        order=raw.get("order") or "",
        family=raw.get("family") or "",
        genus=raw.get("genus") or "",
        resolution_path=resolution_path,
        authority="gbif",
    )


def _homonym_tiebreak(
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


class TaxonResolver:
    def __init__(
        self,
        worms: WormsClient,
        *,
        gbif: GbifClient | None = None,
        terminal_fallback: str = "incertae_sedis",
    ):
        self._worms = worms
        self._gbif = gbif

    def _bump(self, code: str) -> None:

    def _terminal(self) -> ResolvedTaxon:
        if self._terminal_fallback == "biota":
            return _biota(resolution_path="biota_fallback")
        return _biota_incertae_sedis(resolution_path="biota_fallback")

        plausible = []
        for candidate in candidates:
            if rejection is None:
                plausible.append(candidate)
            else:
                self._bump(rejection)

            )
        if len(confident) == 1:
            return _from_worms_record(confident[0], resolution_path="leaf")
        if len(plausible) == 1:
        return None

        resolved_by_part = [
        ]
        resolved = [r for _, r in resolved_by_part if r is not None]

        part_notes = []
        for part, r in resolved_by_part:
            if r is not None and r.needs_review:
                note = f"{part}:{r.review_reason}"
                if r.candidate_ids:
                    note += f":{r.candidate_ids}"
                part_notes.append(note)

            attr = "class_" if rank == "class" else rank
                if ancestor is None:
                    continue
                ancestor.resolution_path = "compound_common_ancestor"

        result = self._terminal()
        result.resolution_path = "compound_common_ancestor"

        normalized = normalize_name(terminal_name)
            return
        try:
            candidates = self._worms.match_one(normalized)
        except WormsError:
            return
        if contradicting:

    def resolve(
        self,
        terminal_name: str,
        source_ranks: dict[str, str],
        *,
        source_taxon_id: str = "",
        ncbi_taxid: str = "",
    ) -> ResolvedTaxon:
        if aphia_id is not None:
            record = self._worms.record_by_aphia_id(aphia_id)
            if record is not None:
                result = _from_worms_record(record, resolution_path="leaf")
                return result

        return result

    def _resolve_by_name_chain(
    ) -> ResolvedTaxon:

        if resolved is not None:
            return resolved

            if resolved is not None:
                if resolved.resolution_path == "leaf":
                    resolved.resolution_path = "rank_backoff"
                return resolved

    ) -> ResolvedTaxon | None:
            return None

        alternatives = [GbifMatch.from_raw(a) for a in match.alternatives]
            and match.status == "SYNONYM"
            and match.accepted_usage_key is not None
        ):

        worms_confident = [
            c
        ]
        return result
