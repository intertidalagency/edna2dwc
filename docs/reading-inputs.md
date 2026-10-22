# Reading inputs

Every conversion reads its inputs into one file, `occurrence_long.tsv`, the intermediate table, in two steps. A reader script written for the dataset reads each file's format into plain tables: counts, features, samples and sequences. `edna2dwc assemble` then joins those tables the same way for every dataset. The script handles what differs between datasets, such as a workbook's layout, and the tool handles what shouldn't, such as how a join treats a key with no counterpart. Everything after the table is the same whichever script read the files.

## The intermediate table

One row per sample and feature, tab-separated UTF-8, with no tab or line break inside a value.

| Column | Required | Holds |
| --- | --- | --- |
| `sampleID` | yes | The sample |
| `featureID` | yes | The ASV or OTU, unique across markers |
| `count` | yes | A number, 0 or more |
| `taxonomy` | one of these taxonomy columns | One lineage: ranks separated by `;` or `\|`, with optional `k__`-style prefixes, or every segment labelled, as `Kingdom: Bacteria \| Phylum: Proteobacteria` |
| `kingdom` to `genus` | one of these taxonomy columns | One column per rank, in any case |
| `species` or `scientificName` | one of these taxonomy columns | The name the source gives, in any case |
| `marker` | with several markers | The key of the marker's entry under `markers:` in `answers.yaml` |
| `sequence` or `DNA_sequence` | no | The feature's DNA sequence |
| `source_taxon_id` | no | A WoRMS AphiaID or LSID |
| `ncbi_taxid` | no | An NCBI taxonomy ID, as a number or `NCBI:txid<number>` |

`resolve-taxonomy` writes `scientificNameID`, `taxonRank`, `scientificNameAuthorship`, `taxonomicStatus` and `taxonConceptID`, so the table can't have a column of those names: its values would be lost. The check refuses one as `CONTRACT_COLUMN_RESERVED`. Give an NCBI taxid as `ncbi_taxid`, a WoRMS AphiaID as `source_taxon_id`, and anything else under another name.

Every other column passes through under its source name. `build` maps a column whose name is a Darwin Core term or a known alias to that term, and proposes the mapping for review in `proposed/term_mapping.tsv`. Any other column goes into `dynamicProperties`. It becomes rows of the `extendedmeasurementorfact` extension when its name is a known measurement, such as temperature or salinity, or when at least 95% of its values are numbers. The proposal names each such column with the target `extendedmeasurementorfact`, and a row of `confirmed/term_mapping.tsv` with the target `dynamicProperties` keeps it out. A value that isn't a number, such as the range `0-100`, is published as written.

`edna2dwc validate-intermediate occurrence_long.tsv` checks the table and prints its schema with `--help`. It reports each kind of problem once, with how many rows have it and the first few row numbers. It warns with `TAXONOMY_BLANK` when no row has a lineage, which usually means the reader script read the taxonomy from the wrong column: every occurrence would be published as the placeholder taxon `Biota incertae sedis`.

## What the tool does, so the script doesn't

