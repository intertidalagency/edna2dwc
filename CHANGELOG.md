# Changelog

Notable changes to `edna2dwc`. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning follows [semantic versioning](https://semver.org/spec/v2.0.0.html).

Semantic versioning here covers the CLI's commands and flags, and the files a person edits: `answers.yaml` and `confirmed/`.

## [Unreleased]

### Fixed

- `resolve-taxonomy` backs off through the source lineage when GBIF matches only a higher rank, instead of publishing GBIF's fallback, often the kingdom.
- A GBIF placeholder species, such as `Mesonia sp012964435` or `Paenibacillus_K guangzhouensis`, never stands for its genus or ties with it as a homonym.
- A GBIF candidate below the rank the source gives the name, or from a kingdom the source rules out, is refused, including GBIF's alternatives to its top match.
- A homonym tie left after the source's phylum and class goes to the candidate that shares another name with the source lineage.

## [0.1.0] - 2026-10-21

Initial release.
