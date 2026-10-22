#!/usr/bin/env Rscript
# installed to run (not needed to read the resulting .rds files).

suppressMessages(library(phyloseq))

# Run from the repo root: Rscript tests/make_phyloseq_fixtures.R
dir.create(out_dir, showWarnings = FALSE, recursive = TRUE)

# Among the survivors, f2/S2 is a genuine zero cell (not an all-zero row or
otu <- matrix(
  c(
    10, 0, 0,   # f1: S1=10, S2=0,  S3=0
    5,  3, 0,   # f2: S1=5,  S2=3,  S3=0
  ),
  nrow = 3, byrow = TRUE,
  dimnames = list(c("f1", "f2", "f3"), c("S1", "S2", "S3"))
)
otu_tab <- otu_table(otu, taxa_are_rows = TRUE)

tax <- matrix(
  c(
    "Bacteria", "Cyanobacteria",
    "Bacteria", "Firmicutes",
    "Bacteria", "Proteobacteria"
  ),
  nrow = 3, byrow = TRUE,
  dimnames = list(c("f1", "f2", "f3"), c("Domain", "Phylum"))
)
tax_tab <- tax_table(tax)

sample_df <- data.frame(
  depth_m = c(12.5, 8.0, 3.0),
  notes = c("collected\tat dawn", "routine", "control"),
  row.names = c("S1", "S2", "S3")
)
sample_dat <- sample_data(sample_df)

refseq_obj <- Biostrings::DNAStringSet(c(
  f1 = "ACGTACGTACGTACGT",
  f2 = "TTGGCCAATTGGCCAA",
  f3 = "AAAACCCCGGGGTTTT"
))

physeq <- phyloseq(otu_tab, tax_tab, sample_dat, refseq_obj)
saveRDS(physeq, file.path(out_dir, "sample_phyloseq.rds"))

