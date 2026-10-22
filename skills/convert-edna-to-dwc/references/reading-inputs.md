# Reading the inputs

Reading the inputs takes two steps. A reader script you write reads each file's format into plain tables. `edna2dwc assemble` joins those tables into `occurrence_long.tsv` the same way every time. No format is unsupported, so don't tell the researcher it is.

## 1. The reader script reads each format into tables

Write the tables to `tables/` as CSV, each keyed by one column. `assemble` reads nothing outside `tables/`, so a file already in the right shape, such as a FASTA, still needs the script to copy it there:

| Table | Key | Holds |
| --- | --- | --- |
| Counts | `featureID`, and `sampleID` when long | Long: `sampleID`, `featureID`, `count`. Wide: `featureID`, an optional `marker`, and one column of counts per sample. Nothing else |
| Features | `featureID` | One row per feature: the taxonomy, as a `taxonomy` lineage, rank columns, or a `species` or `scientificName` column, and any other feature column |
| Samples | `sampleID` | One row per sample: dates, coordinates, depth, measurements |
| Sequences | the record ID | A FASTA whose IDs are featureIDs |

Read the page for each format you have, and start from its snippet:

- Excel workbook → [`formats/excel.md`](formats/excel.md)
- QIIME 2 `.qza` → [`formats/qiime2.md`](formats/qiime2.md)
- BIOM → [`formats/biom.md`](formats/biom.md)
- phyloseq `.rds` → [`formats/phyloseq.md`](formats/phyloseq.md)
- CSV or TSV → `pandas.read_csv`, rename the key column, and write it out
- PDF tables → read the text with pypdf, and check every parsed row against the page

The script imports only the packages `edna2dwc doctor` lists, and runs with the python it names: `replay` runs it again with exactly those packages, so a script that imports anything else, `edna2dwc` included, can't be replayed.

The script only reads. It renames a key column to `featureID` or `sampleID`, keeps every other column under its source name, and leaves values as the source gives them, except where a value must change form:

- **Dates**: ISO 8601, keeping the source's time zone or none. Never append `Z`.
- **Coordinates**: decimal degrees, signed from their hemisphere. Convert NAD83 with pyproj, and give `geodeticDatum: EPSG:4326` under `constants:`, with the conversion as its provenance.
- **Depth ranges**: when the source states both ends of a depth range, write them as `minimumDepthInMeters` and `maximumDepthInMeters`. Leave any other range, such as `0-100` or `>0.8`, as the source writes it.
- **Two coordinate pairs**: use the complete pair. Never combine a start latitude with an end longitude, and tell the researcher which pair you used.

## 2. `assemble` joins the tables

```bash
edna2dwc assemble --counts tables/counts.csv --features tables/taxonomy.csv --samples tables/samples.csv --sequences tables/sequences.fasta
```

It drops zero counts and reports how many, turns a wide count table into one row per nonzero cell, joins every table on its key, and joins the FASTA as the `sequence` column. A key with no counterpart keeps its row and is reported, so read every `JOIN_UNMATCHED`: a sample one file lacks, a control, or two spellings of one name. It records itself in `conversion.yaml`, reports each input's rows and count total to the conversion report, and checks the table. With several markers, repeat `--counts` and `--features` for one table per marker. The `marker` column goes on the count tables only: each feature takes its marker from its count table.

## 3. Decisions go in `answers.yaml`, not the script

The script decides nothing a person should see. Each of these has a place in `answers.yaml`, with its provenance, and `build` applies it and reports it:

- Which samples are controls → `controls:`.
- Taxa the methods removed from a marker → `markers.<marker>.exclude_taxa`.
- A value the same on every row, such as a primer → `constants:` or `markers.<marker>.constants`.
- A unit only a document gives → `units:`.

Leave zero counts and `NA` or `unassigned` as the source has them: `assemble` drops zero counts, and `build` reads those strings as empty in a taxon name, and `NA`, `N/A`, `NaN` or `null` as no value in a measurement. The fabrication audit reads every recorded script and reports one that filters rows or decides one of these.

## 4. Record the script

```bash
edna2dwc record-step --config conversion.yaml --script read_inputs.py --command "python scripts/read_inputs.py" --raw <each raw file it reads>
```

This copies the script into `scripts/`, hashes it, and logs the command, before `assemble` in the steps. The command runs the copy in `scripts/`, because that is what a replay has, and starts with bare `python`, which `replay` provides. Keep each raw input inside the conversion directory, named by a relative path in the command and in the script, and name each in `--raw`. `record-step` refuses a step whose command or script names an absolute path, a path above the conversion directory, or a file no `--raw` names, because a replay has only the recorded scripts, the raw inputs and an empty `tables/`. Record a changed script again to replace its step, then run `assemble` again.
