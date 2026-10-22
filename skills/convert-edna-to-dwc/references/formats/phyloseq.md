# Reading a phyloseq object

A phyloseq `.rds` needs R. Export its tables to CSV with an R script, record that script like any reader script, and assemble the CSVs. The step replays only where R and phyloseq are installed, so tell the researcher.

```r
suppressMessages(library(phyloseq))
physeq <- readRDS("raw/sample_phyloseq.rds")
dir.create("tables", showWarnings = FALSE)

counts <- as(otu_table(physeq), "matrix")
if (!taxa_are_rows(physeq)) counts <- t(counts)
write.csv(data.frame(featureID = rownames(counts), counts, check.names = FALSE),
          "tables/counts.csv", row.names = FALSE)

ranks <- as(tax_table(physeq), "matrix")
write.csv(data.frame(featureID = rownames(ranks), ranks, check.names = FALSE),
          "tables/taxonomy.csv", row.names = FALSE)

metadata <- sample_data(physeq, errorIfNULL = FALSE)
if (!is.null(metadata)) {
  samples <- as(metadata, "data.frame")
  write.csv(data.frame(sampleID = rownames(samples), samples, check.names = FALSE),
            "tables/samples.csv", row.names = FALSE)
}

sequences <- refseq(physeq, errorIfNULL = FALSE)
if (!is.null(sequences)) Biostrings::writeXStringSet(sequences, "tables/sequences.fasta")
```

```bash
edna2dwc assemble --counts tables/counts.csv --features tables/taxonomy.csv --samples tables/samples.csv --sequences tables/sequences.fasta
```

- Record it as `Rscript scripts/export_phyloseq.R`.
- Rank columns from `tax_table` are named by whoever built the object. `Kingdom` to `Genus`, in any case, are read as ranks. Rename others, such as `Rank1`, to the rank they hold.
- A sample-metadata column named `sampleID` collides with the key: rename it before writing.