- **Zero counts.** `assemble` drops zero counts and reports how many as `PRESENCE_ONLY_FILTERED`. A zero read count in metabarcoding isn't evidence of absence. For a targeted assay with a recorded detection limit, `assemble --keep-zeros` keeps them and `build` publishes them as absences: [Derived fields](derived-fields.md#absences) explains how.
- **No-assignment strings.** `NA`, `unassigned`, `no hit` and the other strings [Taxonomy](taxonomy.md#no-assignment-sentinels) lists read as empty wherever a taxon name is expected.
- **Controls, excluded taxa, constants and units.** These are answers in `answers.yaml`, each with its provenance: `controls:`, `markers.<marker>.exclude_taxa`, `constants:` and `units:`. A script that decides one of them hides the decision, and the fabrication audit reports it.

## The packages a script may use

`edna2dwc doctor` lists them and names the Python that has them: pandas, openpyxl, h5py, pypdf, pyproj and timezonefinder, plus the standard library. `replay` runs each recorded script under `uv run`, with the Python and package versions the conversion recorded and nothing else installed. A script that imports any other package, `edna2dwc` included, fails on replay.

An R script, such as one that exports a phyloseq object to CSV, is recorded the same way. It replays only where R and the packages it loads are installed.

## Before you write the script

`edna2dwc inspect PATH...` names each file's format and what reads it, and writes `INSPECTION.md`. It reshapes nothing. A directory stands for every non-hidden file under it, and a `.csv.gz` or `.tsv.gz` is treated as its uncompressed form.

| Format | Read with |
| --- | --- |
| CSV or TSV | `pandas.read_csv` |
| Excel workbook | `pandas.read_excel`. Headers are often not on row 1, and one sheet per plate or run is common. openpyxl reads the workbook's 1900 or 1904 date system |
| QIIME 2 `.qza` | `zipfile`. The payload is under `<uuid>/data/`: `feature-table.biom` (BIOM 2.x in HDF5), `taxonomy.tsv` or `dna-sequences.fasta` |
| BIOM | `json` for version 1. `h5py` for version 2, where the counts are a compressed sparse matrix under `observation/matrix` |
| phyloseq `.rds` | `Rscript`, writing `otu_table`, `tax_table`, `sample_data` and `refseq` to CSV |
| FASTA | Nothing: copy it into `tables/`, and `assemble --sequences` joins it on `featureID` |
| PDF tables | `pypdf` |

A methods write-up, README or protocol (`.md`, `.pdf`, `.docx` and similar) is reported as `document`, with the start of its text. It is read for dataset metadata, never for occurrences. `edna2dwc text FILE...` prints all of a document's text, and each sheet of a workbook as tab-separated rows.

A file `inspect` can't identify is reported as unrecognized, with a preview of its first bytes. Identify it from its extension, its companion files or the tool that made it.

`edna2dwc detect-redundant PATH...` reads delimited text, gzipped or not. It fingerprints each file and gives a verdict for every pair:

| Verdict | Meaning |
| --- | --- |
| `likely redundant` | Same identifiers, same row count, totals equal within tolerance |
| `raw vs. normalized, not redundant` | Same identifiers, different totals |
| `coincidental` | Different identifiers, same total |
| `blank` | One of the files has no rows, or its counts total zero |
| `distinct` | None of the above |

## Values a script has to get right

- **Dates** are ISO 8601, in the source's time zone or none. Don't append `Z`, which asserts UTC.
- **Coordinates** are decimal degrees. A `ddmm.mmm` value with no sign takes it from its hemisphere. NAD83 and WGS84 are different datums: convert with pyproj and set `geodeticDatum` to `EPSG:4326`.
- **Two coordinate pairs**, as on a trawl: use the complete pair, never a start latitude with an end longitude, and say which in `locationRemarks`.
- **Join keys** that don't match between files are never dropped silently. A key in one file and not the other is either a sample one file lacks or a control.

## Joining the tables

```bash
edna2dwc assemble --counts tables/counts.csv --features tables/taxonomy.csv --samples tables/samples.csv --sequences tables/sequences.fasta
```

| Option | Table | Key |
| --- | --- | --- |
| `--counts` | Long, with `sampleID`, `featureID` and `count`, or wide, with `featureID`, an optional `marker`, and one column of counts per sample | `featureID`, `sampleID` |
| `--features` | One row per feature, such as the taxonomy | `featureID` |
| `--samples` | One row per sample, such as the sample metadata | `sampleID` |
| `--sequences` | A FASTA whose record IDs are featureIDs | the record ID |

Each option repeats, for one table per marker. The `marker` column goes on the count tables only, and `assemble` refuses it on a features or samples table, because each feature takes its marker from its count table. `assemble` drops every zero count, from a long table's rows or a wide table's cells, and reports how many as `PRESENCE_ONLY_FILTERED`. `--keep-zeros` keeps them, for a targeted assay that publishes them as absences. It joins every table on its key without dropping a row: a key with no counterpart keeps its row, with blank columns, and is reported as `JOIN_UNMATCHED`. A key repeated in a features or samples table, a FASTA ID with two sequences, or a column two tables both give stops it. It reports each input's rows and count total as `INPUT_TOTALS`, and `build` copies these findings into the conversion report while the table is the one `assemble` wrote. It records itself in `conversion.yaml` after the reader scripts and checks the table it wrote.

`assemble` reads only files under `tables/`, and refuses any other. A replay writes `tables/` again by running the recorded reader scripts, so `reproduce/` never holds a table, and a file `assemble` read from anywhere else would be missing. A source file already in the right shape still needs a reader script, even one that only copies it into `tables/`, recorded with `--raw` for the source file.

The agent skill has a short, tested snippet for each common format that reads a file into these tables. [The quickstart](quickstart.md#4-read-the-files-into-the-intermediate-table) shows the one for Excel.

## Record the script

`replay` runs only what `conversion.yaml` records, so record every script that wrote a table `assemble` reads:

```bash
edna2dwc record-step --config conversion.yaml --script read_inputs.py --command "python scripts/read_inputs.py data/export.txt" --raw data/export.txt
```

This copies the script into `scripts/`, records its hash and the command, and lists `data/export.txt` under `raw_inputs:`, so `build` bundles it. `replay` runs from the bundle root, so the command names `scripts/read_inputs.py`, and it starts with bare `python`, which `replay` provides. Keep raw inputs inside the conversion directory, named by a relative path in the command and in the script, and name each in `--raw`: `record-step` refuses a step whose command or script names an absolute path, a path above the conversion directory, or a file no `--raw` names, since a replay has only the recorded scripts, the raw inputs and an empty `tables/`. A new script goes after the other scripts and before `assemble`. Recording a changed script again replaces its step.
