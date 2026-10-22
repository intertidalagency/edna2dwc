# edna2dwc

`edna2dwc` turns eDNA and metabarcoding results into a Darwin Core Archive (DwC-A) to publish on [GBIF](https://www.gbif.org) and [OBIS](https://obis.org). It reads Excel workbooks, QIIME 2 artifacts, BIOM tables, phyloseq objects, CSVs and other formats.

It is for a scientist who has a spreadsheet of results and a methods write-up, and wants to publish them. You answer questions about your dataset in one file, `answers.yaml`. An AI coding agent, such as Claude Code or Codex, writes the script that reads your files and runs the commands. Every command also runs by hand.

What it is designed to do:

- **Report gaps instead of filling them.** The tool leaves a missing identifier, coordinate, date, country or taxon blank and reports it, even when a filled value would look better. The skill tells the agent never to invent a value, but neither can stop an agent or a person from writing a wrong one, so read `CONVERSION_REPORT.md` before you publish.
- **Ask a person before applying a guess.** The tool proposes which samples are controls, the term mapping, the taxonomy and some derived values, and you confirm or correct each. Each answer says what it rests on, and holds the conversion until a person's reply is pasted into its `confirmed`. `build --automatic` accepts the open proposals and unconfirmed answers instead, and logs each one.
- **Keep what a rebuild needs.** Beside the archive, `reproduce/` holds the script, your answers and the raw inputs, and `edna2dwc replay` rebuilds the archive from them. A rebuild can differ when a package version or `edna2dwc` itself has changed, and `replay --check` reports the difference.

## How a conversion goes

```bash
edna2dwc inspect data/                       # what the files contain, in INSPECTION.md
edna2dwc init --dataset-id my-survey-2026    # writes answers.yaml for you to fill in
python read_inputs.py                        # a reader script, usually written by the agent
edna2dwc resolve-taxonomy                    # looks up every name in WoRMS and GBIF
edna2dwc build                               # repeat until REVIEW.md says the conversion finished
edna2dwc evaluate archive/                   # checks the archive and writes EVALUATION.md
```

Between the reader script and `resolve-taxonomy`, `record-step` records the script and `assemble` joins the tables it wrote into one. [The quickstart](docs/quickstart.md) walks through every step.

What comes out:

```text
REVIEW.md                  what is waiting on you
archive/
  dwca.zip                 the Darwin Core Archive
  occurrence.txt, ...      the files dwca.zip holds, unzipped
  CONVERSION_REPORT.md     what the conversion did and couldn't do; pass it on with the archive
  EVALUATION.md            what evaluate found
  reproduce/               what replay needs to rebuild dwca.zip
```

## Install

You need [`uv`](https://docs.astral.sh/uv/getting-started/installation/). To read phyloseq `.rds` files you also need [R](https://cran.r-project.org/) with the `phyloseq` package, and `Rscript` on your PATH.

### With an agent

Give your agent this prompt:

```text
I want to convert a folder of eDNA data into a Darwin Core Archive using https://github.com/intertidalagency/edna2dwc. Install the `edna2dwc` CLI and its `convert-edna-to-dwc` skill, then walk me through converting the files in <my data folder>.
```

### By hand

Install the CLI, and check the install:

```bash
uv tool install git+https://github.com/intertidalagency/edna2dwc
edna2dwc doctor
```

For Claude Code, copy the skill into `~/.claude/skills/` (every project) or `.claude/skills/` (one project):

```bash
git clone https://github.com/intertidalagency/edna2dwc
cp -r edna2dwc/skills/convert-edna-to-dwc ~/.claude/skills/convert-edna-to-dwc
```

For an agent with no skill mechanism, paste [`skills/convert-edna-to-dwc/SKILL.md`](skills/convert-edna-to-dwc/SKILL.md) into its prompt or project instructions.

A GBIF account is optional, and needed only for the GBIF check in `evaluate --gbif`. [`docs/credentials.md`](docs/credentials.md) says how to store one.

## What leaves your machine

`edna2dwc` sends your data off your machine only in these commands:

- `resolve-taxonomy` sends each distinct taxon name, and any taxon ID your table gives, to WoRMS and the GBIF backbone.
- `evaluate --gbif` and `validate --gbif` upload the whole `dwca.zip` to GBIF's validator, signed in with your GBIF account.
- `credentials set --gbif` checks the account with GBIF before it stores it.
- `replay` installs the package versions `conversion.yaml` recorded, which can mean downloading them.

`build` doesn't call a web service. The AI agent you run is separate: unless its model runs on your machine, it sends what it reads to the model's provider.

## Documentation

[`docs/`](docs/README.md) is the user guide, starting with [the quickstart](docs/quickstart.md). To work on the tool itself, read [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Status

Alpha. The commands, `answers.yaml` and the files in `confirmed/` may change shape before 1.0. [`CHANGELOG.md`](CHANGELOG.md) says when a conversion has to start again from `init`.

## License

MIT. See [`LICENSE`](LICENSE). The term lists, country boundaries and schemas the tool bundles keep their own terms, listed in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

## Citing

A citation for `edna2dwc` will be added here.

## Acknowledgements

Built by Intertidal Agency with The Data Patch and DrivenData, with a grant from Schmidt Marine Technology Partners.

The tool relies on the [World Register of Marine Species](https://www.marinespecies.org/), [GBIF](https://www.gbif.org)'s backbone taxonomy and validator, [OBIS](https://obis.org)'s quality checks, [Natural Earth](https://www.naturalearthdata.com/)'s country boundaries, and [TDWG](https://www.tdwg.org/)'s Darwin Core.

## Feedback

Report a bug or ask a question in [GitHub issues](https://github.com/intertidalagency/edna2dwc/issues).
