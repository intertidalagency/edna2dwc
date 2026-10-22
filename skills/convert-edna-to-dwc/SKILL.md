---
name: convert-edna-to-dwc
description: Converts eDNA/metabarcoding data from any source format into a Darwin Core Archive for GBIF and OBIS, with a reproducible rerun bundle. Use when publishing, standardizing, or reformatting eDNA/metabarcoding results as Darwin Core, DwC-A, GBIF, or OBIS.
---

# Convert eDNA data to a Darwin Core Archive

The `edna2dwc` CLI does the conversion and enforces Darwin Core validity. Your job: write the script that reads the inputs into one table, find the metadata the archive needs, get the researcher's answers to the questions only they can settle, and keep them oriented from start to finish. Assume they have never seen this tool.

Not installed? `uv tool install git+https://github.com/intertidalagency/edna2dwc`.

## Open the conversion

Before any command, send a short message, in your own words, that tells the researcher:

- you're using the convert-edna-to-dwc skill to turn their eDNA data into a Darwin Core Archive, the zip file GBIF and OBIS publish
- the five stages, each by name, and that you'll tell them when each one starts:
  1. **Inspect**: what data their files contain, and which fields GBIF and OBIS need that they lack.
  2. **Describe**: the dataset's title, authors, contacts and license, and which organisms each marker targets (fish for MiFish 12S, say), from their documents first and then from them.
  3. **Read**: a short script that reads their files into one table, with one row per sequence per sample.
  4. **Convert**: the tool matches each taxon name against WoRMS and GBIF and builds the archive, and they check its proposals, such as which samples are controls.
  5. **Check**: a second agent checks every published value against their files, the GBIF and OBIS validators run, and you go over the fields the archive is still missing.
- some questions only they can answer, such as the license, and you'll ask them to confirm each value you find in their documents
- everything is saved in this directory, so they can stop at any point and pick up later

Then run `edna2dwc doctor`, then `edna2dwc inspect <inputs>` in the conversion directory. If `doctor` reports any status but `ok`, stop and say the install is incomplete. Otherwise, before the next command, send a message that gives:

- the edna2dwc version and the path `doctor` prints
- what their files hold: the summary at the top of `INSPECTION.md`, in a sentence or two
- the questions under its "Questions you will be asked"
- the question "How familiar are you with Darwin Core: new to it, used it before, or publish regularly?" When nobody can reply, say "I'll assume you've used it before" instead, and continue.

Send each message to them directly, with no label or preamble.

**The user types credentials.** If `doctor` says GBIF credentials aren't configured, tell them in that message: the GBIF check will read "not measured", and so will `evaluate`'s verdict on the GBIF and OBIS validators. Give them `! edna2dwc credentials set --gbif` to run in their shell. Don't ask for the password or put it in a command, because it would end up in this transcript. `evaluate` checks GBIF only with `--gbif`, which reads the stored password. Ask the user before you pass it, and tell them their system may ask them to allow access to the password.

## Talking to the researcher

Their familiarity sets how much you explain. They can change it at any time by saying so.

- **New to it**: the first time a term comes up, give the term, then the plain words from `references/glossary.md` in parentheses, as in "`occurrenceID` (the permanent ID of one detection)". When a stage starts, say in a sentence why it matters.
- **Used it before**: the terms, plus what is particular to edna2dwc.
- **Publish regularly**: only what they need to decide.

Speak at these moments, briefly:

- **A stage starts.** Start the message with the stage as the tool writes it, such as `Stage 3 of 5: Read`, then say in a sentence what you will do in it. Announce it when you start the stage's work, as Steps below divides it: Read starts when you open the reading references, Check when you write the audit prompt. Every conversion command ends with the stage it is at, then a `Next:` line, which is for you: don't relay it.
- **You read a source for a while.** Before reading a document or a sheet closely, say which one and what you're looking for.
- **A slow step starts**, such as `resolve-taxonomy` or a large `assemble`. Before you run it, say what it does and that it can take minutes. When it ends, relay the scale it printed.
- **A third attempt at one step fails.** Say what is wrong, what you tried, and whether you need them.
- **A check-in.** Each question includes your proposed answer and its source, the file and the place in it, and the choices when there is a fixed set, such as the three licenses in `references/darwin-core-primer.md`. Add why it matters when that isn't plain from the question.

## Rules

