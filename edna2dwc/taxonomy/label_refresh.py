from __future__ import annotations



    distinct_ids = {
    }
    refreshed: dict[str, AphiaRecord] = {}
    for aphia_id in distinct_ids:
        if record is not None:
            refreshed[aphia_id] = record

    for row in resolved:
            continue
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
