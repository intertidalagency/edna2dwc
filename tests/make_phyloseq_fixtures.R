#!/usr/bin/env Rscript
# Generates tests/fixtures/inputs/sample_phyloseq.rds. A committed fixture;
# this script, not any test, regenerates it when the fixture needs to change. Needs R + phyloseq
# installed to run (not needed to read the resulting .rds files).

suppressMessages(library(phyloseq))

# Run from the repo root: Rscript tests/make_phyloseq_fixtures.R
out_dir <- "tests/fixtures/inputs"
dir.create(out_dir, showWarnings = FALSE, recursive = TRUE)

# f3 and S3 are all-zero, so they are pruned before psmelt.
# Among the survivors, f2/S2 is a genuine zero cell (not an all-zero row or
# column): present after pruning, dropped only by the post-psmelt
# presence-only filter.
otu <- matrix(
  c(
    10, 0, 0,   # f1: S1=10, S2=0,  S3=0
    5,  3, 0,   # f2: S1=5,  S2=3,  S3=0
    0,  0, 0    # f3: all zero, pruned
  ),
  nrow = 3, byrow = TRUE,
  dimnames = list(c("f1", "f2", "f3"), c("S1", "S2", "S3"))
)
otu_tab <- otu_table(otu, taxa_are_rows = TRUE)

# Non-standard rank column names, which vary by builder.
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

# A sample_data column with an embedded tab: quote=FALSE with no sanitizer
# would corrupt it, and quote=TRUE round-trips it intact.
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

cat("Wrote sample_phyloseq.rds to", out_dir, "\n")
