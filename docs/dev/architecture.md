# Architecture

The reasons behind this structure are in [`decisions.md`](decisions.md).

## Three commands, three pages

A person runs three commands. `inspect` reads the raw files and writes `INSPECTION.md`. `build` turns the intermediate table into an archive, and writes `REVIEW.md` every time it runs. `evaluate` checks a finished archive and writes `EVALUATION.md` beside `dwca.zip`. `pages.py` writes each page as Markdown and as self-contained HTML. A researcher opens the HTML, and an agent reads the Markdown. Every other command does one part of this work.

## Reading and packaging meet at the intermediate table

Every conversion passes through one long occurrence table, `occurrence_long.tsv`. Upstream, a reader script written for the dataset reads its files, whatever their formats, and joins them. Downstream, `resolve-taxonomy` and `build` run the same way for every dataset.

```text
 .xlsx   .qza   .rds   .biom   .csv   ENA export   a lab's LIMS export
   └───────┴──────┴──────┴───────┴──────────┴────────────────┘
                           │ the reader script, recorded with record-step
                ┌──────────▼──────────┐
                │  occurrence_long    │  sampleID, featureID, count,
                │  one row per        │  taxonomy or rank columns,
                │  (sampleID,         │  anything else passed through
                │   featureID)        │
                └──────────▼──────────┘
                           │
          resolve-taxonomy │ ──► resolved_taxonomy.tsv (the lock)
                           │
   ┌───────────────────────▼────────────────────────┐
   │  build: classify samples, propose the mapping, │  answers.yaml
   │  join the locked taxonomy, filter controls,    │◄─ confirmed/
   │  apply the mapping, derive fields, build       │   resolved_taxonomy.tsv
   │  identifiers, record term states, write, check │
   └───────────────────────┬────────────────────────┘
                           │
   proposed/, REVIEW.md, archive directory: dwca.zip, reproduce/, CONVERSION_REPORT.md
```

A new format needs no release, only a reader script. `reproduce/` contains `conversion.yaml` and the files a replay needs and can't write again.

## The intermediate table

The table is tab-separated, with a header, read as `utf-8-sig` so a byte-order mark from Excel doesn't end up in the first column name. Every step that reads it refuses a file whose header uses commas, semicolons or pipes.

| Column | Required | Notes |
| --- | --- | --- |
| `sampleID` | yes | Non-empty, no tabs or newlines |
| `featureID` | yes | ASV or OTU identifier, non-empty |
| `count` | yes | Numeric, zero or more |
| `taxonomy` | this, rank columns, `species` or `scientificName` | Delimited classifier string |
| `kingdom`..`genus` | this or `taxonomy` | One column per rank |
| `marker` | with more than one marker | Groups the `sampleSizeValue` denominator and scopes exclusions |
| `sequence` | no | Hashed into `taxonID`, and published in the DNA extension |
| anything else | no | Passed through |

`validate-intermediate` checks the column rules above and four rules for the whole table:

- `(sampleID, featureID)` is unique.
- No cell contains a tab, carriage return or line feed.
- `taxonomy`, a rank column, `species` or `scientificName` is present.
- No two columns share a name.

New requirements go into passthrough columns, because changing the schema breaks every recorded reader script.

## The files of a conversion

Nothing the tool writes is a file a person edits.

| File | Written by | Read by |
| --- | --- | --- |
| `occurrence_long.tsv` | `assemble`, from the tables a reader script wrote | `resolve-taxonomy`, `build` |
| `answers.yaml` | `init`, once, then only a person | `resolve-taxonomy`, `build` |
| `resolved_taxonomy.tsv` | `resolve-taxonomy` | `build` |
| `proposed/*.tsv` | every `build`, from scratch | a person, who puts the rows they change in `confirmed/` |
| `confirmed/*.tsv` | a person | `build` |
| `conversion.yaml` | `init`, `record-step`, `assemble`, `resolve-taxonomy`, `build` | `replay` |
| `audit_record.json` | `audit record`, which also rewrites `CONVERSION_REPORT.md` from its JSON twin and copies the record into `reproduce/` | `build`, which lists its findings in the report and bundles it for `evaluate` |
| `REVIEW.md`, the archive directory | every `build` | a person, `evaluate` |

