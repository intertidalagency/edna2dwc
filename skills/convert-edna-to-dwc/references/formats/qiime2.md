# Reading QIIME 2 artifacts

A `.qza` is a zip, so it needs neither QIIME 2 nor conda. Its payload is under `<uuid>/data/`: a feature table as `feature-table.biom` (BIOM 2.x in HDF5), a taxonomy as `taxonomy.tsv`, and representative sequences as `dna-sequences.fasta`. `<uuid>/provenance/` records the denoiser, the classifier and often the primers, for `answers.yaml`.

```python
import io
from pathlib import Path
import zipfile

import h5py
import pandas as pd


def payload(qza: str, name: str) -> bytes:
    with zipfile.ZipFile(qza) as archive:
        member = next(n for n in archive.namelist() if n.split("/")[1:] == ["data", name])
        return archive.read(member)


def count(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


Path("tables").mkdir(exist_ok=True)
with h5py.File(io.BytesIO(payload("raw/table.qza", "feature-table.biom")), "r") as biom:
    features = [x.decode() for x in biom["observation/ids"][:]]
    samples = [x.decode() for x in biom["sample/ids"][:]]
    matrix = biom["observation/matrix"]
    data, indices, indptr = matrix["data"][:], matrix["indices"][:], matrix["indptr"][:]
rows = [
    (samples[indices[k]], feature, count(data[k]))
    for i, feature in enumerate(features)
    for k in range(indptr[i], indptr[i + 1])
]
pd.DataFrame(rows, columns=["sampleID", "featureID", "count"]).to_csv(
    "tables/counts.csv", index=False
)

taxonomy = pd.read_csv(io.BytesIO(payload("raw/sample.qza", "taxonomy.tsv")), sep="\t", dtype=str)
taxonomy = taxonomy.rename(columns={"Feature ID": "featureID", "Taxon": "taxonomy"})
taxonomy.to_csv("tables/taxonomy.csv", index=False)
```

```bash
edna2dwc assemble --counts tables/counts.csv --features tables/taxonomy.csv
```

- **Sequences**: write `payload(qza, "dna-sequences.fasta")` to `tables/sequences.fasta` and pass `--sequences tables/sequences.fasta`.
- **`Confidence`** in `taxonomy.tsv` is the classifier's confidence in the name, not a measurement of the sample. `build` proposes it as measurement rows because it is numeric: send it to `dynamicProperties` in `confirmed/term_mapping.tsv`.
- **Sample metadata** is a TSV, not an artifact. Its second row may be `#q2:types`: read it with `skiprows=[1]` when it is, and rename its first column to `sampleID`.
- **Several markers** each have their own table and taxonomy. Add a `marker` column to each count table, and pass each table with its own `--counts` and `--features`.
