# Contributing

The code conventions are in [`AGENTS.md`](AGENTS.md). This page covers reporting issues, setup, tests and pull requests.

## Reporting issues

Open an issue at [github.com/intertidalagency/edna2dwc/issues](https://github.com/intertidalagency/edna2dwc/issues). Include the output of `edna2dwc doctor`, the command you ran, and what it printed. Describe your input files rather than attaching them, unless they are already public.

## Setup

```bash
git clone https://github.com/intertidalagency/edna2dwc
cd edna2dwc
uv sync --group dev
```

`edna2dwc` supports Python 3.11 and later. CI tests 3.11 through 3.14 on Linux, and 3.13 on macOS and Windows.

Each dependency in `pyproject.toml` has a floor at the oldest version CI tests and a cap below its next major version. Raise a cap once the tests pass on the new major. `uv.lock` pins development and CI. It isn't part of the distribution.

Reading phyloseq `.rds` objects needs `Rscript` with the `phyloseq` package. Tests that need it skip when it's missing, so a local run without R passes and CI still covers them: one CI job runs in a Bioconductor container and installs `phyloseq` there. To run them locally, install R and then `Rscript -e 'install.packages("BiocManager"); BiocManager::install("phyloseq")'`.

## The loop

```bash
just test      # pytest, with a coverage summary of files that have untested lines
just coverage  # the same, as HTML in htmlcov/
just test-memory  # assemble, build and replay --compare on up to 2M rows under a 512 MiB limit; Linux only, and CI doesn't run it
just lint      # ruff format --check, ruff check, ty check, rumdl check, zizmor
just checks    # lint, then test
just format    # ruff check --fix, ruff format, rumdl check --fix
```

Every recipe runs its tool through `uv run`. `uv sync --group dev` installs `just` (the `rust-just` wheel) and rumdl, so the whole toolchain comes from Python. Without a global `just`, run `uv run just test`.

`just lint` runs `ty` over `edna2dwc/`, `tests/` and `maintenance/`, and it must come back clean. Treat a diagnostic as a claim about the code. Fix it by making the signature true, splitting the registry, or enforcing the invariant where the value is built.

## Tests

`tests/<area>/test_<module>.py` tests `edna2dwc/<area>/<module>.py`. `tests/<area>/test_<module>_cli.py` tests its CLI surface.

A CLI test calls the app in-process through the `run_cli` fixture in `tests/conftest.py`. Assert on the `CommandResult` it returns, or on the `UsageError` or `CommandFailed` it raises. `replay` prints its work as it runs, so its tests read captured stdout.

`tests/test_cli_mentions.py` checks that every command and long flag the skill, `docs/`, `README.md` and the tool's own messages name exists.

`tests/test_no_ground_truth.py` fails if a reference archive or benchmark dataset is reachable from `edna2dwc/` or `skills/`. It fails on any path that contains `downloads`. To check for benchmark names too, set `EDNA2DWC_REFERENCE_ARCHIVES` to the path of a YAML file, kept outside the repo, that lists them under `archives:`. Without the variable, as in CI, it skips the name check.

`tests/test_golden_archives.py` builds each case in `tests/golden/` from its intermediate table, answers and `resolved_taxonomy.tsv`, and compares the result with the case's `dwca.zip`. A difference is either a fix you meant or a regression. To accept a deliberate change, run `uv run python -m tests.make_golden_archives`. Add `--resolve` to ask WoRMS and GBIF again and rewrite each case's `resolved_taxonomy.tsv`.

Tests are hermetic: HTTP clients replay recorded responses. Build new fixtures under `tests/` from synthetic data.

## Adding a format

The tool ships no reader for any format. A reader script, written for each dataset, reads the inputs into plain tables, and `assemble` joins them. Supporting a new format means teaching the agent to write that script:

1. Add a page to `skills/convert-edna-to-dwc/references/formats/`, with a short Python or R snippet that reads the format into the tables `assemble` joins, the `edna2dwc assemble` command that joins them, and the format's quirks. A Python snippet imports only what `edna2dwc doctor` lists.
2. Link the page from `skills/convert-edna-to-dwc/references/reading-inputs.md`.
3. Add a small synthetic fixture under `tests/fixtures/inputs/`, written by `tests/make_input_fixtures.py`, and name it for the page in `FIXTURES` in `tests/test_skill_snippets.py`. That test runs the snippet against the fixture, runs the `assemble` command, and checks the table it writes.
4. If `inspect` doesn't recognize the format, teach `inputs/inspect.py` to name it and summarize it, so the agent knows what it has.

A format needs no change to `assemble` or any packaging step. If yours seems to, open an issue first.

## Pull requests

Branch from `main`, and fix a bug test-first, as [`AGENTS.md`](AGENTS.md) says. Before you open a pull request, `just test` and `just lint` must pass, and `just docs` must leave `docs/findings.md` and `docs/commands.md` unchanged. Add a line under `[Unreleased]` in [`CHANGELOG.md`](CHANGELOG.md) for a change a user would notice, and an entry in [`docs/dev/decisions.md`](docs/dev/decisions.md) for a design choice. Title the pull request with the change itself, in plain English.

By contributing, you agree that your contribution is licensed under the [MIT License](LICENSE) that covers this project.

## CI

CI installs the built wheel with the newest dependencies its bounds allow, as a user would, runs `doctor` and builds the `two_markers` golden archive with it. It runs the tests on the locked dependencies, and once more on the oldest and once on the newest versions `pyproject.toml` allows, runs the linters, and audits the workflows with `zizmor`. [`docs/dev/ci.md`](docs/dev/ci.md) says how to run the audit locally and how actions and images are pinned.

## The shipped skill

`skills/convert-edna-to-dwc/` is the skill users install. `.agents/skills/convert-edna-to-dwc` and `.claude/skills/convert-edna-to-dwc` are committed symlinks to it, so an agent working in this repo loads the version you're editing. Skills for developing this repo go in `.claude/skills/`, which git ignores apart from that link. On Windows, clone with `git clone -c core.symlinks=true` so the links check out as links rather than text files.
