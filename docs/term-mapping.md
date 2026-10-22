# Term mapping

This page covers how the intermediate table's columns become Darwin Core terms, how a value no column gives can be set for every row, and the state the conversion records for each term.

## Proposing the mapping

`build` proposes the mapping as `proposed/term_mapping.tsv` from the intermediate table's header. It lists your source columns only. `sampleID`, `featureID` and `count` are left out, because the identifiers use them. A row of `confirmed/term_mapping.tsv` replaces the proposed row for its column. A taxonomy column `resolve-taxonomy` reads, such as `scientificName` or `kingdom`, is proposed as `internal`, because the join publishes the resolved value in its place. A column the join writes and doesn't read, such as `taxonConceptID`, never reaches the mapping: the table check refuses it. A row mapping a column onto such a term stops the build, even a column of the same name such as `taxonConceptID -> taxonConceptID`: change a taxon in `confirmed/taxa.tsv` instead, or give the source's NCBI taxonomy IDs as an `ncbi_taxid` column and its WoRMS AphiaIDs as `source_taxon_id` in the intermediate table, which `resolve-taxonomy` reads.

A column is matched first to a term with the same name, then to a term whose name matches when case and punctuation are ignored (`decimal_latitude` matches `decimalLatitude`), then to a curated alias, such as `degrees_latitude` or `lat_dd` for `decimalLatitude`. A column that matches nothing goes to `dynamicProperties`. When two columns match one term, the weaker match, or the later column when both match equally, is marked `ambiguous`, reported as `TERM_AMBIGUOUS` and `TERM_TARGET_COLLISION`, and goes to `dynamicProperties` until a row in `confirmed/term_mapping.tsv` names its term. It never becomes eMoF rows, however numeric. The mapping waits for review in `REVIEW.md`, and the archive is still built.

`term_mapping.tsv` has the columns `source_column`, `target`, `basis`, `provenance`, `confirmed` and `measurement`. `basis` is how the tool matched the column, such as `exact`, `alias` or `ambiguous`. `provenance` and `confirmed` are empty in the proposal. Each row of `confirmed/term_mapping.tsv` that changes the proposal's target needs its `provenance`, saying what the change rests on, such as `methods.pdf p2, site_lat holds longitudes`. A changed row without one refuses the sheet, and the build stops naming the row. A row copied unchanged from the proposal needs neither column. `measurement` only informs: on a row proposed as eMoF rows it shows the `measurementType` and `measurementUnit` `build` will publish, and where each unit comes from, as `measurementType=temperature; measurementUnit=degrees Celsius (from the header)`. A confirmed sheet may leave the column out. A changed row with `confirmed` empty is applied, and holds the build at `needs_review` until a person's reply is pasted there.

- To drop a column, give it a row in `confirmed/term_mapping.tsv` with a blank `target` and `basis` `internal`.
- A column proposed as eMoF rows has the target `extendedmeasurementorfact` and the basis `measurement`. A row with the target `dynamicProperties` keeps it in `dynamicProperties`, and a row with the target `extendedmeasurementorfact` makes any column eMoF rows.
- A column `build` adds after the proposal, such as `scientificName` or `occurrenceID`, maps to the term it names, or is left out when internal. Any other such column goes to `dynamicProperties` and reports `MAPPING_ROW_MISSING`.
- Each constant is added to the applied mapping as a row with `(constant)` as `source_column`, or `(constant <marker>)` for a marker's constant, `constant` as `basis` and its `provenance`.

## Measurements and units

A column at least 95% of whose values are a number, alone or followed by a unit the unit table lists, or whose header is a known measurement name, becomes an eMoF row. A column the intermediate table reserves, such as `marker` or `sequence`, never does unless a confirmed row sends it there, so a marker named `16S` stays a marker. A header is a known measurement name when the whole header is one, or when what remains after a unit the unit table lists is one: `temp_C` publishes `temperature`, while `temp_station` and `pCO2_corrected` publish their own names as `measurementType`. A value that isn't a number, such as the range `0-100` or `>0.8`, is published as written: GBIF and OBIS accept any text in `measurementValue`. A value of `NA`, `N/A`, `NaN` or `null` is no value, so it publishes no row and doesn't count against the 95%. `measurementUnit` is a unit the source states, in the header (`depth (fathoms)`, `temp_C`) or on the value (`12.3 F`), that the curated unit table lists. A one-letter unit on a value counts only in its symbol's case (`m`, `s`, `h`, `L`, `l`, `C`, `F`), so `16S` is a gene and `5M` isn't five meters. A value that states a unit other than its header's, such as `54 F` in `temperature_C`, is published as written and stops the build with `MEASUREMENT_UNITS_MIXED`. A value followed by any other token, such as `16S` or `12 knots`, counts as text, so a `gene` column of `16S` and `18S` isn't proposed as measurements. A unit a document gives, or a correction to the one the header or values name, goes under `units:` in `answers.yaml`, keyed by source column, with its provenance:

