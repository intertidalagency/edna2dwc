# Controls and exclusions

This page covers the samples and rows a conversion removes before it publishes, and how it reports them.

## Control samples

`build` decides which samples are controls and writes its classification to `proposed/control_roster.tsv`. After the taxonomy join, it removes the controls, as classified and then as `controls:` in `answers.yaml` settles them.

Classification uses the first of these that applies:

1. A type column in a sample-metadata file (`filters.sample_metadata` with `filters.sample_type_col` in `answers.yaml`).
2. A type column in the occurrence table (`filters.occurrence_type_col`).
3. A keyword in the sample ID.

The sample-metadata file needs a `sampleID` or `sample_id` column. `build` stops, naming the key, when a column either answer names isn't there.

A type value of `control`, `blank`, `negative`, `negative control`, `positive`, `positive control`, `mock`, `mock community`, `ntc` or `zymo`, in any case, marks a control. Any other type value is read with the sample-ID keywords below, so `rtsf blank` and `PCR negative control` mark controls, and `NC` alone asks. A type value with no keyword, such as `seawater`, leaves the sample ID to decide.

The keywords include `blank`, `negative control`, `ntc`, `extraction blank`, `field blank`, `pcr blank`, `mock`, `zymo`, `control` and `kitome`. Longer phrases are tried first. Keywords match whole tokens only. The sample ID is split at punctuation, case changes, and letter-digit boundaries, so `FieldBlank02` gives `Field`, `Blank`, `02`, and the site code `PLANTC1` gives `PLANTC`, `1`, which doesn't match `nc`.

Some keywords are too short or generic to act on alone, such as `blk`, `nc`, `ntc`, `control`, `mock` and `neg`. A sample that matches only one of these, with no type column to confirm it, is marked `ambiguous`, and `build` stops before writing the archive. Answer `control` to exclude the sample, or `sample` to keep it, under `controls:` in `answers.yaml`, with `provenance` saying why and `confirmed` holding the person's reply:

```yaml
controls:
  NC1: {value: control, provenance: "NC1 is the PCR negative in the lab sheet", confirmed: "J. Smith"}
```

An answer under `controls:` settles any sample, ambiguous or not, so the same entry keeps a field site named like a control, or excludes a control the classification missed. A sample with no answer is classified as proposed. An answer naming a sample the table doesn't have settles nothing, so the build stops as `CONTROL_ANSWER_UNMATCHED` until the entry is removed or its `sampleID` corrected: a typo such as `SE-22` for `SE.22` would otherwise publish the control's reads. `controls:` is the only way to change the classification: `build` doesn't read a `confirmed/control_roster.tsv`.

`REVIEW.md` lists the roster as waiting while a sample is excluded on a keyword in its ID alone, with no type column behind it, until `controls:` answers that sample.

## Excluding taxa

`build` stops and asks when the joined table has _Homo sapiens_ rows and `filters.exclude_human` is unanswered, since only a person can say whether human DNA belongs in this dataset. It asks this together with any other missing answer. A row is human when its name is `Homo` or starts with `Homo sapiens`, or when its `scientificNameID` or `taxonConceptID` is a WoRMS, GBIF or NCBI ID for _Homo sapiens_ or the genus _Homo_. `Homo erectus` and `Homarus` don't match. `filters.exclude_human: {value: true, provenance: "Homo sapiens reads, also in the negative control", confirmed: "J. Smith: drop them"}` removes those rows. It has the shape of any other answer, and `answers.yaml` refuses a bare `true` or `false`.

`filters.exclude_kingdoms` lists kingdoms, in any case: Animalia, Archaea, Bacteria, Chromista, Fungi, Plantae, Protozoa, Viruses. It applies per marker, and removes a kingdom's rows for a marker only when that marker's target in `markers:` doesn't cover the kingdom. One dataset can have a bacterial and a vertebrate marker, and a dataset-wide exclusion would delete one of them.

A marker's `target` is one or more of these, separated by commas:

| Answer | Kingdoms it covers |
| --- | --- |
| `prokaryotes` | Bacteria, Archaea |
| `bacteria` | Bacteria |
| `archaea` | Archaea |
| `eukaryotes` | Animalia, Plantae, Fungi, Chromista, Protozoa |
| `animals`, `vertebrates` | Animalia |
| `plants` | Plantae |
| `fungi` | Fungi |
| `universal` | All of the above, and Viruses |

```yaml
markers:
  12S: {target: vertebrates, provenance: "methods.pdf p4, MiFish primers", confirmed: "J. Smith: fish only"}
```

`markers.<marker>.exclude_taxa` removes taxa a study's methods removed from one marker's results, such as Metazoa from an 18S survey of protists. It names taxa, in any case, with one `provenance` and `confirmed` for the list. A row is removed when one of the names appears anywhere in its source lineage, including a segment such as `d__Eukaryota` that no register resolves, or in its resolved taxonomy. Each removed row is in `excluded_rows_report.tsv` with `taxon:<name>` as its reason, and `CONTAMINANT_EXCLUDED` counts them per taxon and marker.

```yaml
markers:
  18S:
    target: eukaryotes
    provenance: "paper.pdf, Methods, 1391F/EukBr primers"
    confirmed: ""
    exclude_taxa: {value: [Metazoa, Streptophyta], provenance: "paper.pdf, Methods", confirmed: ""}
```

`build` asks for a target for every marker in the table. A table with no `marker` column has exactly one entry, under any name. In a table where some rows set a marker and others leave it blank, the blank-marker rows take no entry: no marker constant and no `exclude_kingdoms` scoped by a target reaches them, and `MARKER_INCOMPLETE` reports them. The answer doesn't change taxonomy settings. For a prokaryote marker, set `taxonomy: {registers: [worms]}` under that marker yourself, so they apply to its rows only. See [Options](taxonomy.md#options).

## What gets reported

Every row `build` removes goes to `excluded_rows_report.tsv`, with an `exclusion_reason` of `control:<keyword>`, `human`, `kingdom:<kingdom>` or `taxon:<name>`. The roster gives each sample's classification, the evidence tier, and whether it would be `excluded`, `ambiguous` or `kept` before any `controls:` answer, which `build` applies over it.

| Finding | Meaning |
| --- | --- |
| `CONTROL_EXCLUDED` | How many control samples were excluded |
| `HUMAN_EXCLUDED`, `CONTAMINANT_EXCLUDED` | How many rows each of these exclusions removed |
| `HUMAN_PUBLISHED` | How many human rows the archive publishes under `filters.exclude_human: false`, and whether a person confirmed that answer |
| `CONTROL_AMBIGUOUS` | A weak keyword match. `build` stops until `controls:` answers it |
| `CONTROL_TAXON_LEAKAGE` | A taxon from a positive control (a mock community or spike-in) also appears in a real sample. Not removed |
