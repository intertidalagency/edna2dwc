# Vocabulary

Each term below has one meaning. The _Avoid_ lines name words that mean something else in this domain, or nothing. A full name and its short form are both fine.

## The domain

**eDNA**: environmental DNA, genetic material recovered from a sample of water, sediment or air rather than from an organism. This tool publishes what was detected in such a sample.

**Metabarcoding**: amplifying and sequencing one marker region across everything in a sample at once, which gives many taxa per sample. This is the default here. Contrast **targeted assay**.

**Targeted assay**: qPCR or ddPCR against one organism, with a validated limit of detection. Only here is a non-detection real evidence of absence. _Avoid_: qPCR as a name for the category, because it names one method.

**Marker**: the amplified region, together with the primer pair that amplifies it. A dataset often has several. A marker's name doesn't determine what it amplifies: "16S" is both a universal bacterial target and a vertebrate mitochondrial one. _Avoid_: amplicon, locus, gene and primer set, when the marker is what is meant.

**Feature**: one ASV or OTU, a distinct sequence the pipeline resolved, identified by `featureID`. The row axis of the input table. _Avoid_: taxon, because a feature has a taxonomic assignment and is not one. Also sequence variant, and OTU on its own.

**Event**: one physical sampling event, a collection at one place and time, identified by `eventID`. Every sample taken from it shares that `eventID`. _Avoid_: site and station, which name a place that many events share.

**Sample**: what was sequenced, identified by `sampleID`: a physical collection, or a PCR replicate, dilution or technical replicate of one sequenced on its own. Two replicates are two samples of one event, never one sample with their counts added together. The column axis of the input table. _Avoid_: replicate as a synonym, because a replicate is one kind of sample.

**Library**: one sample amplified with one marker and sequenced, a `(sampleID, marker)` pair. Read totals, and so `sampleSizeValue`, are per library. A sample sequenced with three markers gives three libraries.

**Control**: a sample that measures contamination rather than biology: a field blank, an extraction blank, a PCR negative, a positive control or a mock community. Controls are removed before publication. _Avoid_: blank, which names one kind of control. Also negative and non-sample.

**Occurrence**: one detection: this feature in this sample at this place and time. The unit of publication, and one row of the archive's core file.

**Darwin Core Archive**: the published zip of a core file, its extensions, a `meta.xml` describing them and an `eml.xml` describing the dataset. Write it **DwC-A**, not "DwCA" or "darwin core zip".

**Term**: a Darwin Core or MIxS field name, such as `scientificNameID` or `env_broad_scale`. Write the exact term string, not a paraphrase.

**Extension**: a non-core file in the archive, joined to the core by identifier. This tool writes two: **DNADerivedData** for the sequence and sequencing metadata, and **eMoF** (`extendedmeasurementorfact`) for measurements.

**WoRMS**: the World Register of Marine Species, the marine taxonomic authority. An **AphiaID** is its identifier for a taxon. The **LSID** is that identifier in the URN form the archive uses.

**No-assignment sentinel**: a source string that says a feature got no taxonomic assignment, such as `NA`, `unassigned`, `no hit` or `incertae sedis`. The closed vocabulary is in `edna2dwc/taxonomy/unassigned.py`. A cell that contains one reads as empty wherever a taxon name is expected. An empty cell is not a sentinel, because it says nothing. _Avoid_: null and missing, which name the empty cell.

**Placeholder taxon**: the name published when a feature got no assignment: `Biota incertae sedis` (WoRMS AphiaID 12) or its parent `Biota`. It is a real register entry with a resolvable `scientificNameID`, so it belongs in a row's `scientificName` and `kingdom` and is not an invented value. Always write the term in full, because **placeholder** alone means an invented filler value. _Avoid_: unassigned taxon, which names the feature's state, not the name the archive publishes.

**GBIF backbone**: GBIF's taxonomy, consulted for names WoRMS doesn't have. Its identifiers go in `taxonConceptID`, and in `scientificNameID` for a name WoRMS doesn't confirm.

## This tool

**The intermediate table**: `occurrence_long.tsv`, the one long table every conversion passes through, with one row per `(sampleID, featureID)` pair. _Avoid_: the contract, and occurrence_long as a bare noun in prose.

**Reader script**: the script a conversion writes to read each input's format into plain tables, which `assemble` joins into the intermediate table. It uses only the packages `doctor` lists. `record-step` copies it into `scripts/` and logs the command that ran it, and `replay` runs it again. The tool ships no readers of its own. _Avoid_: ad hoc script, bespoke reader and ingest script. Also parser, which names one part of what it does.

**Darwin Core packaging step**: one of the fixed steps `build` runs to turn the intermediate table into a Darwin Core Archive. The steps run in a fixed order and never see the input format. None is a command of its own. Short form: **packaging step**. _Avoid_: the pipeline, which can mean the packaging steps or the whole conversion. Pipeline means only the bioinformatics pipeline that produced the inputs.

**Conversion**: all the work that takes one dataset from raw inputs to a validated archive, recorded in `conversion.yaml` and `answers.yaml`. _Avoid_: run and job. Also build, which names one invocation of `edna2dwc build`.

**Answer**: something the tool can't determine from its inputs at any effort, which a person writes in `answers.yaml`. `build` stops with the status `needs_decision` until each one it needs is given. The invariants in [`AGENTS.md`](../../AGENTS.md) list them. _Avoid_: decision, question and prompt.

