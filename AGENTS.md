# edna2dwc

`edna2dwc` converts eDNA and metabarcoding data into Darwin Core Archives for GBIF and OBIS. The repo contains the Python CLI (`edna2dwc/`) and the agent skill users install (`skills/convert-edna-to-dwc/`).

Use terms as [`docs/dev/vocabulary.md`](docs/dev/vocabulary.md) defines them. Its _Avoid_ lines list words that mean something else here.

|  |  |
| --- | --- |
| [`docs/dev/architecture.md`](docs/dev/architecture.md) | The intermediate table, the packaging steps, the module map |
| [`docs/dev/decisions.md`](docs/dev/decisions.md) | Decisions and their corresponding tradeoffs. Add to this list when necessary |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Setup, tests, CI |
| [`docs/`](docs/README.md) | User reference, one page per area |

## Invariants

**One intermediate table.** Every conversion passes through `occurrence_long.tsv`. Each reader upstream of it handles one input format. The packaging steps downstream of it read only that table. Support a new format with a new reader, and keep the table's schema fixed.

**A pure build.** `build` recomputes the archive every time from `occurrence_long.tsv`, `answers.yaml`, `conversion.yaml`, `confirmed/`, `resolved_taxonomy.tsv` and `audit_record.json`, with `assembly.json` and the files `answers.yaml` and `conversion.yaml` name. It keeps no state between runs and calls no web service: only `resolve-taxonomy` calls a taxonomic register, and only `evaluate --gbif` and `validate --gbif` call GBIF's validator.

**No fabrication.** Leave a missing identifier, coordinate, date, country or taxon blank, and report the blank. This applies even when a filled value would score higher.

**A person owns their files.** `build` stops until `answers.yaml` gives every answer it needs: `markers`, `metadata`, `controls`, `filters.exclude_human` when the table has human reads, and `organismQuantityType` when a count isn't a whole number. It writes each proposal to `proposed/` and applies the rows a person changed in `confirmed/`, where a header-only copy accepts the proposal. Only `controls:` changes which samples are controls. Every answer is `{value, provenance, confirmed}`, and `confirmed` holds only a person's words: an answer with it empty waits for a person. `--automatic` accepts each open proposal and unconfirmed answer and logs it, and never fills in an answer. The tool never writes `answers.yaml` after `init`, or anything in `confirmed/`. Every `build` writes `REVIEW.md` with what a person needs to do next.

**Reproducible archives.** `dwca.zip` holds only the Darwin Core Archive, and is published on its own. Beside it, `reproduce/` holds exactly what a replay can't write again: `conversion.yaml`, `answers.yaml`, the sheets in `confirmed/`, `resolved_taxonomy.tsv`, `audit_record.json` once recorded, every file in `scripts/`, every file `answers.yaml` names, such as the sample metadata, every raw input `record-step --raw` names, and the justfile that runs the replay. A replay runs the `steps:` logged in `conversion.yaml`, then `build`, which write everything else again, so `reproduce/` never holds the intermediate table or a build output. A raw input that is missing, or outside the conversion directory, ends the build. `CONVERSION_REPORT.md` sits beside both.

**The CLI is what an agent sees.** An agent running the skill has the CLI, its output and the skill, never `docs/` or the source. Put what it needs to act in `--help`, in a command's output, such as a finding's message, or in the skill. `docs/` repeats it for people.

**No answer keys.** Don't commit a published reference archive or benchmark dataset under `edna2dwc/` or `skills/`, or name a path to one there, because an agent running the skill could copy it instead of converting the data. `tests/test_no_ground_truth.py` checks this.

## Code

- Name things so the code explains itself, and split a function when its purpose needs explaining. The code has no comments and no docstrings.
- Command docstrings are the exception, because cyclopts renders them as `--help`. Write a one-line summary and an `Args:` section with one line per parameter. Keep each paragraph and each `Args` entry on one line.
- Write a pragma bare: `# noqa: BLE001`.
- Put behavior in the `docs/` page for its area, structure in `docs/dev/architecture.md`, and design choices in `docs/dev/decisions.md`.
- State reasoning in the code's own terms. A milestone name, PR number, section number or defect code means nothing to a later reader.
- Fix a bug test-first: write the test, show it failing, then fix the code.
- CI runs the tests on Windows, where `str(path)`, a `Path` in an f-string and `os.path` all give `\`. Write a path into a message, a file or a comparison with `.as_posix()`, and normalize a `/` string with `posixpath`, never `os.path`. Write text with `newline="\n"` when its bytes or line endings matter. Build an expected path in a test with `Path`, and mark a test that needs a POSIX-only module or call, such as `fcntl`, with `skipif` or `pytest.importorskip` and the reason.
- Test `edna2dwc/<area>/<module>.py` in `tests/<area>/test_<module>.py`, and its CLI surface in `tests/<area>/test_<module>_cli.py`.
- Title a commit, PR or issue with the change itself, in plain English for a reader who hasn't seen the code: "Record every audit finding in the report".

## Verify

```bash
just test
just lint
```

Windows runs only in CI. After pushing, wait for `gh pr checks --watch`, and read a failure with `gh run view <id> --log-failed`. Work isn't done until Windows passes.

Tests are hermetic: HTTP clients replay recorded responses. Report a result with the output of `just test`.
