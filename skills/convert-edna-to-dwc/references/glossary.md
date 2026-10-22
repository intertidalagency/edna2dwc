# Glossary for the researcher

Say the precise term, then the plain words in parentheses, the first time a term comes up for a researcher new to Darwin Core: "`occurrenceID` (the permanent ID of one detection)". After that, the term alone. The last column is what to add when they ask. Why the archive is shaped this way, and what publishing does, is in `references/darwin-core-primer.md`.

| Term | In parentheses | When they ask |
| --- | --- | --- |
| Darwin Core | the shared vocabulary biodiversity databases use for "what was found, where, when" | A standard maintained by TDWG. Each field it defines is a term, such as `eventDate` |
| Darwin Core Archive (DwC-A) | the zip file GBIF and OBIS accept | A core table, extension tables beside it, `meta.xml` describing the tables, and `eml.xml` describing the dataset |
| term | a named field | `decimalLatitude`, `scientificName`. MIxS terms such as `target_gene` describe the sequencing |
| occurrence | one detection: this sequence in this sample | One row of the core table. Metabarcoding publishes presences only, and `references/darwin-core-primer.md` says why |
| event | one collection at one place and time | Every sample from that collection shares its `eventID` |
| marker | the gene region amplified, with its primers | "12S", "COI". The name doesn't say which organisms it targets: "16S" names both a bacterial region and a vertebrate mitochondrial one, so the primers or methods decide |
| feature, ASV, OTU | one distinct DNA sequence the pipeline found | Each has a taxonomic assignment, and several features can share one taxon |
| library | one sample sequenced with one marker | Read totals are per library |
| control | a sample that measures contamination, such as a field or PCR blank | Removed before publication. `excluded_rows_report.tsv` lists every removed row |
| extension | an extra table joined to each occurrence | DNA-derived data records each sequence and how it was produced. eMoF records measurements such as temperature |
| EML (`eml.xml`) | the dataset's title page: title, authors, abstract, license, contacts | GBIF and OBIS build the dataset's page from it |
| `occurrenceID` | the permanent ID of one detection | Built from the dataset ID, sample and feature, so it is the same on every rebuild. It is how the next version of the dataset recognises the same record, which is why the dataset ID must stay fixed |
| WoRMS, AphiaID | the World Register of Marine Species, and its ID for a name | OBIS matches every name to it. GBIF's own taxonomy covers names WoRMS lacks |
| _Biota incertae sedis_ | the name used for a sequence nothing could identify | A real WoRMS entry (AphiaID 12), so the record still has a name OBIS can match |
| answer | something only you can tell the tool | Written in `answers.yaml` with its `provenance` (where it came from) and `confirmed` (your reply, word for word) |
| proposal | the tool's draft for you to check | In `proposed/`. You accept it, or change rows of it, in `confirmed/`. The control roster is the exception: your answers under `controls:` settle it |
| finding | a note of something the tool did or couldn't do | Coded, such as `JOIN_UNMATCHED`. `edna2dwc findings CODE` explains one. A finding needs no reply |
| GBIF | the Global Biodiversity Information Facility, the open database of where species were recorded | Registers the dataset and gives it a DOI, so it can be cited |
| OBIS | the Ocean Biodiversity Information System, its marine counterpart | Matches every name to WoRMS, drops taxa that aren't marine, and flags points on land |