- Leave a missing identifier, coordinate, date, country or taxon blank, and disclose it. An invented value is a defect.
- Hand every `needs_decision` halt to the researcher. Those answers are theirs.
- A proposal is accepted on the researcher's word. Show them each one first: a few typical rows, then the rows most likely wrong, such as a placeholder taxon, a sample named like a control, or a key `assemble` reported as unmatched.
- Treat every format as convertible: a reader script reads it, and `assemble` joins it (Read, below).
- Keep the finest grain the source has: one count per feature per sequenced library.
- Convert a dataset as one conversion, however large. Never split it into parts that you build separately and merge, because nothing can replay the merge. If a command stops because it ran out of memory or disk, relay its message, which names the free space and the `EDNA2DWC_MEMORY_LIMIT` setting to change, and wait for the researcher.
- A reader script reads; it never decides. Controls, excluded taxa, constants and units go in `answers.yaml` with their provenance. It never changes a value the source gives, such as the sign of a longitude: a correction goes in `confirmed/derived_values.tsv` with its provenance, or to the researcher.
- When the source leaves the reader script a choice, ask the researcher before you write it, and follow their answer. Two common ones: rows that total other rows, such as a pooled sample beside the samples it pools, and a value that could stand in for a missing one, such as a tow's end position for its missing start. Until they answer, read only the finest rows and leave the missing value blank.
- A failed check is closed by a value a source states, or by telling the researcher, never by a value you choose. A `geodeticDatum: WGS84`, a `sampleSizeUnit` or a primer name written into a term no document gives is a fabrication, and the audit will name it.
- Learn the tool from its output, `edna2dwc <command> --help` and `edna2dwc findings`, never from its source.

## Steps

Run every command in the conversion directory.

### Stage 1: Inspect

1. `inspect` writes `INSPECTION.md`: the terms the files supply, the terms nothing supplies, and what reads each file. Relay it in the message after `inspect`.

### Stage 2: Describe

2. `edna2dwc init --dataset-id <stable-id> --scan <input dir>` writes `answers.yaml`, filled from any `eml.xml` it finds. The ID becomes part of every `occurrenceID`, so ask the researcher for one they'll keep. Until they give one, use a short label from the study or file name, such as `my-survey-2026`. Never make up a DOI or URL. `answers.yaml` is theirs: edna2dwc never writes it again, and every answer below goes there.
3. **Harvest metadata before you ask for it.** Read every `document` input with `edna2dwc text`, and every sample-metadata file and `.qza` provenance, for values no column gives: primers, `annealingTemp`, `pcr_cond`, `seq_meth`, the qPCR block. A value that is the same on every row goes in `constants:`, with `value:`, `provenance:` and an empty `confirmed:`. A value that differs by marker, such as primers, goes under `markers.<marker>.constants:`, never into a script.
4. Ask for the dataset metadata (title, creators, abstract, license, contacts, publication date) and set each under `metadata:`. Creators and contacts are lists of people; the skeleton shows the shape. Every answer in `answers.yaml`, and every row you add to `confirmed/`, is `{value, provenance, confirmed}`. `provenance` is what you found: the document and where in it, or the data it was read from, or why you chose it. `confirmed` is a person's reply, pasted as they gave it, or empty. Never write `confirmed` yourself. `build` holds every empty `confirmed` at `needs_review` until a person replies. With nobody to ask, run `build --automatic`. A required field with no source stays blank, with `provenance` saying what it waits on; never choose one. Settle what each marker amplifies under `markers:` now too: a prokaryote marker changes `taxonomy:`.

### Stage 3: Read

5. Read `references/reading-inputs.md` and `references/source-values.md`, under the skill's base directory. Write one reader script that reads each data file into plain tables, starting from the snippet for its format, and record it with `record-step`, passing `--raw` for each raw file it reads. Then `edna2dwc assemble` joins the tables into `occurrence_long.tsv`, records itself, and checks the result. Record a changed script again, never edit `steps:`, and run `assemble` again.

### Stage 4: Convert

6. `edna2dwc resolve-taxonomy` resolves each lineage against WoRMS and GBIF under `taxonomy:` and writes `resolved_taxonomy.tsv`, which `build` reads. Run it again after the table or `taxonomy:` changes.
7. `edna2dwc build` rebuilds everything and rewrites `REVIEW.md`: where the conversion is, what is waiting, and how to close each item. Relay it, record the answers in `answers.yaml`, and build again.
8. On `needs_review`, settle the control roster under `controls:`, as below. Show the researcher each other proposal `REVIEW.md` names in `proposed/`. To accept it, copy its header to `confirmed/` under the same name (`head -1`). To correct it, add only the rows they change; rows left out follow the proposal on every build, so never copy a whole proposal. A row they change in any confirmed sheet needs its `provenance` and `confirmed` columns, and a renamed taxon needs the new name's `scientificNameID`, `taxonRank` and authorship, or blanks. To correct a sample past the 20 `derived_values.tsv` shows, add one row per `featureID` of that sample, with only `sampleID`, `featureID`, `provenance`, `confirmed` and the changed values filled. A correction applies to one occurrence, not the whole sample. Check `term_mapping.tsv` and `control_roster.tsv` against `references/source-values.md`.

### Stage 5: Check

