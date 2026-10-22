from __future__ import annotations

from pathlib import Path

from edna2dwc.common.tsv import write_tsv
from edna2dwc.conversion import artifacts
from edna2dwc.dwca import writer
from tests import manifests

COLUMNS = ["occurrenceID", "scientificName", "basisOfRecord"]
TERM_TABLE = {column: {"uri": f"http://rs.tdwg.org/dwc/terms/{column}"} for column in COLUMNS}


def write_one_occurrence_archive(out_dir: Path, scientific_name: str = "A") -> Path:
    core_path = out_dir.parent / f"{out_dir.name}_occurrence.tsv"
    row = {
        "occurrenceID": "ds_s1_f1",
        "scientificName": scientific_name,
        "basisOfRecord": "MaterialSample",
    }
    write_tsv([row], core_path, columns=COLUMNS)
    writer.write_archive(
        core_path=core_path,
        extensions={},
        manifest=manifests.required_manifest(),
        dataset_id="ds",
        generated_at="2024-06-01T00:00:00Z",
        term_table=TERM_TABLE,
        out_dir=out_dir,
    )
    return out_dir / artifacts.ZIP_NAME