`conversion/artifacts.py` names every file of a conversion and of its archive directory, and is the one reader and writer of `conversion.yaml`. `answers.py` is the one reader of `answers.yaml`: it loads it and refuses an unknown key, naming it. `build` refuses a column `answers.yaml` names that the intermediate table or the sample-metadata file lacks. `build` empties the archive directory when it starts, so nothing from an earlier build survives in it, but only when it is empty or holds an earlier build's `reproduce/` (`build/archive_dir.py`). It zips the files `meta.xml` declares, and removes the directory again when the build ends in `error`. `replay --check` reports a zip member `meta.xml` doesn't declare.

## `build` recomputes the archive

`build` (`packaging.build`) keeps no state between runs, and reads and writes only the conversion directory it is given, never the current one. Each build reads `answers.yaml`, `conversion.yaml`, the intermediate table `occurrence_long.tsv`, `resolved_taxonomy.tsv`, `confirmed/`, `audit_record.json`, `assembly.json` and the files `answers.yaml` and `conversion.yaml` name, loads the table into DuckDB, and runs these steps in order:

1. Classify samples as controls, applying `controls:`.
2. Propose the term mapping, and apply `confirmed/term_mapping.tsv` if it exists.
3. Derive each row's lineage, and halt with `error`, naming `resolve-taxonomy`, if `resolved_taxonomy.tsv` is absent, lacks one, or resolved one under settings `answers.yaml` no longer gives it.
4. Join the locked taxonomy, with `confirmed/taxa.tsv` over it. Halt with `needs_decision` if `answers.yaml` lacks an answer the invariants in [`AGENTS.md`](../../AGENTS.md) list. Every missing answer is asked at once, and nothing is built. With an answer missing, a halt from steps 2 and 3 waits behind it.
5. Remove controls and excluded taxa, each exclusion scoped to the markers whose target justifies it.
6. Check the source columns: zero counts, a second sequence column that disagrees with the one mapped to `DNA_sequence`, and the two timestamp columns `answers.yaml` names, which these checks read by their source names.
7. Apply the mapping, the constants and the defaults. From here every step reads terms, beside the intermediate table's `sampleID`, `featureID`, `count` and `marker` and the taxonomy join's `resolution_path`, which the mapping keeps for them.
8. Derive status, quantities, coordinates, country and generalizations, each filling a term only on a row the source left blank. `proposed/derived_values.tsv` holds the first 20 samples, by term. A row of `confirmed/derived_values.tsv`, for any sample, corrects a column the mapped table has before the derivation and a derived value after it, and stops the build when it names a column the proposal lacks.
9. Build `occurrenceID`, `taxonID` and `materialSampleID` where the source gave none, convert every column the derivation added or a person corrected to its term's format, and record each term's state.
10. Write the archive and validate it. The writer keeps each table as written, with its line numbers, and validation checks those tables rather than reading the files back; only the row-shape check reads the files, since it checks the writer.
11. Work out the status, then write `CONVERSION_REPORT.md` with its JSON twin and `reproduce/` beside `dwca.zip`, and `findings.json` and `REVIEW.md` in the conversion directory.

A halt at step 4 still leaves the proposals computed before it in `proposed/`, and `REVIEW.md` lists them under "Waiting on you" beside the questions, so a person can answer and review in one round.

Each step takes a DuckDB view or table and returns another, which adds, replaces or filters columns, together with its findings. `build` collects the findings into `findings.json`, and stops with `error` when a step returns an error. It writes to disk only what a person or a replay reads: `proposed/`, `findings.json`, `term_mapping.tsv`, `term_states.tsv`, `excluded_rows_report.tsv`, `REVIEW.md`, the `environment:` in `conversion.yaml` and the archive directory.

### The table in DuckDB

