# Troubleshooting

## macOS denies access to a folder

On macOS, work outside `~/Documents`, `~/Desktop` and `~/Downloads`, for example in `~/conversions`. macOS grants access to those folders per application, such as your terminal, separately from the rest of your home directory. It can withdraw that access mid-session with no dialog, and after that every read and write fails with `Operation not permitted`.

`build` writes a test file into the conversion directory when it starts, and stops with a message naming the folder if it can't. It can't see access withdrawn after that, during a long step such as `resolve-taxonomy`. If a command fails partway with a permission error in one of those folders, move the conversion directory elsewhere and run it again.

## The GBIF check reads "not measured"

`evaluate --gbif` and `validate --gbif` send the archive to GBIF's validator, which needs a GBIF account. "Not measured" never counts as passed, so `evaluate` won't call the archive ready. The finding says which cause applies:

| Finding | What to do |
| --- | --- |
| `GBIF_CREDENTIALS_MISSING` | Store an account with `edna2dwc credentials set --gbif`. In an agent session, run it yourself: in Claude Code, `! edna2dwc credentials set --gbif` |
| `GBIF_CREDENTIALS_PARTIAL` | Only one of `EDNA2DWC_GBIF_USER` and `EDNA2DWC_GBIF_PASS` is set, or the stored account has no password. Set both variables or neither, or store the account again |
| `GBIF_CREDENTIALS_REJECTED` | GBIF refused the account. Check it at [gbif.org](https://www.gbif.org) and store it again |
| `GBIF_VALIDATOR_UNAVAILABLE` | GBIF's API couldn't be reached. Try again later |

`evaluate` without `--gbif` skips the check on purpose, and it reads "not measured" too. [Credentials](credentials.md) covers the account in full.

## `resolve-taxonomy` is slow

Its time depends on the number of distinct names in the table, not the number of records. It prints an estimate on stderr when it starts, and refines it as batches come back. A dataset with thousands of distinct names can take an hour the first time.

Names already looked up come from the on-disk cache, so running it again, even after a small change to the table, asks only for the new names. A run that stopped on a register outage resumes the same way: run `edna2dwc resolve-taxonomy` again. Avoid `--refresh` unless you need a fresh verdict, because it ignores the cache and saves nothing to it.

`build` doesn't call a register, so only `resolve-taxonomy` waits on one. Run it again only after the table or a `taxonomy:` setting changes.

## `replay` fails installing packages

`replay` runs each reader script under the package versions `conversion.yaml` recorded, and installs them first, which needs network access. Offline, or when a recorded version can no longer be installed, add `--unpin` to use the versions installed now. A replay with `--unpin` may differ from the original if a package changed how it reads a file.

## `build` says to run `resolve-taxonomy`

`build` stops when `resolved_taxonomy.tsv` is missing, lacks a lineage the table has, or was resolved under settings `answers.yaml` no longer gives. This happens after the reader script changes the table, or after a `taxonomy:` block changes. Run `edna2dwc resolve-taxonomy` and build again.

## A command runs out of memory or disk

A `build` that stops this way removes the half-written archive directory, so the next build starts clean.

A command that runs out stops with `Error:` and a message naming its memory limit, where the limit came from, and the free space in the directory it spills to. `edna2dwc doctor` prints the same before you start.

- **Out of memory.** Raise `EDNA2DWC_MEMORY_LIMIT`, such as `EDNA2DWC_MEMORY_LIMIT=8GB`, if the machine has memory to spare. Leave the process about 600 MB above the limit. In a container, raise the container's limit instead: the default follows it.
- **Out of disk.** Free space in the spill directory, or set `TMPDIR` to a directory on a larger disk.

Convert a large dataset whole. A dataset split into parts and merged by hand can't be replayed. See [Memory and disk](commands.md#memory-and-disk).

## Known limitations

- **`countryCode` is blank far from land.** A point in no country's land polygon takes the nearest country's code only when its coast is within 25 km. A sample farther out gets a blank `countryCode`, reported with its coordinates. See [Derived fields](derived-fields.md).
- **OBIS drops names only GBIF knows.** A name WoRMS doesn't have gets a GBIF identifier as `scientificNameID`. GBIF publishes the record, but OBIS drops it unless its own name match finds the name in WoRMS. `taxonomy.registers: [worms]` keeps every record in OBIS, at the cost of coarser names. See [Taxonomy](taxonomy.md).
- **Prokaryote names from SILVA or GTDB may land high.** Many of their genus and family names aren't in WoRMS. Under `taxonomy.registers: [worms]`, those records back off to the deepest rank WoRMS has, which can be the kingdom `Bacteria`. The source lineage stays in `verbatimIdentification`.
- **Lost folder access on macOS can't be detected partway through a command.** See [above](#macos-denies-access-to-a-folder).