**Proposal**: a table the tool has already produced, which `build` writes to `proposed/` from scratch every time for a person to review. There are four, each named for what it holds: `control_roster`, `term_mapping`, `taxa` and `derived_values`. A proposal with something to review and no confirmed sheet is **open**, and `build` ends at `needs_review`. `--automatic` accepts it. _Avoid_: checkpoint.

**The three pages**: `INSPECTION.md`, which `inspect` writes about the raw files. `REVIEW.md`, which `build` writes every time, listing everything waiting on a person. `EVALUATION.md`, which `evaluate` writes beside a finished archive's `dwca.zip`. Each has an HTML copy of the same name. _Avoid_: report, which names `CONVERSION_REPORT.md`, the disclosure document the archive ships. Also dashboard and summary.

**Confirmed sheet**: the rows of a proposal a person changed, in `confirmed/` under the proposal's name and header, applied over the fresh proposal by key and disclosed in the report. The header alone accepts the proposal. The control roster has no confirmed sheet: answers under `controls:` settle it. A changed row of any confirmed sheet holds its provenance and the person's reply in its `provenance` and `confirmed` columns. _Avoid_: reviewed sheet, override, correction and approval.

**Finding**: one coded statement, from a closed vocabulary, of what a step did or couldn't do. A finding is a disclosure. A reader can act on it, and nobody answers it. _Avoid_: warning, error, issue and message.

**eDNA list**: the 60 terms the bundled term table rates for an eDNA archive, in its `priority_tier` field, as `required`, `strongly_recommended` or `recommended`. `validate --priority-terms` and `evaluate` check the required and strongly recommended ones, and `build` gives all 60 a term state. A term's `tier` is separate, and says what GBIF requires.

**Term state**: the recorded status of a term for this dataset: exactly one of **Filled**, **Ask**, **Impossible** or **Not-applicable**, each with a pointer to its evidence. A `Not-applicable` state has a reason. A term with no state is a separate failure that the report names. _Avoid_: present, absent and missing as the name of a state. `absent` already means something else here.

**Mapping**: the source-column to term assignment, reviewable as `term_mapping.tsv` before it is applied.

**The mapped occurrence table**: the occurrence table after `build` applies the mapping, so its columns are terms, not source columns. Always write it in full, since the intermediate table is also an occurrence table. _Avoid_: occurrence table as a bare noun for it. Also mapped.tsv as a bare noun in prose, which names only the working file `build` writes it to.

**Dataset metadata**: the `metadata:` section of `answers.yaml`, held in code as a `Manifest`. Every field is an **answer**: `{value, provenance, confirmed}`, where `provenance` says what the value rests on and `confirmed` holds a person's reply or nothing, and the loader refuses a field without provenance. An answer with `confirmed` empty is **unconfirmed** and holds the build. _Avoid_: provenance tag, and agent choice for an unconfirmed answer. Also manifest in prose, though the code keeps the name for the class and its module, `dwca/manifest.py`.

**Reproduce bundle**: the `reproduce/` directory beside `dwca.zip` in the archive directory, with `conversion.yaml`, `answers.yaml`, the taxonomy lock, the confirmed sheets, the audit record once one is recorded, and the vendored scripts and raw inputs needed to rebuild the archive. **Replay** is rebuilding from it.

**Taxonomy lock**: `resolved_taxonomy.tsv`, which `resolve-taxonomy` writes from the registers and `build` reads without calling one. Short form: **the lock**.

**Documentation input**: a file that describes a dataset rather than containing its records, such as a methods write-up, a README, a protocol or a sequencing report. `inspect` reports it as `document`. It is read for dataset metadata, never for occurrences, so no reader script reads it. _Avoid_: unrecognized format, which names a data file `inspect` can't identify. Also input on its own, when the file holds no data.

**Human review**: every point where the tool gives work to a person: the answers, the four proposals, `REVIEW.md`, the fabrication audit and the report. Its module is `edna2dwc/review/`. _Avoid_: oversight, which also means an omission.

**Credentials**: the one GBIF account that `evaluate --gbif` and `validate --gbif` use, found in the environment, the OS keyring, this tool's credentials file or `~/.netrc`. Every other register this tool consults is unauthenticated, so "credentials" means nothing else here. _Avoid_: API key and token, because GBIF issues neither and the secret is an account password. Also login and config, which name the act and the file, not the secret.

## Relationships

- A **conversion** produces one **DwC-A** and one `conversion.yaml`.
- A **sample** has many **features**, and the pair identifies one **occurrence**.
- A **marker** has one target, given as an **answer**, and that target scopes every taxon exclusion.
- A missing **answer** stops the build, an open **proposal** waits for a **confirmed sheet**, and a **finding** only informs.
- Each **term** has one **term state** per conversion.
- A **control** is a **sample**, which `build` removes before publishing and reports as removed.

## Flagged ambiguities

- **"16S"** names two unrelated markers. In code, documentation or a prompt, say which target you mean.
- **"absent"** means both "not detected" and "established as not present". The archive only asserts the second, and only for a targeted assay with a recorded detection limit.
- **"run"**: a **conversion** is the whole thing, and one invocation of `build` is a **build**. Neither is a run.
- **"blank"** means both a control sample and an empty cell. Prefer **control** for the sample and **empty** for the cell.
- **"placeholder"** means both an invented filler value, which this tool never writes, and the **placeholder taxon**, which it does. Write the taxon term in full every time.