`table.py` holds the database: a file in a temporary directory, deleted when `build` ends, under a memory limit of half the memory the process can use, or `EDNA2DWC_MEMORY_LIMIT`, past which it spills to the system temporary directory. `connect()` turns running out of memory or spill space into `ResourceLimitError`, which the CLI prints as one line naming the limit, the free space and the settings to change. `assemble`, `validate-intermediate`, `resolve-taxonomy`, `validate`, `evaluate` and `package` open one the same way, so their peak memory follows the limit rather than the row count. The database stores tables in row groups of 16,384 rows rather than DuckDB's 122,880, because DuckDB compresses a row group's long strings outside its limit. The intermediate table is read with every column as text. Each row keeps its input row number in a hidden column, and every file is written ordered by it, so output rows follow input rows and the zip is the same on every run. `write_tsv` numbers the lines by sorting the order keys alone, joins the numbers back, and writes about 16 MB of lines at a time, because DuckDB's sort needs memory that grows with the width of the rows it sorts.

A missing value is NULL: the row has no such key. An empty value is `''`. A step that adds a column leaves it NULL on rows it doesn't set, and a column that is NULL on every row is dropped, so a column exists in the output only when some row set it, as when rows were dicts.

DuckDB ignores case in column names, and a table can hold both `Kingdom` and the `kingdom` the taxonomy join writes. So every column name is encoded on its way into SQL, with a caret before each capital letter, and decoded on its way out. Columns a step uses for its own working start with `^_`, which no encoded name can, and are never written. The term mapping's hidden columns pass the source `dynamicProperties` value and each column bound for `dynamicProperties` or eMoF to the writer, and mark each row whose source value for a term failed conversion, so the derivation treats it as given (`map_terms.source_gave`).

Python runs once per distinct value, never per row. A step selects the distinct values its rule needs, such as a lineage's source ranks, a sample ID, a coordinate pair, a sequence or a mapped column's value, runs the Python rule on each, loads the answers as a lookup table (`table.lookup`), and joins it back. A value that differs on nearly every row gets no Python at all. `dynamicProperties` is one. The term mapping keeps each column bound for it as a hidden column of the mapped table, beside the source's own `dynamicProperties` value (`terms/dynamic_properties.py`). The writer unnests those columns into eMoF entries, parsing JSON only on rows whose source has a value, and then builds the JSON once, by joining `"key":value` strings, from what eMoF didn't take. `package` takes the same path, with its core's `dynamicProperties` as the source value. The unit of a measurement is looked up once per distinct key and unit token. The archive files are written with `COPY`, and `write_tsv` writes the header itself, because `COPY` renames a column whose name differs from another only in case.

`build` writes the four proposals in `proposed/` from scratch every time (`build/sheets.py`). A proposal is open when it has something to review and no confirmed sheet:

| Proposal | Has something to review when |
| --- | --- |
| `control_roster.tsv` | a sample is excluded on a keyword in its ID alone, and `controls:` doesn't answer it |
| `term_mapping.tsv` | a mapping is ambiguous, or a column goes to `dynamicProperties` or eMoF |
| `taxa.tsv` | always |
| `derived_values.tsv` | a coordinate sign looks wrong |

A confirmed sheet is applied over the fresh proposal by key, and rows it leaves out follow the proposal. A confirmed mapping row onto a term the taxonomy join writes stops the build. So does a confirmed row, or a `controls:` answer, whose key the table no longer has, as `CONFIRMED_ROW_UNMATCHED`, `DERIVED_CONFIRMED_UNMATCHED` or `CONTROL_ANSWER_UNMATCHED`, because an answer that settles nothing is a mistake to fix.

After validation, every finding whose code is in `findings.JUDGED_BY_A_PERSON`, the codes that change or blank what the archive publishes, such as `TERM_FORMAT_UNCONVERTIBLE`, `JOIN_METADATA_MISSING` and `TAXON_MASS_COLLAPSE`, raises `ADJUDICATION_NEEDED` naming the `adjudications:` line that accepts its code, or `STRUCTURAL_COST_DISCLOSED` once that line is there. The status is computed last, from every finding. It is `needs_decision` from step 4, `error` when any finding other than `ADJUDICATION_NEEDED` is an error, from a step, validation or the bundle, `needs_review` if a proposal is open, an answer has `confirmed` empty, a required metadata field is blank, or a finding waits on `adjudications:`, and `ok` otherwise. A recorded fabrication audit never changes the status: the report lists its findings. `--automatic` treats every open proposal as accepted and logs each as `PROPOSAL_ACCEPTED`, and uses every unconfirmed answer and logs them as `UNCONFIRMED_ACCEPTED`. It never answers a missing answer, fills a blank or accepts a finding that waits on `adjudications:`. `REVIEW.md` lists what is waiting and how to close each item, lists each proposal and answer `--automatic` used under "Accepted by --automatic, confirm", including the error a build stopped on, and its headline says the conversion finished only when nothing is. Its checklist is the five stages of `conversion/stages.py`: Inspect, Describe, Read, Convert and Check. `build` is at Convert, or at Check once `audit_record.json` exists; the page ticks every stage before it and marks it **Now**. Every conversion command ends its output with the same stage on a line of its own, `Stage 3 of 5: Read`, then `Next: ...`, and `--json` gives them as `stage` and `next`. A build stopped on an error points `Next` at that error. `INSPECTION.md` opens with the five stages and the questions the conversion will ask.

