# Darwin Core for a researcher new to it

Explain from this page when a researcher asks why the archive is shaped the way it is, or what publishing does. Give the source with each claim. The tool enforces the terms and their values, so this page covers only the reasons.

## What the archive is

Darwin Core is a set of standard terms for sharing biodiversity data, such as `eventDate` and `scientificName` ([TDWG](https://dwc.tdwg.org/terms/)). A Darwin Core Archive is a zip of text tables: exactly one core table, extension tables whose rows each belong to one core row, and `meta.xml`, which maps every column to a term ([Darwin Core Text Guide](https://dwc.tdwg.org/text/)). `eml.xml` beside them describes the dataset: its title, people, abstract and license ([DNA-derived data guide, 1.4](https://docs.gbif.org/publishing-dna-derived-data/1.0/en/)).

## How eDNA fits it

The GBIF guide _Publishing DNA-derived data through biodiversity data platforms_ (the DNA guide, [section 2.2](https://docs.gbif.org/publishing-dna-derived-data/1.0/en/#mapping-metabarcoding-edna-and-barcoding-data)) describes the layout this tool follows:

- **One occurrence per sequence per sample.** Each ASV or OTU detected in a sample is one row of the Occurrence core. `eventID` ties the rows of one sampling event together.
- **Reads are the quantity.** `organismQuantity` is the sequence's read count, with `organismQuantityType` "DNA sequence reads", and `sampleSizeValue` is the library's total reads. `build` derives it as the sum of the reads it publishes for that library, after exclusions, so it is smaller than the sample's total when the source table was already filtered. The guide advises against rarefying.
- **The DNA-derived data extension** records the sequence (`DNA_sequence`) and how it was produced: `target_gene`, the primers, the SOP, the clustering method and the reference database. These terms come from MIxS, the genomics community's standard.
- **eMoF** (extended measurement or fact) records measurements such as temperature or salinity.

## Why only presences

A sequence in a sample is evidence the organism's DNA was there, and DNA can persist after the organism has gone. For metabarcoding, the DNA guide has publishers give the read counts and leaves users to judge how much they show. A non-detection becomes an absence only for a targeted qPCR or ddPCR assay, and depends on that assay's detection limit ([DNA guide, 2.1.3](https://docs.gbif.org/publishing-dna-derived-data/1.0/en/#category-iii)).

## Why the IDs must stay fixed

`occurrenceID` names the detection, so it must not change between versions of the dataset: it is how the same record is recognised in the next version ([TDWG](https://dwc.tdwg.org/terms/#dwc:occurrenceID); [OBIS manual](https://manual.obis.org/darwin_core.html)). That is why the dataset ID, part of every `occurrenceID`, is asked for once and kept.

## GBIF and OBIS

- **GBIF** takes a dataset from an organisation registered with it, usually published from an IPT (GBIF's publishing software), and gives the dataset a DOI. A new major version gets a new DOI, and a citation names the version ([IPT manual](https://ipt.gbif.org/manual/en/ipt/latest/)).
- **OBIS** takes data from marine data providers through an OBIS node, which can pass it on to GBIF too, so a dataset is published once. OBIS matches every name to WoRMS, drops records of taxa that aren't marine, and flags coordinates that fall on land ([OBIS manual: nodes](https://manual.obis.org/nodes.html), [name matching](https://manual.obis.org/name_matching.html), [quality checks](https://manual.obis.org/common_qc.html)).

## The license

GBIF and OBIS accept three licenses, which `metadata.license` takes by the ID beside each name ([IPT manual](https://ipt.gbif.org/manual/en/ipt/latest/applying-license); [OBIS policy](https://manual.obis.org/policy.html)). OBIS prefers CC0.

| License | Anyone may reuse the data |
| --- | --- |
| [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/), `CC0-1.0` | for any purpose, without asking or giving credit |
| [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), `CC-BY-4.0` | for any purpose, crediting the creators |
| [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/), `CC-BY-NC-4.0` | crediting the creators, and not commercially |

The researcher chooses the license, though their institution or funder often sets it. Offer the three with these meanings, and record what they say.
