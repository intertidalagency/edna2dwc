# What `build` does, and where it halts

`edna2dwc build` reads `answers.yaml`, `occurrence_long.tsv`, `resolved_taxonomy.tsv`, `confirmed/` and `audit_record.json`, and rebuilds the archive from scratch every time. Nothing it writes is a file a person edits.

| Step | Proposal for review |
| --- | --- |
| Classify samples as controls | `proposed/control_roster.tsv` |
| Propose the term mapping | `proposed/term_mapping.tsv` |
| Join `resolved_taxonomy.tsv`, which `resolve-taxonomy` wrote | `proposed/taxa.tsv` |
| Remove controls, and Homo sapiens and kingdoms a marker doesn't target if asked | |
| Apply the mapping and constants | |
| Derive `countryCode`, quantities, `sampleSizeValue`, `footprintWKT`, by term | `proposed/derived_values.tsv` |
| Build `occurrenceID`, record term states | |
| Write, validate and bundle the archive, with `CONVERSION_REPORT.md` | |

A sheet in `confirmed/` with the same name is applied over the proposal, row by row. It holds the proposal's header and only the rows a person changed, so a header alone accepts the proposal. Rows left out follow the proposal on every build, so a fix to the input still reaches them.

**Halts.** Each `build` rewrites `REVIEW.md` and ends with one status:

- `needs_decision`: `answers.yaml` lacks metadata, a marker's target, a `controls` answer, `filters.exclude_human` when the table has human reads, or `organismQuantityType` when a count isn't a whole number, all asked at once. Nothing is built. Give the researcher the question from `REVIEW.md` as it is, set the key it names, and build again.
- `needs_review`: the archive is built, and a proposal with something to review has no sheet in `confirmed/`, or an answer or confirmed row has an empty `confirmed`, or a required metadata field is blank, or a finding only a person can judge waits on `adjudications:`: a validator issue such as OBIS `ON_LAND`, or one that changed or blanked published values, such as `TERM_FORMAT_UNCONVERTIBLE` for dates no rule could convert or `JOIN_METADATA_MISSING` for rows with no sample metadata. Show the proposal to the researcher, who accepts it or corrects rows of it in `confirmed/`, except the control roster, which `controls:` answers settle, or ask them about each unconfirmed answer and paste their reply into its `confirmed`, or ask them to judge the finding: fix the input, or accept the code under `adjudications:` with their reply in `confirmed`. Then build again.
- `error`: read the error `REVIEW.md` lists, fix the input, and build again. `build` exits 1. It exits 2 when it refuses `answers.yaml`, the intermediate table or a confirmed sheet, and 0 at every other status.

`--automatic` uses every unreviewed proposal and every unconfirmed answer as written, and logs each one. `REVIEW.md` lists each proposal and answer it used under "Accepted by --automatic, confirm", and `build` prints them. It never fills in a missing answer, accepts a blank required metadata field or accepts a finding that waits on `adjudications:`, so such a build ends at `needs_review`: relay the finding, never accept it yourself. Use it when there is nobody to ask.

**The register pass.** `resolve-taxonomy` prints its scale and progress on stderr. Relay them. Cost depends on distinct names. If a register stops answering, it fails, the cache keeps every lookup, and running it again continues. `build` doesn't call a register. If `resolved_taxonomy.tsv` is absent or lacks a lineage of the table, `build` stops with `error` and says to run `resolve-taxonomy`.

**Absences.** The archive is presence-only unless the assay is targeted and its detection limit is recorded: `assemble` drops zero counts. For a targeted assay, run `assemble --keep-zeros` and set this in `answers.yaml`, and `build` publishes zero counts as `absent`. `build` stops with `ZERO_COUNTS_KEPT` when a row it would publish has a zero count without it:

```yaml
derive_fields: {emit_absences: true}
term_states: {assay_type: targeted_assay}
constants:
  pcr_primer_lod: {value: <the limit>, provenance: <the document and where in it>, confirmed: ""}
```