`build` returns one `BuildResult` (`build/result.py`): the status and its detail, every finding, the review items, the stage and the next step. The review items are the one list of what is waiting on a person, accepted by `--automatic`, done or not reached. The status is `needs_review` exactly when an item waits, `REVIEW.md` renders the items, and the report counts what waits from the same facts. A build that halts adds one finding naming the status it halted at, `DECISION_REQUIRED`, `PROPOSAL_OPEN` or `RUN_FAILED`, with the detail as its message, so `findings.json`, the report and `--json` hold the same findings. The command only prints the result.

Which columns go into an extension is decided by one module per extension: `dwca/dna_derived_data.py` for `dnaderiveddata`, and `dwca/emof.py` for `extendedmeasurementorfact`. The writer takes the eMoF columns from its caller and never chooses them: `build` passes the columns the term mapping routes to eMoF, and `package`, which has no mapping, passes the `dynamicProperties` keys `emof.py`'s rule picks and prints them.

## The taxonomy lock

`resolve-taxonomy` (`taxonomy/lock.py`) derives each lineage of the intermediate table and resolves it against WoRMS and GBIF under the `taxonomy:` settings in `answers.yaml`, or its marker's own. It writes `resolved_taxonomy.tsv`, with the settings each lineage was resolved under in its `settings` column and the findings it raised in its `findings` column, and records a `resolve_taxonomy:` block in `conversion.yaml`: when it ran, on which version, and against which registers. `--refresh` bypasses the match cache, and `-o` writes a trial file without replacing the lock. `build` doesn't call a register: it reads the lock through the same module, which refuses one that lacks a lineage or records other settings. The match cache makes a rerun cost only the names it hasn't seen. The command in `cli/taxonomy.py` picks the cache directory and hands `lock.run` a `register_clients` factory, which opens the WoRMS and GBIF clients for each scope's settings. A test hands in a factory whose clients answer from a mock transport.

## Reproducibility

`conversion.yaml` is the recipe: the `steps:` that ran each vendored reader script, the `raw_inputs:`, the `environment:` with each package version and the tool's version and commit, which every `build` rewrites, and the `resolve_taxonomy:` block. `build` is not logged as a step, because a replay always ends with it.

The bundle in `reproduce/` (`reproduce/bundle.py`) holds what a replay needs and can't write again: `conversion.yaml`, `answers.yaml`, `resolved_taxonomy.tsv`, `confirmed/`, `audit_record.json` once an audit is recorded, the files `answers.yaml` names, every file in `scripts/`, the raw inputs, which must be inside the conversion directory, and the justfile. Everything else, the intermediate table and every `build` output, a replay writes again. `bundle.check_recipe` checks each recorded step against what the bundle holds: a path its command names, or a string literal in its script, must be a recorded script, a recorded raw input or under `tables/`, never absolute or above the conversion directory. `record-step` runs the same check on the step it is about to record, and `build` runs it on the whole recipe, where a reader script with no raw input at all, or a raw input under `tables/`, is also an error. `replay` copies the bundle into a scratch directory with an empty `tables/` and no `findings.json`, runs the recorded reader scripts there, then `edna2dwc build --automatic`, and reads the rebuild's status from the finding that build's `findings.json` records it halted on, or from the last line of the output when a step failed before `build` wrote one. `--check` compares the rebuild with the archive that shipped whenever the build wrote an archive, whatever its status, and then prints that status. Either form exits non-zero when the rebuild ends in `error`. The packages are installed at the recorded versions, and `--unpin` runs the steps under the installed ones, through the same `uv run`. The tool itself runs from the replaying install, and `replay` prints its version and commit beside the recorded ones.

