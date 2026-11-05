# Decisions

Each entry records a decision, the alternatives considered, and the tradeoffs. An entry belongs here when reversing the choice would change the architecture or the published output. Current behavior goes in the docs page for its area. Choices about how the repository is developed, such as CI pinning and type checking, are in [`CONTRIBUTING.md`](../../CONTRIBUTING.md) and [`ci.md`](ci.md).

## A GBIF higher-rank match backs off through the source lineage

**Decision.** When GBIF answers `HIGHERRANK` for a name, the next register is asked for it, then resolution backs off through the source lineage, skipping each rank GBIF also answers `HIGHERRANK` for, and takes the deepest rank that resolves. GBIF's higher-rank taxon is published, flagged `gbif_higher_rank_match`, only when no rank resolves or the one that does sits above it in GBIF's classification, as when GBIF parsed a binomial to its genus and the lineage resolves only to the phylum. A higher-rank taxon below the rank the source gives the name is refused outright, so the class `Saprospirae` backs off to its phylum rather than taking the genus _Saprospira_.

**Alternatives.**

- Accept GBIF's higher-rank taxon for the name, as before. Rejected because GBIF's fallback is often the kingdom: in the Earth Microbiome Project's Greengenes 13_8 lineages, `Deltaproteobacteria` resolved to _Bacteria_ though `Proteobacteria`, the phylum above it, is an exact accepted match, and 1,360 of 2,767 lineages lost two or more ranks this way.
- Treat every `HIGHERRANK` answer as a refusal. Rejected because GBIF answers `HIGHERRANK` with the queried taxon itself when the backbone holds placeholder species under it, as for `Prevotella` and `Corynebacterium`, and refusing that answer dropped 226 EMP lineages to the family. A `HIGHERRANK` answer whose name is the name asked for counts as confident.
- Compare ranks by name, such as phylum above class. Rejected because WoRMS and GBIF name ranks differently and include ranks between the six columns, while GBIF's classification of its own taxon says directly whether the lineage's match sits above it.

## A homonym tie is narrowed by rank, and a GBIF placeholder species is no homonym

**Decision.** A GBIF candidate whose `scientificName` is a placeholder species, `<Genus> sp<digits>` or `<Genus> sp. sp<digits>`, is compared by that full name, not by its `canonicalName`, which GBIF gives as the bare genus. Among tied exact candidates, those at the rank the source gives the name win first, before the source's phylum and class narrow them.

**Alternatives.**

- Compare every GBIF candidate by `canonicalName`, as before. Rejected because each GTDB placeholder species in the backbone then tied with its genus: in the Earth Microbiome Project run, 597 lineages were flagged `ambiguous_homonym` at genus, such as _Mesonia_ against `Mesonia sp012964435`.
- Recognize only the `sp<digits>` placeholder forms. Rejected because GTDB names such as `Paenibacillus_K guangzhouensis`, with canonical name `Paenibacillus` or `Paenibacillus spec.`, still matched the genus, and 112 lineages published a genus name with a species' rank and ID. A GBIF candidate below the rank the source gives the name, or at species rank for a one-word name, is refused as well. WoRMS candidates are exempt, because WoRMS names a species by its binomial.
- Narrow a homonym tie only by the source's phylum and class. Rejected because a lineage can place a name at another rank, such as Chlorophyta as an order, so `Carteria` tied the fungus, the alga and the ammonite. Candidates whose classification holds any other name in the source lineage now win when phylum and class leave a tie.
- Check only GBIF's top match for kingdom and organelle plausibility. Rejected because the alternatives then reached the tie-break unchecked, and a bacterial `Marina` was published as the plant genus _Marina_ Liebm. without a review flag. Each alternative now passes the same checks, and a refused alternative that names the query is reported like a refused top match.
- Drop every candidate at a rank other than the queried one. Rejected because a lineage that names no rank for the name, such as a binomial leaf, has none to compare, and a source rank that matches no candidate would remove them all. Narrowing by rank is skipped in both cases.
