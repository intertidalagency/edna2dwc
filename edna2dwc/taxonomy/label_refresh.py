from __future__ import annotations

from typing import TYPE_CHECKING

from edna2dwc.taxonomy.worms import AphiaRecord, WormsClient

if TYPE_CHECKING:
    from edna2dwc.taxonomy.resolve_taxonomy import ResolvedTaxon


def refresh_labels(resolved: list[ResolvedTaxon], worms: WormsClient) -> None:
    distinct_ids = {
        r.aphia_id for r in resolved if r.authority == "worms" and r.aphia_id and not r.provenance
    }
    refreshed: dict[str, AphiaRecord] = {}
    for aphia_id in distinct_ids:
        record = worms.current_record_by_aphia_id(int(aphia_id))
        if record is not None:
            refreshed[aphia_id] = record

    for row in resolved:
        if row.provenance or row.authority != "worms":
            continue
        record = refreshed.get(row.aphia_id)
        if record is None:
            continue
        if (
            row.scientific_name != record.scientificname
            or row.taxonomic_status != record.status
            or row.kingdom != record.kingdom
            or row.phylum != record.phylum
            or row.class_ != record.class_
            or row.order != record.order
            or row.family != record.family
            or row.genus != record.genus
        ):
            row.scientific_name = record.scientificname
            row.taxonomic_status = record.status
            row.kingdom = record.kingdom
            row.phylum = record.phylum
            row.class_ = record.class_
            row.order = record.order
            row.family = record.family
            row.genus = record.genus
            row.findings.append("TAXON_LABEL_STALE")