## Output

A command returns a `CommandResult` with a JSON form, a text form and an exit code. The root app prints it and exits. Commands that produce a result accept `--json`. Findings use the closed list of codes in `findings.py`, and `edna2dwc findings` explains each one. `replay` also streams the recorded steps' output while it runs.

## Module map

Each package is one area, in conversion order below. Beside them, the package root holds `__init__.py` and two directories of files. `data/` holds the country boundaries and ISO 3166 codes `terms/country_code.py` reads, and the GBIF EML profile's XSDs, which only the tests read and the wheel leaves out. `templates/justfile` is the recipe file `init` copies into the conversion directory and `build` bundles into `reproduce/`, and `templates/answers.yaml` is the commented skeleton `init` fills in and writes as `answers.yaml`. `common/` holds what every area uses, and `cli/` has one module per area of the help page. Only `cli/` and `review/review_page.py`, which reads the build's result, import from `build/`.

| Package | What it holds |
| --- | --- |
| `common/` | The finding codes (`findings.py`), `CommandResult` (`result.py`), progress lines on stderr (`progress.py`), pages as Markdown and HTML (`pages.py`), a short list in a message (`text.py`), the installed version and commit (`version.py`), the DuckDB database a command works in (`table.py`), and reading and writing TSV (`tsv.py`) |
| `conversion/` | The files of a conversion: `answers.py` loads and checks `answers.yaml`, with each settings section a dataclass whose fields are its keys and defaults, and fills in the skeleton `init` starts from, `provenance.py` is the one parser for an answer's `{value, provenance, confirmed}` shape, in `answers.yaml` and in a confirmed sheet's columns, and the one walk that finds the unconfirmed ones, `artifacts.py` names the files of a conversion and of its archive directory, and reads and writes `conversion.yaml`, and `intermediate.py` is the intermediate table's schema and its check |
| `inputs/` | `inspect` (`inspect.py`) and the `INSPECTION.md` it writes (`inspection_page.py`), `assemble` (`assemble.py`), `text` (`document_text.py`), `detect-redundant`, and telling a file's format from its suffix and content (`sniff.py`) |
| `taxonomy/` | `resolve-taxonomy`: lineages, WoRMS and GBIF lookups, their match cache (`match_cache.py`), the lock, the count of register calls, and the no-assignment vocabulary (`unassigned.py`). The only code that calls a taxonomic register |
| `terms/` | The Darwin Core term table and its loader (`term_table.py`), its sync from TDWG and GBIF, value formats, the term mapping (`map_terms.py`) with the terms the taxonomy join writes, the `dynamicProperties` JSON it builds, term states, and the country of a coordinate (`country_code.py`) |
| `build/` | `build`: `packaging.py` runs the steps and works out the status, `result.py` holds the build's result and the one list of what is waiting on a person, `questions.py` asks the missing answers, and `sheets.py` writes the proposals and applies the confirmed sheets. The other modules are the steps it runs: classifying samples, the taxonomy join, controls, exclusions, derived fields, and identifiers |
| `dwca/` | Writes the archive (`writer.py`), `meta.xml`, `eml.xml` and the extensions, and holds the dataset metadata with its provenance. The `package` command calls `writer.py` directly, without the packaging steps |
| `validation/` | `validate` and `evaluate`, the gates both read (`gates.py`), the GBIF and OBIS checks, and the GBIF account (`credentials.py`), the only code that writes a secret to disk |
| `review/` | The fabrication audit, the report, and `review_page.py`, which renders the build's result as `REVIEW.md` |
| `reproduce/` | The steps log, the bundle, `replay`, `compare`, and the recorded environment |
| `cli/` | The commands, one module per area: `setup`, `inputs`, `taxonomy`, `build`, `evaluate`, `review`, `reproduce`, `package` and `terms`. `app.py` is the root app, `groups.py` orders the help page, `help.py` lays it out, `common.py` has the shared types, and `run_log.py` writes the `EDNA2DWC_LOG` log |
