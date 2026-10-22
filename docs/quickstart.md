# Quickstart

This page takes one dataset from raw files to a checked archive. With an agent and the `convert-edna-to-dwc` skill, the agent runs these commands and asks you for the answers. Every command also runs by hand.

> **What you need**
>
> - `edna2dwc` installed, as the [README](../README.md#install) describes. `edna2dwc doctor` checks it.
> - Your data files: counts, taxonomy and sample metadata, in whatever format your pipeline wrote.
> - The documents that describe them, such as a methods write-up, for the dataset metadata and the primers.
> - A directory to work in. On macOS, use one outside `~/Documents`, `~/Desktop` and `~/Downloads`. See [Troubleshooting](troubleshooting.md#macos-denies-access-to-a-folder).
> - Optionally, a GBIF account for the GBIF check in step 7. See [Credentials](credentials.md).

## 1. Inspect your files

```bash
edna2dwc inspect data/
```

`inspect` prints each file's format and writes `INSPECTION.md`. The page names the feature table and taxonomy source it found, the Darwin Core terms your columns supply, the terms the tool will derive, and the terms nothing supplies. It says what reads each file. It reads nothing into the conversion.

If two delimited tables might contain the same feature table, one raw and one normalized, compare them:

```bash
edna2dwc detect-redundant data/asv_counts.tsv data/asv_relative.tsv
```

Any verdict other than `distinct` needs a look. Normalized abundances published as read counts are a defect no later step can catch. `detect-redundant` reads delimited text only, so it can't compare `.qza` or BIOM files.

## 2. Start the conversion

```bash
edna2dwc init --dataset-id my-survey-2026 --scan data/
```

Run this in the conversion directory. It writes three files there:

- `answers.yaml`, a commented skeleton of every answer the dataset needs from you. The tool writes it once and never again, so your edits stay.
- `conversion.yaml`, which records the reader scripts, the raw inputs and the environment.
- a `justfile` of common recipes.

The `--dataset-id` becomes the first part of every `occurrenceID`. Keep it stable: a new ID republishes every record as a new record. It can't be blank or contain a colon. With no identifier in the sources, use a short label from the study or file name, never a made-up DOI or URL.

`--created` defaults to now and is recorded once, so a rebuild produces the same bytes. `--out-dir` defaults to `archive`.

`--scan` looks for an `eml.xml` and copies its metadata, such as the title, abstract, creators and publication date, into `answers.yaml`, each with `provenance: "eml.xml <field>"` and an empty `confirmed`, so a person confirms them once.

## 3. Answer what you can now

`build` stops until `answers.yaml` holds every answer it needs, which [A conversion](commands.md#a-conversion) lists. You can give these three now.

**Dataset metadata.** Title, creators, abstract, license, contacts and publication date (`pub_date`). Every answer is `{value, provenance, confirmed}`: `provenance` says what the value rests on, and `confirmed` holds a person's reply or nothing. See [Provenance and confirmation](metadata.md#provenance-and-confirmation). Creators and contacts are lists of people. See [Dataset metadata](metadata.md#what-emlxml-holds).

```yaml
metadata:
  title: {value: "Puget Sound eDNA survey 2026", provenance: "eml.xml title", confirmed: "J. Smith: yes"}
  creators: {value: [{given: Jo, surname: Smith, email: jsmith@example.org}], provenance: "eml.xml creator", confirmed: "J. Smith: yes"}
```

**What each marker amplifies.** One entry per value of the table's `marker` column, or exactly one entry, under any name, if the table has no marker column:

```yaml
markers:
  12S: {target: vertebrates, provenance: "methods.pdf p4, MiFish primers", confirmed: "J. Smith: fish only"}
```

Take the answer from the primer sequences or the methods text, and say where in `provenance:`. A marker's name doesn't settle it: "16S" is both a bacterial target and a vertebrate mitochondrial marker. With `filters.exclude_kingdoms`, a wrong answer deletes the wrong half of your data. [Excluding taxa](controls-and-exclusions.md#excluding-taxa) lists the valid answers.

**Ambiguous samples.** `build` asks about a sample whose ID only weakly matches a control keyword. Answer under `controls:`. See [Controls and exclusions](controls-and-exclusions.md).

An unknown key in `answers.yaml` fails the build and names the key. So does a column it names, such as `filters.sample_type_col`, that the table or file doesn't have, and `filters.sample_type_col` or `filters.sample_metadata` given without the other.

## 4. Read the files into the intermediate table

Every conversion reads its data files into one table, `occurrence_long.tsv`, with one row per sample and feature. A short Python or R script written for your files does the reading. With the skill, the agent writes it. Without one, here is a script for a workbook with a sheet each for counts, taxonomy and samples:

```python
from pathlib import Path

import pandas as pd

workbook = "data/samples.xlsx"
Path("tables").mkdir(exist_ok=True)

counts = pd.read_excel(workbook, sheet_name="Counts", dtype=str)
counts.rename(columns={"ASV_ID": "featureID"}).to_csv("tables/counts.csv", index=False)

taxonomy = pd.read_excel(workbook, sheet_name="Taxonomy", dtype=str)
taxonomy = taxonomy.rename(columns={"OTU_ID": "featureID", "Taxon": "taxonomy"})
taxonomy.to_csv("tables/taxonomy.csv", index=False)

samples = pd.read_excel(workbook, sheet_name="Samples", dtype=str)
samples.rename(columns={"Sample Name": "sampleID"}).to_csv("tables/samples.csv", index=False)
```

The script only reads: it renames each table's key column to `featureID` or `sampleID` and writes plain tables to `tables/`. Run it with the Python `edna2dwc doctor` names, and record it so a replay can run it again. Then `assemble` joins the tables into `occurrence_long.tsv`, records itself, and checks the result:

```bash
python read_inputs.py
edna2dwc record-step --config conversion.yaml --script read_inputs.py --command "python scripts/read_inputs.py" --raw data/samples.xlsx
edna2dwc assemble --counts tables/counts.csv --features tables/taxonomy.csv --samples tables/samples.csv
```

[Reading inputs](reading-inputs.md) describes the tables, the packages a script may import, and how each format reads. `replay` runs only recorded scripts, so a conversion that used an unrecorded one can't be replayed.

## 5. Resolve the taxonomy

```bash
edna2dwc resolve-taxonomy
```

`resolve-taxonomy` looks up each distinct lineage in the table against WoRMS and GBIF, under the `taxonomy:` settings in `answers.yaml`, and writes `resolved_taxonomy.tsv`. `build` reads that file and doesn't call a register. Run `resolve-taxonomy` again after the table or the `taxonomy:` settings change. `build` stops and says so when the table has a lineage the file lacks. [Taxonomy](taxonomy.md) describes the settings.

It prints an estimate on stderr when it starts:

```text
resolve-taxonomy terminal names: 11,257 distinct names
  2,155 cached, 9,102 to look up -> 183 requests, 4 at a time
  rough estimate 61 min, refined once it starts
  up to 3,410 more names if these find no match
```

Taxonomy resolution is usually the longest step. Its time depends on the number of distinct names, not the number of records. Names already in the on-disk cache cost nothing.

## 6. Build

```bash
edna2dwc build
```

`build` runs the [packaging steps](commands.md#what-build-does) in order and writes the archive. It recomputes everything each time, so run it as often as you like. It writes `REVIEW.md`, which says what is waiting on you and how to close each item. Close the items, then run `build` again. Repeat until `REVIEW.md` says the conversion finished. You will meet these stops.

**A missing answer.** `build` stops before writing the archive. `REVIEW.md` names the key to set in `answers.yaml`, as in step 3.

**A proposal to review.** The tool has an answer for you to check: the sample roster, the term mapping, the resolved taxonomy, or a suspect derived value. It writes each one to `proposed/` on every build. To accept a proposal, copy its header to `confirmed/` and build again:

```bash
mkdir -p confirmed
head -1 proposed/taxa.tsv > confirmed/taxa.tsv
edna2dwc build
```

To correct a proposal, add to that sheet only the rows you change, each with what the change rests on in its `provenance` column, such as `genus was misidentified`, and the person's reply in `confirmed`. The sample roster is the exception: settle a sample under `controls:` in `answers.yaml` instead. [Reviewing a proposal](commands.md#reviewing-a-proposal) has the details.

**The fabrication audit.** After the build, an independent reviewer checks that every value in the archive comes from an input. Print its prompt, give it to a fresh agent that has seen only the source files and the archive, then record the result:

```bash
edna2dwc audit prompt archive/ --source data/samples.xlsx --source data/methods.pdf
edna2dwc audit record archive/ --from-file audit_result.json
```

`audit record` lists each finding in `CONVERSION_REPORT.md`. It doesn't wait on them: the reviewer can be wrong, and whether to fix one is your call. See [The fabrication audit](fabrication-audit.md).

**An error.** `REVIEW.md` lists the error under "Waiting on you". Fix the input or the answer it names, and build again.

`resolve-taxonomy` prints its progress on stderr. `--quiet` or `EDNA2DWC_QUIET=1` turns it off.

## 7. Evaluate the archive

```bash
edna2dwc evaluate archive/
```

`evaluate` runs the OBIS checks and the term, mapping and row checks, and with `--gbif` GBIF's validator, and writes `EVALUATION.md` beside `dwca.zip` (not inside it). Each check is passed, failed or not measured, and "not measured" never counts as passed. The page lists every missing term with the state the conversion recorded for it. The page opens with the verdict of the two validators: "GBIF and OBIS validators: accept", "reject" or "not measured". The command exits non-zero until every check passes, apart from the advisory check of strongly recommended terms. Without `--gbif`, the GBIF check reads "not measured" and doesn't decide the exit code.

The GBIF check needs `--gbif` and a [GBIF account](credentials.md). Without either, the check reads "not measured", and so does the validators' verdict.

`CONVERSION_REPORT.md` sits beside `dwca.zip`, outside it, and lists what the conversion did and what it couldn't do. Pass it on with the archive, unchanged.

## 8. Check that it reproduces

```bash
edna2dwc replay --check .
```

Run this from the conversion directory. It copies only `archive/reproduce/` to a scratch directory, reruns the recorded reader scripts and `build --automatic` there, and compares the result with `archive/dwca.zip`. A difference, or a build that ends in `error`, exits non-zero.

The replay installs the package versions `conversion.yaml` recorded, which needs network access. Offline, add `--unpin` to use the installed ones. [Reproducibility](reproducibility.md) covers the bundle and the other ways to replay.

## Run unattended

```bash
edna2dwc build --automatic
```

`--automatic` uses every proposal nobody confirmed, and every answer with `confirmed` empty, as written, and logs each one. It still stops on a missing answer. Use it when there is nobody to ask, or on a dataset you have already converted once.
