# edna2dwc documentation

## Start here

| | |
| --- | --- |
| [Quickstart](quickstart.md) | One conversion from start to finish |
| [A worked example](example.md) | A tiny workbook converted, with what each command printed |
| [Concepts](concepts.md) | The words these pages use |
| [Troubleshooting](troubleshooting.md) | Common problems, and the tool's known limitations |

## Reference

| | |
| --- | --- |
| [Commands](commands.md) | What each command does, the files of a conversion, and how to review a proposal |
| [Reading inputs](reading-inputs.md) | The intermediate table, and the reader script that writes it |
| [Archive contents](archive-contents.md) | What the archive directory holds, and how the archive is checked |
| [Dataset metadata](metadata.md) | Provenance and confirmation, and what `eml.xml` holds |
| [Finding codes](findings.md) | Every finding code, its severity and its meaning |
| [Credentials](credentials.md) | The GBIF account the validators use |

## How it decides

| | |
| --- | --- |
| [Controls and exclusions](controls-and-exclusions.md) | Which samples are controls, and which taxa are removed |
| [Taxonomy](taxonomy.md) | How names are resolved against WoRMS and GBIF |
| [Term mapping](term-mapping.md) | How columns become Darwin Core terms, constants, units and term states |
| [Derived fields](derived-fields.md) | The values `build` works out, such as `countryCode`, and absences |
| [The fabrication audit](fabrication-audit.md) | The independent check that every value came from an input |

## Advanced

| | |
| --- | --- |
| [Reproducibility](reproducibility.md) | The `reproduce/` bundle, the steps log and `replay` |

To work on the tool itself, see [`CONTRIBUTING.md`](../CONTRIBUTING.md) and the [development docs](dev/README.md).
