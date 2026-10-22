# Reading an Excel workbook

Read each sheet with pandas, rename its key column to `featureID` or `sampleID`, and write it as a CSV in `tables/`. Then `assemble` joins the sheets.

```python
from pathlib import Path

import pandas as pd

workbook = "raw/multisheet.xlsx"
Path("tables").mkdir(exist_ok=True)

counts = pd.read_excel(workbook, sheet_name="Counts", dtype=str)
counts.rename(columns={"ASV_ID": "featureID"}).to_csv("tables/counts.csv", index=False)

taxonomy = pd.read_excel(workbook, sheet_name="Taxonomy", dtype=str)
taxonomy = taxonomy.rename(columns={"OTU_ID": "featureID", "Taxon": "taxonomy"})
taxonomy.to_csv("tables/taxonomy.csv", index=False)

samples = pd.read_excel(workbook, sheet_name="Samples", dtype=str)
samples.rename(columns={"Sample Name": "sampleID"}).to_csv("tables/samples.csv", index=False)
```

```bash
edna2dwc assemble --counts tables/counts.csv --features tables/taxonomy.csv --samples tables/samples.csv
```

- **Headers are often not on row 1.** Read the sheet with `header=None`, find the header row by eye from `edna2dwc text`, and pass `header=<row index>`. Never guess a fixed row.
- **Per-run copies of a sheet** are one table. Concatenate them with `pd.concat`, after checking that their headers agree.
- **Dates.** With `dtype=str`, a date cell reads as `2021-06-01 00:00:00`. Read date columns without `dtype=str` and format them as ISO 8601 with `.dt.strftime("%Y-%m-%d")`, keeping a time only when the cell has one. openpyxl applies the workbook's 1900 or 1904 date system. A date column of plain numbers is Excel serial days: convert it with `pd.to_datetime(values, unit="D", origin="1899-12-30")`, or origin `1904-01-01` when the workbook uses that system.
- **`ddmm.mmm` coordinates** take their sign from the hemisphere the sheet or methods state:

```python
def ddmm(value: str, hemisphere: str) -> float:
    degrees, minutes = divmod(abs(float(value)), 100)
    return (-1 if hemisphere in "SW" else 1) * (degrees + minutes / 60)
```

- **NAD83 coordinates** are converted, never relabelled: `pyproj.Transformer.from_crs("EPSG:4269", "EPSG:4326", always_xy=True)`, then give `geodeticDatum: EPSG:4326` under `constants:`, with the conversion as its provenance.
- **A sample name that differs between sheets** (`S001` and `S1`) breaks the join. `assemble` keeps the row and reports the key. Fix the names in the reader script, and tell the researcher how.
