# Reading a BIOM table

BIOM 2.x is HDF5: read it as [`qiime2.md`](qiime2.md) reads `feature-table.biom`, with `h5py.File(path)`. BIOM 1.0 is JSON:

```python
import json
from pathlib import Path

import pandas as pd

with open("raw/sample_v1.biom", encoding="utf-8") as f:
    biom = json.load(f)
features = [row["id"] for row in biom["rows"]]
samples = [column["id"] for column in biom["columns"]]
if biom["matrix_type"] == "sparse":
    cells = biom["data"]
else:
    cells = [(i, j, v) for i, row in enumerate(biom["data"]) for j, v in enumerate(row)]

Path("tables").mkdir(exist_ok=True)
pd.DataFrame(
    [(samples[j], features[i], int(v) if float(v).is_integer() else v) for i, j, v in cells if v],
    columns=["sampleID", "featureID", "count"],
).to_csv("tables/counts.csv", index=False)

taxonomy = [
    (row["id"], ";".join((row.get("metadata") or {}).get("taxonomy") or []))
    for row in biom["rows"]
]
pd.DataFrame(taxonomy, columns=["featureID", "taxonomy"]).to_csv(
    "tables/taxonomy.csv", index=False
)
```

```bash
edna2dwc assemble --counts tables/counts.csv --features tables/taxonomy.csv
```

- A whole-number count can arrive as `10.0`. Write it as `10`, or `organismQuantity` is published as `10.0`.
