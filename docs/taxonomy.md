# Taxonomy resolution

## What to expect

Your classifier's names, such as `d__Bacteria;p__Cyanobacteria` or `Gadus morhua`, become the accepted names, ranks and identifiers of the World Register of Marine Species (WoRMS), or of the GBIF backbone for a name WoRMS doesn't have. `resolve-taxonomy` does the lookups once and saves them in `resolved_taxonomy.tsv`, so `build` never waits on a register.

- **It is usually the slowest step.** Time depends on the number of distinct names, not records. A rerun asks only for names it hasn't seen.
- **Many records resolve above species.** A name no register knows backs off to its genus, family and so on up, and a feature with no assignment is published as the placeholder taxon `Biota incertae sedis`. Neither is an error: the source lineage stays in `verbatimIdentification`.
- **A near match is refused.** A name a register only fuzzily knows is not published as that taxon: resolution backs off to the rank above it, and `TAXON_FUZZY_REJECTED` counts them. `taxonomy.require_confident: false` keeps near matches instead, marked for review. An unaccepted name or a tie between homonyms is published and marked for review in `proposed/taxa.tsv`. Correct a row in `confirmed/taxa.tsv`.
- **OBIS keeps only names tied to WoRMS.** A name only GBIF resolves is published to GBIF, but OBIS may drop it.

## How it works

Three steps turn a classifier's taxonomy into `scientificName`, `scientificNameID`, `kingdom` through `genus`, `taxonRank` and `taxonomicStatus`. Names are resolved against WoRMS first and the GBIF backbone second, unless `taxonomy.registers` says otherwise.

