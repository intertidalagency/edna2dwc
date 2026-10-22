# A worked example

This page runs one conversion from start to finish on a tiny synthetic workbook, the test fixture `tests/fixtures/inputs/multisheet.xlsx`, copied to `data/reef_survey.xlsx`. Every output below is what the commands printed, trimmed where marked. The workbook has three sheets:

| Sheet | Contents |
| --- | --- |
| Samples | `Sample Name`, `Site`, `Depth (m)`: S001 at North Reef, 12.5 m; S002 at South Reef, 8 m |
| Counts | `ASV_ID`, then one column of read counts per sample, for asv1 and asv2 |
| Taxonomy | `OTU_ID`, `Taxon`: asv1 is `d__Bacteria;p__Cyanobacteria`, asv2 is `d__Bacteria;p__Firmicutes` |

## Inspect and start

```bash
edna2dwc inspect data/
edna2dwc init --dataset-id reef-survey-2021 --scan data/
```

`inspect` previews each sheet, names `Counts` as the feature table, and lists the terms nothing supplies, from `annealingTemp` to `thresholdQuantificationCycle`. `init` writes `answers.yaml`, `conversion.yaml` and `justfile`.

## Read the workbook

The reader script is the one in [the quickstart](quickstart.md#4-read-the-files-into-the-intermediate-table), with `workbook = "data/reef_survey.xlsx"`.

```bash
python read_inputs.py
edna2dwc record-step --config conversion.yaml --script read_inputs.py --command "python scripts/read_inputs.py" --raw data/reef_survey.xlsx
edna2dwc assemble --counts tables/counts.csv --features tables/taxonomy.csv --samples tables/samples.csv
```

```text
Recorded step 1, scripts/read_inputs.py, in conversion.yaml.
Stage 3 of 5: Read
Next: `edna2dwc assemble` on the tables the script writes
Wrote 3 row(s) to occurrence_long.tsv, and recorded the step in conversion.yaml.
INFO: PRESENCE_ONLY_FILTERED: counts.csv: 1 empty or zero cell(s) of the wide count table were not written as rows, because a zero read count is not evidence of absence
INFO: INPUT_TOTALS: counts.csv: 3 count row(s), with a count total of 35
INFO: INPUT_TOTALS: taxonomy.csv: 2 row(s)
INFO: INPUT_TOTALS: samples.csv: 2 row(s)
OK: occurrence_long.tsv satisfies the intermediate table's schema.
Stage 3 of 5: Read
Next: `edna2dwc resolve-taxonomy`
```

asv1 has no reads in S002, so the intermediate table has three rows:

```text
sampleID  featureID  count  Depth (m)  Site        taxonomy
S001      asv1       10     12.5       North Reef  d__Bacteria;p__Cyanobacteria
S001      asv2       5      12.5       North Reef  d__Bacteria;p__Firmicutes
S002      asv2       20     8          South Reef  d__Bacteria;p__Firmicutes
```

## Resolve the taxonomy

```bash
edna2dwc resolve-taxonomy
```

Both names resolve in WoRMS, at the phylum rank the source gives: `Cyanobacteria` as `urn:lsid:marinespecies.org:taxname:146537` and `Firmicutes` as `urn:lsid:marinespecies.org:taxname:377975`, each with `resolution_path` `leaf`.

## Build until REVIEW.md is done

The first `build` stops, because `answers.yaml` is still the skeleton:

```text
needs_decision: metadata.title; metadata.creators; metadata.abstract; metadata.license; metadata.contacts; metadata.pub_date; markers
What is waiting on you, and how to close it: REVIEW.md
Stage 4 of 5: Convert
Next: close the 7 item(s) under "Waiting on you" in REVIEW.md, then `edna2dwc build`
```

`REVIEW.md` lists each key, what it means and how to set it. The answers, with the publication date left for later:

```yaml
metadata:
  title: {value: "Reef eDNA survey 2021", provenance: "asked A. Researcher", confirmed: "A. Researcher: yes"}
  abstract: {value: "16S metabarcoding of seawater from two reef sites.", provenance: "asked A. Researcher", confirmed: "A. Researcher: yes"}
  license: {value: CC-BY-4.0, provenance: "asked A. Researcher", confirmed: "A. Researcher: CC-BY"}
  creators: {value: [{given: A., surname: Researcher, organization: Example Institute}], provenance: "asked A. Researcher", confirmed: "A. Researcher: just me"}
  contacts: {value: [{given: A., surname: Researcher, email: a.researcher@example.org}], provenance: "asked A. Researcher", confirmed: "A. Researcher: yes"}
  pub_date: {value: "", provenance: "set when the archive is published", confirmed: "A. Researcher: decide at publication"}
markers:
  16S: {target: prokaryotes, provenance: "methods.pdf p2, 515F/806R primers", confirmed: "A. Researcher: yes"}
```

The second `build` writes the archive, and waits on two items:

```text
Archive built at archive.
needs_review: proposed/taxa.tsv: 2 distinct lineage(s) resolved; metadata.pub_date: blank
What is waiting on you, and how to close it: REVIEW.md
Stage 4 of 5: Convert
Next: close the 2 item(s) under "Waiting on you" in REVIEW.md, then `edna2dwc build`
```

The term mapping needed no review: `Site` maps to `locationID`, `Depth (m)` to `minimumDepthInMeters`, and `taxonomy` to `verbatimIdentification`, each by a known alias. No sample ID looks like a control.

Accept the taxonomy as resolved, set the publication date, and build again:

```bash
mkdir -p confirmed
head -1 proposed/taxa.tsv > confirmed/taxa.tsv
edna2dwc build
```

`REVIEW.md` now opens with "Finished. The archive is built.", lists nothing under "Waiting on you", and names the audit as the next step.

## What came out

```text
archive/
  dwca.zip                  the archive: occurrence.txt, meta.xml and eml.xml
  occurrence.txt, meta.xml, eml.xml   the same files, unzipped
  CONVERSION_REPORT.md      and CONVERSION_REPORT.html
  reproduce/                answers.yaml, conversion.yaml, confirmed/, data/, scripts/, resolved_taxonomy.tsv, justfile
```

One row of `occurrence.txt`, as columns:

| Term | Value |
| --- | --- |
| `occurrenceID` | `reef-survey-2021:S001:asv1` |
| `materialSampleID` | `S001` |
| `basisOfRecord` | `MaterialSample` |
| `occurrenceStatus` | `present` |
| `organismQuantity`, `organismQuantityType` | `10`, `DNA sequence reads` |
| `sampleSizeValue`, `sampleSizeUnit` | `15`, `DNA sequence reads` |
| `scientificName` | `Cyanobacteria` |
| `scientificNameID` | `urn:lsid:marinespecies.org:taxname:146537` |
| `taxonRank`, `kingdom`, `phylum` | `phylum`, `Bacteria`, `Cyanobacteria` |
| `locationID` | `North Reef` |
| `minimumDepthInMeters`, `maximumDepthInMeters` | `12.5`, `12.5` |
| `verbatimIdentification` | `d__Bacteria;p__Cyanobacteria` |

The workbook has no coordinates, dates or sequences, so the archive has none. `CONVERSION_REPORT.md` says so rather than filling them in:

```text
- **TAXON_ID_BLANK** (3): ... 3 row(s) have no DNA_sequence to hash, so taxonID is blank
- **TERM_MISSING_PRIORITY** (3): ... countryCode: 3 row(s) have no coordinates in a decimalLatitude/decimalLongitude, latitude/longitude or lat/lon column, so their countryCode was left blank
```

## Evaluate and replay

```bash
edna2dwc evaluate archive/
```

```text
Archive structure is valid: passed
Every required term is filled on every row: failed (annealingTemp (0/312 rows), countryCode (0/312 rows), decimalLatitude (0/312 rows), decimalLongitude (0/312 rows), eventDate (0/312 rows), geodeticDatum (0/312 rows))
Every strongly recommended term is filled on every row: failed (DNA_sequence (0/312 rows), annealingTempUnit (0/312 rows), ...)
Every column is a Darwin Core term: passed
Every mapped column has a traceable method: passed
Every term has a recorded state: passed
Every row is accounted for: passed
Values are in the right format: passed
GBIF validator reports no errors: not measured (not run; evaluate --gbif runs it)
OBIS checks report no errors: passed
GBIF and OBIS validators: not measured.
Wrote archive/EVALUATION.md and archive/EVALUATION.html.
Stage 5 of 5: Check
Next: close what EVALUATION.md lists, then go over the archive with the researcher
```

`evaluate` exits 1: the archive is valid, but lacks terms GBIF and OBIS expect, which only the source data or a person can supply. Each missing term is recorded as Ask in `EVALUATION.md`, with the evidence `no <term> column in the mapped occurrence table`.

```bash
edna2dwc replay --check .
```

```text
Replaying a copy of archive/reproduce; the bundle itself is only read.
# Archive comparison

No differences.
Wrote archive/comparison_summary.md.
Rebuild status: ok
```