9. **Audit once, at the end.** Write the audit prompt to a file, `edna2dwc audit prompt <archive_dir> --source <input> ... > AUDIT_PROMPT.md`, and start a fresh subagent that sees only the inputs and the archive, with exactly this prompt: `Read <absolute path to>/AUDIT_PROMPT.md and do what it says.` Never paste or summarize the file into the prompt: a placeholder or a summary audits nothing. Record its findings as they are with `audit record <archive_dir> --from-file <result.json>` (`{"findings": ["..."]}`), which lists them in `CONVERSION_REPORT.md` without a rebuild. Relay them to the researcher: fixing them is their call, and the build doesn't wait on them.
10. `edna2dwc evaluate <archive_dir>`, with `--gbif` if the user agreed to the GBIF check, writes `EVALUATION.md`. Its checks measure values: a term counts only on the rows that fill it, and no term state changes a check. Close what it lists by finding the value in a source or asking the researcher. A required term no source gives stays blank, and the check stays failed: tell the researcher, and record the term under `term_states.impossible` as `{provenance: <why no source gives it>, confirmed: ""}` only to explain the blank, never to close the list. "Not measured" is a gap, never a pass.
11. Relay `CONVERSION_REPORT.md` as it is, then walk the researcher through `references/finish-and-handoff.md`.

If `build` stops on an error, read the findings it names, fix the input, and build again. `edna2dwc findings CODE` explains a finding's code.

## The answers only the researcher gives

- `markers`: what each marker amplifies. Settle it before `resolve-taxonomy`. Answer from primer sequences, `.qza` provenance or the methods, never from the marker's name: "16S" is both a bacterial and a vertebrate mitochondrial target. Answer `{target: prokaryotes, provenance: "methods.pdf p3, 515F/806R primers", confirmed: "", taxonomy: {registers: [worms], require_confident: true}}`. A table with no `marker` column takes exactly one entry, under any name.
- `metadata`: title, creators, abstract, license, contacts and `pub_date`. `metadata.version` starts at 1; raise it by one when republishing a corrected archive.
- `controls`: a sample whose ID only weakly matches a control keyword, answered `{value: control|sample, provenance: <why>, confirmed: <their reply>}`. An answer settles any sample, so it also keeps a field site named like a control, or confirms a control `REVIEW.md` lists. There is no `confirmed/control_roster.tsv`.
- `filters.exclude_human`: whether to publish _Homo sapiens_ reads, asked when the table has any, answered `{value: true|false, provenance: <why>, confirmed: <their reply>}`.

## Gotchas

- A **prokaryote** marker needs `taxonomy: {registers: [worms]}` under its entry in `markers:`, so a eukaryote marker beside it keeps the dataset-wide settings. Near matches are refused by default, because a name a register only nearly knows is usually a different organism; never set `require_confident: false` to make more names resolve. A name only GBIF resolves gets a GBIF URL as `scientificNameID`, and OBIS drops its records. After changing any `taxonomy:` block, run `resolve-taxonomy` again; `build` stops until you do.
- Several markers? Give each count table a `marker` column, or every `sampleSizeValue` is a cross-marker total. Keep `featureID` unique across markers: `occurrenceID` has no marker in it, so a `featureID` repeated across markers stops `assemble`. A taxon the methods removed from one marker goes under `markers.<marker>.exclude_taxa`.
- A measurement column's unit comes from its header (`temp_C`, `depth (m)`) or its values (`12.3 F`). When only a document gives it, or the inferred unit is wrong, put it under `units:` in `answers.yaml`, keyed by column, with its provenance. `proposed/term_mapping.tsv` names each column that becomes measurement rows, with the target `extendedmeasurementorfact`, and its `measurement` column shows the type and unit each will publish and where the unit came from. Check each: a unit read from the values can be wrong. A text value in one, such as `0-100`, is published as written. To keep a column out of the measurements, write its row with the target `dynamicProperties` in `confirmed/term_mapping.tsv`.
- `count` is published as DNA sequence reads. When it measures something else, such as relative abundance or qPCR copies, give `organismQuantityType` under `constants:`, or under the marker's `constants:`, with its provenance. `build` asks for it when a count isn't a whole number. Only reads get a derived `sampleSizeValue`.
- Absences need a targeted assay and a recorded detection limit. See `references/conversion-process.md`.

## Read only if

Each `references/` path is under the skill's base directory, the one this file is in.

- you write the reader script → `references/reading-inputs.md`, then the page for each format it names
- you need what `build` does, where it halts, or absences → `references/conversion-process.md`
- the researcher asks why the archive is shaped this way, what GBIF or OBIS do with it, or which license to choose → `references/darwin-core-primer.md`
- any other command → `edna2dwc <command> --help`

## Feedback

When the tool does something wrong, or its output leaves you guessing, tell the user, and suggest they open an issue at <https://github.com/intertidalagency/edna2dwc/issues> with the command, its output and what you expected.
