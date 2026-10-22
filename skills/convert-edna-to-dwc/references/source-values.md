# What a source value means

eDNA files reuse words and numbers that mean something else elsewhere. Read each column as a metabarcoding lab wrote it, check the tool's reading of it in `proposed/`, and ask the researcher where these rules don't settle it.

## Grain: one row per feature per library

A **library** is one sample amplified with one marker and sequenced. Keep the finest grain the source has: one count per feature (ASV, OTU or zOTU) per library.

- Read the feature table (ASV by sample) and its sequences, and use a taxon-summed table only when the source has nothing finer. Summing by taxon loses the sequences, `DNA_sequence` and every feature the classifier couldn't name.
- A PCR replicate, a dilution (`d1`, `d5`, `d10`) or a technical replicate sequenced on its own is its own sample. Give each its own `sampleID`, and keep the field sample it came from in an `eventID` column. A sample sequenced with several markers keeps one `sampleID`, and the `marker` column tells its libraries apart. Never add their counts together.
- Two sequencing runs of one marker, such as columns `12S_run1` and `12S_run2`, are one marker: each run of a sample is its own sample, and the `marker` column holds the marker's name, `12S`.
- A column suffix you can't decode, such as `_d5`, is a question for the researcher, asked before you write the reader.

## Markers are gene names

`16S`, `18S`, `12S`, `28S`, `COI`, `ITS`, `rbcL` and `MiFish` name a gene or a primer set. The S is the Svedberg unit of the ribosome subunit, never seconds. A column of them goes in `marker`, and `marker` never becomes measurement rows.

## Identifiers are not measurements

A column of numbers that names something, such as `PopID`, `sample`, `transect`, `replicate`, `bottle` or `station`, is an identifier. When `proposed/term_mapping.tsv` sends one to `extendedmeasurementorfact`, write its row in `confirmed/term_mapping.tsv` with the target `dynamicProperties`, or a Darwin Core term it matches, such as `locality` for a station name.

## Units

Read the `measurement` column of `proposed/term_mapping.tsv` for every measurement row, and correct any type or unit that is wrong; `units:` corrects a unit. Two traps:

- A one-letter unit counts only in its symbol's case: `5 m` is metres, `5M` is text.
- A suffix that is not a unit is part of the name: `temp_station` and `temp_depth` are two measurements, and `pH_corrected` and `pH_uncorrected` are two more.

## Taxonomy

Copy the source's taxonomy as it is. Write its rank columns (`kingdom` to `species`) when it has them, and a `taxonomy` lineage string only when that is all it has. Keep rank prefixes such as `k__` and `d__` as the source writes them. A source taxon ID goes in its own column: an NCBI taxid in `ncbi_taxid`, a WoRMS AphiaID in `source_taxon_id`. Never write `taxonConceptID`, `scientificNameID` or `taxonRank`: `resolve-taxonomy` writes them, and `assemble` refuses them.

## Coordinates

A column's header can be wrong. Check that each site's latitude and longitude put it where the methods say it is, before you map them. When the source swaps them, map each column to the term its values fit in `confirmed/term_mapping.tsv`, with the evidence in `provenance` and `confirmed` empty. `countryCode` and `footprintWKT` follow that mapping.

## Controls

Labs name controls in many ways: `pcrblank`, `PCRneg`, `EB_` (extraction blank), `FB` (field blank), `NTC`, `CB_` (cooler or collection blank) and `ArtComm` or `mock` (a mock community of known organisms). `proposed/control_roster.tsv` shows what the tool matched. Read every sample ID against the methods, and put each control the roster misses under `controls:`, with its provenance.
