# Reproducibility

Every `build` writes `reproduce/` beside `dwca.zip`. From it, `replay` reruns the conversion's reader scripts and `build`, and can compare the result with the archive that shipped. `dwca.zip` is published on its own. Share `reproduce/` too to let someone rebuild it.

## The reproduce bundle

`reproduce/` holds exactly what a replay can't write again: `conversion.yaml`, `answers.yaml`, every `.tsv` sheet in `confirmed/`, `resolved_taxonomy.tsv` (the taxonomy lock, because `build` asks no register), every file at the top level of `scripts/`, whether or not the steps log records it with its SHA-256, every file `answers.yaml` names by path, such as `filters.sample_metadata`, every raw input `record-step --raw` listed in `conversion.yaml`, `audit_record.json` once an audit is recorded, and the `justfile` whose recipes run the replay. A replay's steps and `build` write everything else again, so it leaves out the intermediate table, `proposed/`, the tables a reader script writes, and the build's outputs: `excluded_rows_report.tsv`, `term_mapping.tsv`, `term_states.tsv` and `findings.json`. `evaluate` reads `term_mapping.tsv`, `term_states.tsv`, `excluded_rows_report.tsv` and the intermediate table in the conversion directory whose `answers.yaml` names the archive as its `out_dir`, wherever it runs. The term table and the country boundaries are not bundled: `build` reads the ones the installed tool ships. A file in `scripts/` that no step runs is reported as `BUNDLE_SCRIPT_NOT_RUN`: delete it unless a reader script imports it.

`build` copies each raw input however large, at the path the recorded command uses. A raw input must be inside the conversion directory, named in the recorded command by a path relative to it. `record-step` refuses a `--raw` file outside it, and warns about a command path that is absolute, starts with `~`, or climbs out with `..`. A raw input that is missing or outside the conversion directory ends the build in `error`, with a message naming the file and where it belongs.

## The steps log

The `steps:` list in `conversion.yaml` holds the reader scripts that wrote the intermediate table, each recorded with `record-step` as the command that ran it, the script's path in `scripts/` and its SHA-256, followed by `assemble`, which records itself. `replay` runs them under the recorded Python and package versions, then `edna2dwc build --automatic`. `build` itself is not logged, because it is the same every time and reads everything else from `answers.yaml` and `confirmed/`.

`record-step` puts a new script after the other scripts and before `assemble`. Recording a script already in the log again replaces its step in place, with the new copy and hash, so a changed script is recorded the same way as a new one. `record-step` refuses `--position` then. A step that produces an input for a step already in the log needs `--position N` (1-based), or `replay` runs the consumer first. `record-step` copies the script to `scripts/` and refuses a command that doesn't run that copy, as `python scripts/read_lims.py` does, because a replay runs from the bundle and has only the copy. It also refuses an empty command.

A replay has only what the bundle holds: the recorded scripts, the raw inputs `--raw` named, and an empty `tables/`. So `record-step` and `build` check the recipe against that, and refuse a step that reads anything else: a command or a script that names an absolute path, a path above the conversion directory, or a file inside it that no `--raw` names. `build` also stops when a reader script is recorded with no raw input at all, or a raw input is under `tables/`, which the scripts write. Each refusal names the step, the script and the path, and says to copy the input inside the conversion directory, read it by a relative path and name it in `--raw`.

## Replaying

```bash
edna2dwc replay --check .
```

Run this from the conversion directory. It replays `archive/reproduce/`, the bundle beside the archive `answers.yaml` names as its `out_dir`, and prints that path: it copies only the bundle to a scratch directory, runs the recorded steps and then `build --automatic` there, and compares the result with `archive/dwca.zip`. Nothing else in the conversion directory reaches the replay, so a pass means `reproduce/` alone rebuilds the archive. A directory with no such bundle beside its archive is replayed as it is. The rebuild uses the bundled `resolved_taxonomy.tsv` and never asks a register.

It compares whenever the build wrote an archive, even one still waiting on review, and then prints the build's status, read from the rebuild's `findings.json`, on its own line. A difference, or a build that ends in `error`, exits non-zero. A plain `replay` prints the rebuild's status the same way. Both succeed when the build ends `ok` or `needs_review`, and fail when it ends in `error` or writes no archive.

From an archive directory, run `edna2dwc replay --check reproduce`, which compares with the `dwca.zip` beside it. Where `reproduce/` is kept apart from `dwca.zip`, add `--against` and the zip's path. Inside `reproduce/`, `just check` does the same. `--check` writes `comparison_summary.md` and `comparison_summary.json` beside the `dwca.zip` it compares with, never into `reproduce/`, and `--output` puts them elsewhere.

A comparison pairs each table's rows by the id column `meta.xml` declares. Rows of one id that are identical on both sides pair first, and the rest pair in file order. In `comparison_summary.json`, `rows_only_in_old` and `rows_only_in_new` count the rows with no partner, and `only_in_old` and `only_in_new` name the first ten ids that hold one, though such an id may still have other rows on both sides. `value_diff_counts` counts the paired rows whose value in each column differs, and `row_order_matches` is false when the paired rows come in a different order.

The replay installs the package versions recorded in `conversion.yaml`, which needs network access. Offline, or when those versions can't be installed, add `--unpin` to run the steps under the installed versions instead, still through `uv run`, so `python` is on the path either way. `edna2dwc` itself always runs from your install. `replay` prints its version and commit beside the ones `conversion.yaml` recorded, and a commit ending in `-dirty` was built from a checkout with uncommitted changes.

`replay --dry-run .` prints the command sequence instead, for a methods appendix. `replay --compare OLD NEW` compares two archive zips without replaying.