1. Deriving lineages parses each row's taxonomy into a terminal name and its source ranks, and gives each distinct lineage a `lineage_key`. A row's `ncbi_taxid` and `source_taxon_id` are part of its lineage, so rows that share a name but not their IDs are resolved apart. So is its marker, when the marker has its own `taxonomy:` settings. `resolve-taxonomy` and `build` both do this.
2. `resolve-taxonomy` looks up each distinct lineage and writes `resolved_taxonomy.tsv`, one row per `lineage_key`, with the name the source gave in `source_name` and its source lineage in `source_lineage`, so a row can be read without the hash. Its `settings` column records the settings each lineage was resolved under, and its `findings` column the finding codes resolving it raised, such as `TAXON_FUZZY` or `TAXON_ID_CONTRADICTS_SOURCE`. It records in `conversion.yaml`, under `resolve_taxonomy:`, when it ran, the tool version, and the registers it asked.
3. `build` puts the result back onto the rows by `lineage_key`. `build` copies the resolved table to `proposed/taxa.tsv` for review, and a row of `confirmed/taxa.tsv` with its `provenance` filled replaces the resolved row. Before writing the archive, `build` checks that every published `scientificName` and `scientificNameID` pair is one the join wrote, and stops with `TAXON_NOT_FROM_LOCK` if not, so a taxon changes only through `confirmed/taxa.tsv`. See [Correcting a taxon](#correcting-a-taxon).

`build` doesn't call a register. If `resolved_taxonomy.tsv` is absent, the intermediate table has a lineage it lacks, such as after a taxon ID column is added, or a row's `settings` differ from what `answers.yaml` now gives its lineage, `build` stops and says to run `resolve-taxonomy`. Names already looked up come from the cache.

Resolution works on whole lineages. Hundreds of unrelated features can share a terminal name such as `Unassigned` or `s__`. Joining on the name would give all of them the lineage of the first.

## Parsing

Deriving a lineage, which `resolve-taxonomy` and `build` both do, splits a `taxonomy` string on `;` or `|`, which separate ranks and never mean "or" in a lineage. A segment such as `isolate=MT00778` or `strain=...` is bookkeeping, not a name, and is skipped; a one-letter label is dropped, so `g:Dioithona` reads as `Dioithona`; and a `+` inside a segment is a space, so `Pseudocalanus+moultoni` reads as `Pseudocalanus moultoni`. A token that starts with `d__`, `k__`, `p__`, `c__`, `o__`, `f__`, `g__` or `s__` fills that rank (`d__` and `k__` both mean kingdom). A species token only becomes the terminal name, because the rank columns stop at genus. A token with no prefix becomes the terminal name as it is.

A string with no prefixes at all, such as `Bacteria;Cyanobacteria;Cyanobiia;Synechococcales;Prochlorococcaceae;Cyanobium_PCC-6307` or SILVA and PR2's `Eukaryota;Alveolata;Dinoflagellata;core-syndiniales;MALV-II`, is an unranked lineage. Its last name is the terminal name, and the names above it are kept in order, without their sentinels, for rank backoff. They are part of the `lineage_key`, so two unranked lineages that end in the same name are resolved apart. A row with rank columns beside an unranked string reads its rank columns and ignores the string, because the string has no rank the columns lack. A string with any prefixed or labelled rank is read as above, whatever rank columns the row has.

A labelled lineage, such as `Kingdom: Eukaryota | Phylum: Chlorophyta | Genus: Micromonas | Species: Micromonas pusilla`, is read by its labels. It is labelled when every segment between `|` or `;` separators is a rank word, a colon and a name, in any case. `Domain` and `Superkingdom` fill kingdom, `Division` fills phylum, and the deepest named segment, whatever its label, becomes the terminal name. A blank name, a sentinel, and a name that starts with a rank word and an underscore, such as `order_Orbiniidae`, are read as empty. A string with any unlabelled segment is read the `;` way above.

With no `taxonomy` column, the terminal name comes from the first non-empty of `species`, `scientificName`, the deepest rank column from genus up, and `verbatimIdentification`. Column names match regardless of case, so phyloseq's `Kingdom` and R's `scientificname` work. A bare epithet in `species` is joined to `genus`, so `genus=Acartia` and `species=tonsa` give `Acartia tonsa`.

## No-assignment sentinels

Classifiers say "no assignment" in many ways. These are read as no assignment:

- exact strings such as `*`, `NA`, `none`, `no hit`, `root`, `other`, `others`, `environmental samples` and `incertae sedis`
- `unassigned`, `unclassified`, `uncultured`, `unidentified` or `unknown`, followed by a space or an underscore and anything else
- anything ending in `metagenome` after a space or an underscore

Matching ignores case and surrounding space.

Deriving a lineage reads a sentinel in `scientificName`, `species`, any rank column or any `taxonomy` token as an empty cell. It is never sent to a register.

Each row keeps its source identification in `verbatimIdentification` (OBIS keeps this as `originalScientificName`): its `taxonomy` string, or its source `scientificName`, or, when it names no taxon at all, the sentinel it gave. A source `verbatimIdentification` is never replaced. A sentinel next to a real rank, such as `species=uncultured_marine` with `genus=Flavobacterium`, is an empty cell: the row is identified at its genus.

## Name normalization

Before a lookup, the tool reduces a name to its Latin name: the first word, then its lowercase epithets, with `subsp.`, `ssp.`, `var.` or `f.` before an epithet kept, and `Candidatus` kept before the first word. Parenthesized groups go first, `cf.`, `aff.`, `other` and `others` are dropped, and `sp.` or `spp.` ends the name. What follows the Latin name is dropped when the name has an epithet, or when it is a citation: a comma followed by a year, or an ending year. A comma with no year after it separates the names of a compound, so `Gadus morhua, other Gadidae` is the two names `Gadus morhua` and `Gadidae`, published at the family they share:

- `Pelagibacter ubique HTCC1062` becomes `Pelagibacter ubique`
- `Gadus morhua Linnaeus, 1758`, `Gadus morhua (Linnaeus, 1758)` and `Gadus morhua Linnaeus 1758` become `Gadus morhua`
- `Austrarchaea sp. QLD` becomes `Austrarchaea`
- `Candidatus Pelagibacter ubique HTCC1062` becomes `Candidatus Pelagibacter ubique`

A one-word name followed by anything else is sent whole, so `Bacteroidetes BD2-2` is never trimmed to `Bacteroidetes`. Each part of a compound name is reduced on its own. The source value stays in `verbatimIdentification`.

A name with an underscore is a clade, strain or OTU label, such as `Cyanobium_PCC-6307`, `SAR11_clade_Ia` or `MALV-II_X`, not a taxon name. It is never sent to a register, at any rank, terminal name included, and rank backoff climbs past it. The one exception is a Latin name joined with underscores, a capitalized word then lowercase words, such as `Mytilus_edulis` or `Candidatus_Pelagibacter`, which is sent with spaces.

What normalization doesn't fix:

- An author whose name starts lowercase keeps it: `Genus species van Beneden` becomes `Genus species van`.
- A one-word name followed by an author with no comma or year keeps the author: `Gadidae Rafinesque` is sent whole.

## Resolution order

For each lineage, `resolve-taxonomy` tries these in order:

1. **A register ID in the source.** A WoRMS LSID or AphiaID on the row is fetched and trusted, unless `registers` leaves out WoRMS. A name lookup that matches the source ID or its accepted ID agrees with it. If a name lookup disagrees, the source ID wins, the disagreement is reported as `TAXON_ID_CONTRADICTS_SOURCE`, and the row is up for review in `proposed/taxa.tsv`. A sentinel or rank word beside the ID is not looked up, since it can't contradict one. If WoRMS doesn't answer the name lookup, the source ID is kept unchecked, reported as `TAXON_ID_UNCHECKED`, and up for review the same way, and running `resolve-taxonomy` again checks it.
2. **An empty or sentinel name.** A name that is empty after normalization, such as one with an underscore, or is a sentinel, is never sent to a register. It goes straight to rank backoff. A sentinel in a source rank is skipped. WoRMS can match an empty query to a real genus. A bare rank word, such as `Genus`, `species` or `Order:`, is treated the same way, wherever it appears: as the name, a part of a compound name, a source rank or a name in an unranked lineage. Beside a `source_taxon_id`, it isn't sent to check the ID. The lineage reports `TAXON_RANK_WORD_REFUSED`, because a rank word in a name means a label was read as a taxon. GBIF has an insect genus named _Genus_, which would otherwise take every such lineage.
3. **Compound names.** A name with ` or `, `/` or `|` is split. `Genus a or b` gives `Genus a` and `Genus b`. A one-word lowercase part takes the genus before it, and a capitalized one-word part, such as `Gadidae`, stays whole. Each part is resolved against the registers in order, and the result is their deepest shared rank. A part whose lineage leaves a rank blank, such as a family with no genus, disagrees at that rank. If any part doesn't resolve, no rank is shared, and `review_reason` names the part as `compound_name_part_unresolved:<part>`. A compound name skips rank backoff: with no resolved part or no shared rank, it gets the placeholder taxon, with `resolution_path` `compound_common_ancestor`.
4. **The terminal name, then rank backoff** through genus, family, order, class, phylum and kingdom. At each rank, the registers are tried in the order `taxonomy.registers` gives, WoRMS then GBIF by default, before moving up. A GBIF genus beats a WoRMS family. An unranked lineage backs off through its names from the deepest up, and the register's match supplies the rank. A name with an underscore at any rank, such as `SAR11_clade` or `order_Orbiniidae`, is a clade label or a placeholder, not a taxon, and is skipped, as is a rank word. A rejected match moves the backoff up a rank, the same as no match.
5. **The placeholder taxon.** `Biota incertae sedis` (AphiaID 12). With `terminal_fallback: biota`, a lineage with a real terminal name that resolves nowhere gets `Biota` (AphiaID 1) instead. An empty or sentinel name always ends at `Biota incertae sedis`.

An `ncbi_taxid` on the row becomes `taxonConceptID` as `NCBI:txid<number>`, replacing a GBIF species URL. Leading zeros and a trailing `.0` from a float column are dropped. `0`, `1` (the root) and `131567` (cellular organisms) name no taxon, so they aren't published. They and a malformed value are reported as `NCBI_TAXID_MALFORMED`, which says what `taxonConceptID` the row keeps. A `source_taxon_id` of `0` is not looked up.

`scientificNameID` is a WoRMS LSID whenever WoRMS confirms the name. For a name GBIF resolved, the tool looks up the canonical name in WoRMS, unless `registers` leaves it out, and uses the LSID only when the WoRMS kingdom matches GBIF's. Otherwise `scientificNameID` is the GBIF species URL, `https://www.gbif.org/species/<key>`, a resolvable identifier for that name, so the `scientificName` and `scientificNameID` pair the archive requires is complete. `authority` is `gbif` either way. The GBIF key also goes in `taxonConceptID` as a GBIF species URL.

OBIS keeps only records it can tie to WoRMS. A record whose name only GBIF resolves has a GBIF URL, not a WoRMS LSID, as `scientificNameID`, and OBIS drops it as `NO_MATCH` unless its own name match finds it in WoRMS. GBIF publishes it either way. The source lineage stays in `verbatimIdentification`. Resolved against WoRMS alone, a 16S record whose GTDB or SILVA name WoRMS lacks falls back to kingdom `Bacteria`, which keeps it visible in OBIS. GBIF might resolve it deeper, and OBIS would then drop it.

After every lineage resolves, `resolve-taxonomy` looks for mass collapse: five or more lineages with different terminal names that resolved to one taxon whose name is not their terminal name or any other name in their source lineage. Each such lineage gets `needs_review=true` and `TAXON_MASS_COLLAPSE`. Rank backoff lands on a name in the lineage, and the placeholder taxon is exempt, so neither counts.

`resolved_taxonomy.tsv` records how each lineage resolved in `resolution_path`:

| `resolution_path` | Meaning |
| --- | --- |
| `leaf` | The terminal name resolved |
| `rank_backoff` | A higher rank of the source lineage resolved. `authority` says which register |
| `gbif_fallback` | GBIF resolved the terminal name after WoRMS couldn't. `worms_fallback` is the same with `registers: [gbif, worms]` |
| `compound_common_ancestor` | The deepest rank shared by the parts of a compound name, or the placeholder taxon when they share none |
| `homonym_disambiguated` | A homonym tie broken by the source's phylum or class |
| `incertae_sedis_placeholder` | The source named no taxon, and no rank of its lineage resolved |
| `biota_fallback` | Nothing in the lineage resolved |

## Confident matches

A WoRMS match is confident when its type is `exact`, `exact_subgenus` or `exact_replaced`, and the returned name equals the name asked for. The comparison ignores case and a parenthesized subgenus, and reads `_` as a space. A GBIF match is confident when it is `EXACT` and its `canonicalName` agrees.

WoRMS answers `exact` for `Bacteroidetes BD2-2` with the phylum `Bacteroidetes`. The names differ, so that match is not confident.

A single plausible match that is confident and accepted wins. Any other single plausible match is still published, with `needs_review=true` and a `review_reason` such as `non_confident_match_type:fuzzy` or `unaccepted_status:<status>`.

`require_confident`, on by default, refuses non-confident WoRMS matches and fuzzy GBIF matches, so resolution backs off a rank. A GBIF match at a rank above the query is still accepted, and flagged `gbif_higher_rank_match`. A near match is usually a different organism: SILVA's `Porticoccus` fuzzy-matches the genus _Ponticoccus_, `Blfdi19` matches _Polyangium_, and a bacterial label matched the wasp family Vespidae. `require_confident: false` keeps such matches, marked for review. A candidate whose name is a rank word, such as the WoRMS entry named `Genus`, is never a match under either setting.

## Homonyms

When two or more candidates are exact and accepted, the source's `phylum` and then `class` narrow them. A step that would remove every candidate is skipped. If one candidate is left, it wins as `homonym_disambiguated`. If more are left, the first is published with `needs_review=true`, every tied ID goes in `candidate_ids`, and the reason is `homonym_source_mismatch` (the source ranks matched none) or `ambiguous_homonym`.

## Kingdom checks

Resolution checks each candidate against the source lineage's kingdom. An unranked lineage whose first name is in the table below, such as `Bacteria` or `Eukaryota`, is checked against that name. Kingdoms are grouped:

| Group | Kingdoms or domains |
| --- | --- |
| `prokaryote` | Bacteria, Archaea, Monera, Prokaryota, Prokarya, Eubacteria, Archaebacteria |
| `eukaryote_multicellular` | Animalia, Metazoa, Plantae, Viridiplantae, Fungi |
| `eukaryote_protist` | Protozoa, Chromista, Protista, Chromalveolata, Rhizaria, Excavata, Harosa, Hacrobia, Alveolata, Stramenopiles, SAR, Amoebozoa |
| `virus` | Viruses, Virus, Viroids |
| `eukaryote_any` | Eukaryota, Eukarya. Compatible with every eukaryote group |

A non-confident candidate is rejected as `TAXON_REJECTED_KINGDOM` when both kingdoms are in known groups and the groups differ. A confident candidate is rejected only when the domains differ: a prokaryote, a eukaryote of any group, or a virus. Registers disagree about eukaryote kingdoms, putting brown algae in Plantae or Chromista, so a confident `Chromista` match for a `Plantae` lineage stands. A different domain is rejected even for an exact name: the 16S lineage `Bacteria;…;Opitutaceae;Diplosphaera` matches the green alga _Diplosphaera_ exactly, and backs off to `Opitutaceae` instead.

Many reference databases put `Eukaryota` in the kingdom column. That maps to `eukaryote_any`, which can't catch a cross-kingdom match. For those lineages, resolution applies the `require_confident` rule automatically and reports `SOURCE_KINGDOM_UNINFORMATIVE`.

A source lineage whose genus, family, order or class is `chloroplast`, `mitochondria`, `mitochondrion`, `plastid` or `apicoplast` rejects any candidate from another kingdom, confident or not. A `Chloroplast` row backs off to `Cyanobacteria` or `Bacteria`, not to a land plant.

## Options

`resolve-taxonomy` reads these from the `taxonomy:` block of `answers.yaml`. A marker's own `taxonomy:` block, under `markers.<marker>`, overrides any of them for that marker's rows. Each row of `resolved_taxonomy.tsv` records the settings it was resolved under, and `build` stops until `resolve-taxonomy` runs again after a change.

| `answers.yaml` key | Default | Effect |
| --- | --- | --- |
| `taxonomy.registers` | `[worms, gbif]` | The registers to try at each name, in order. `[worms]` never asks GBIF, so OBIS keeps every record. `[gbif]` never asks WoRMS, so `scientificNameID` is the GBIF species URL and OBIS drops the records |
| `taxonomy.marine_only` | `false` | Match marine WoRMS taxa only. Off by default, because freshwater and terrestrial taxa are routine in eDNA |
| `taxonomy.require_confident` | `true` | Refuse non-confident WoRMS matches and fuzzy GBIF matches; `false` keeps them, marked for review |
| `taxonomy.terminal_fallback` | `incertae-sedis` | `biota` publishes `Biota` for a real name that resolves nowhere |
| `taxonomy.refresh_labels` | `false` | After resolving, fetch each AphiaID's current name and ranks live. Skips rows with a `provenance` |

Two flags apply to one `resolve-taxonomy` only. `--refresh` ignores the cache. `-o trial.tsv` writes the result there instead of to `resolved_taxonomy.tsv`, and leaves the `conversion.yaml` record alone, so a setting can be compared before it replaces what `build` reads.

A prokaryote marker beside a eukaryote one gets its own settings:

```yaml
markers:
  16S:
    target: prokaryotes
    provenance: "methods.pdf p3, 515F/806R primers"
    confirmed: ""
    taxonomy: {registers: [worms]}
  COI:
    target: animals
    provenance: "methods.pdf p3, Leray primers"
    confirmed: ""
```

`filters.exclude_kingdoms` removes rows after the join. See [Excluding taxa](controls-and-exclusions.md#excluding-taxa).

## Cache and outages

Register answers are cached in the user cache directory (`edna2dwc/taxonomy`), so a second `resolve-taxonomy` over the same names is fast. That includes a WoRMS lookup by `source_taxon_id`, but not the label refresh, which always asks WoRMS. A run that finds every name in the cache says so: its verdicts are what the registers last said, not a fresh check. `--refresh` looks up every name live, and neither reads nor updates the cache. A cache file that won't parse, such as one cut off by a crash, is read as empty, and every save replaces the file whole.

A request that times out, can't connect, or gets a 408, 429 or 5xx is tried 7 times in all, waiting 2, 4, 8, 16, 32 and then 64 seconds between attempts, each of which can take up to 20 seconds. On a 429 or 503 with a `Retry-After` header, the wait is what the register asks for, up to two minutes. Any other 4xx fails at once. A WoRMS batch that still fails is retried one name at a time.

If eight WoRMS batches in a row fail with no answered batch between them, a WoRMS name that failed on its own fails again when its lineage is resolved, or a GBIF request fails, resolution stops with a one-line message, which counts how the failed WoRMS batches failed, such as `5 HTTP 429 Too Many Requests, 3 ReadTimeout`, and writes no `resolved_taxonomy.tsv`. It first waits for the batches already in flight, and every answer received so far is in the cache, so rerunning `edna2dwc resolve-taxonomy` resumes and asks only for the names still missing. Under `--refresh` nothing was cached, so a rerun with `--refresh` starts again from the first name.

A failed label refresh is treated the other way. It runs after every lineage has resolved, and only fetches the current name and ranks of each AphiaID, so the resolved table still ships, with `TAXON_LABEL_REFRESH_INCOMPLETE`, rather than discarding a finished pass.

## What the archive shows

The join writes into `identificationRemarks` why a row got the placeholder taxon, why a row needs review, in a sentence such as "WoRMS gives this name the status unaccepted", and the tied candidates' IDs. `resolved_taxonomy.tsv` keeps `review_reason` as codes, which the join turns into those sentences. `taxonID` identifies the sequence, not the taxon: `build` sets it to `ASV:` plus the MD5 of the sequence, and leaves it blank, with `TAXON_ID_BLANK`, when there is no sequence. Each kind of rejection, fuzzy match or tiebreak is also counted in one dataset-level finding, such as `TAXON_FUZZY`, `TAXON_REJECTED_KINGDOM` or `SOURCE_KINGDOM_UNINFORMATIVE`. `resolve-taxonomy` prints them, and every `build` reads them from the lock's `findings` column into `findings.json`, the report, and the `taxa` item of `REVIEW.md`.

## Correcting a taxon

`proposed/taxa.tsv` is the resolved table, written on every build for review. To change a row, copy the proposal's header to `confirmed/taxa.tsv` and add only the rows you change.

A row of `confirmed/taxa.tsv` that differs from `resolved_taxonomy.tsv` in a column the join publishes, from `scientificName` to `genus` and `resolution_path`, needs its `provenance` column, saying what the change rests on, such as `the genus was misidentified, per the lab's voucher list`. It then replaces the resolved row, reported as `TAXON_OVERRIDDEN`. A changed row with nothing in `provenance` refuses the sheet, and the build names the row. A changed row with `confirmed` empty holds the build for review until a person's reply is pasted there. `resolved_taxonomy.tsv` has the same two columns. A row that changes `scientificName` must give the new name's `scientificNameID` and `scientificNameAuthorship`, or leave them blank, and keeps `taxonRank` only when the new name has as many words as the old one. A row that keeps what belongs to the old name stops the build with `TAXON_OVERRIDE_INCONSISTENT`, so no species is published beside its genus's LSID.