```yaml
units:
  conductivity: {value: mS/cm, provenance: "methods.pdf p3", confirmed: ""}
```

The entry names a unit the unit table lists by its name, such as `degrees Celsius`, or a spelling, such as `degC`, in any case, and gets its `measurementUnitID`. The entry wins over the header and the values. A value with a unit the table lists, such as `12.3 F`, then publishes its number alone under the entry's unit, and a value followed by any other token is published as written. `build` reports each entry that replaces a unit the header or values name as `MEASUREMENT_UNIT_OVERRIDDEN`, and stops with `MEASUREMENT_UNITS_MIXED` when the column's values state more than one unit, such as `12 C` and `54 F`, because one entry can't be right for both; and the `measurement` column of `proposed/term_mapping.tsv` shows the unit as from `units:`. A column with no unit from any of these gets a blank `measurementUnit` and `TERM_PAIR_INCOMPLETE`. `measurementTypeID` and `measurementUnitID` come only from the curated tables.

## Constants

A term no column fills and no step derives, such as a sampling protocol stated only in the methods, can be set on every row as a constant. A constant fills blanks only: one that would replace a value the data gives, such as a derived `sampleSizeValue`, stops the build. Add it to the `constants:` block of `answers.yaml`:

```yaml
constants:
  samplingProtocol: {value: "1 L filtered through 0.45 um", provenance: "methods.pdf p3", confirmed: ""}
```

A value that differs by marker, such as a primer, a target gene or a sequencing method, goes under that marker's entry in `markers:` and reaches only the rows with that `marker`:

```yaml
markers:
  16S:
    target: prokaryotes
    provenance: "methods.pdf p4, 515F-Y/926R primers amplify prokaryote 16S"
    confirmed: ""
    constants:
      pcr_primer_forward: {value: GTGYCAGCMGCCGCGGTAA, provenance: "methods.pdf p4", confirmed: ""}
```

A table with no `marker` column has one entry in `markers:`, and its constants reach every row. A `dynamicProperties` constant fills the rows where the table gives no `dynamicProperties` value, like any constant, and the columns the mapping sends to `dynamicProperties` are added to it, so their measurements still become eMoF rows. A term may be under `constants:` or a marker, not both. A term the taxonomy join writes, such as `scientificName`, `kingdom` or `phylum`, can't be a constant, because it would fill rows no register resolved: change a taxon in `confirmed/taxa.tsv` instead. Nor can a term that identifies one record, event, sample or sequence: `occurrenceID`, `eventID`, `materialSampleID`, `taxonID` and `organismID`. One `eventID` on every row says every sample came from one event; put the column that distinguishes events in the intermediate table under that name, or leave the term blank.

An entry with no `provenance:` fails when `answers.yaml` loads. A constant joins the applied mapping, as above, but isn't in `proposed/term_mapping.tsv`, so review constants in `answers.yaml`.

## Term states

`build` gives every priority eDNA term one state in `term_states.tsv`, with a pointer to its evidence.

| State | Meaning |
| --- | --- |
| Filled | At least one row of the mapped occurrence table has a value. Evidence: `term_mapping.tsv:<column>`, `constant:<provenance>`, `default:<value>` or `mapped occurrence table` |
| Not-applicable | The term doesn't apply to this study design, with a reason |
| Impossible | The term applies, but no source has it, with a reason. It explains a blank to the researcher and passes no gate: `evaluate` still lists the term with the share of rows it fills |
| Ask | A person has to supply the value. A mapped column that is blank on every row makes its term Ask |

`occurrenceID`, `basisOfRecord` and `scientificName` can't be recorded Not-applicable or Impossible.

Under the default `metabarcoding` design, the qPCR terms (`probeReporter`, `probeQuencher`, `ampliconSize`, `thresholdQuantificationCycle`, `baselineValue`, `pcr_primer_lod`, `pcr_primer_loq`) are Not-applicable automatically. Every other unclassified term becomes Ask, with evidence such as `no <term> column in the mapped occurrence table`.

The `term_states:` block of `answers.yaml` sets a state directly, and Impossible wins over Ask. Each reason is `{provenance, confirmed}`, with no value, and one with `confirmed` empty holds the build for review:

```yaml
term_states:
  assay_type: targeted_assay
  not_applicable:
    otu_db: {provenance: "methods.pdf, no OTU clustering in a targeted assay", confirmed: "J. Smith: right"}
  ask:
    pcr_primer_lod: {provenance: "the assay validation report has it", confirmed: ""}
  impossible:
    annealingTemp: {provenance: "the methods give primers but no PCR profile", confirmed: ""}
```
