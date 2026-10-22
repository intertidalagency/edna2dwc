# Credentials

`edna2dwc` uses one credential: a GBIF account. `validate --gbif` and `evaluate --gbif` use it to send the archive to GBIF's validation API. WoRMS and the GBIF backbone need no account.

Without an account, the rest of the conversion runs. The GBIF check reads "not measured", which is not a pass.

## Store an account

```bash
edna2dwc credentials set --gbif
```

The command asks for the username, then the password at a prompt that doesn't echo. It checks the account with GBIF before it stores anything. `--no-verify` skips that check, for an offline machine.

The password goes in the OS keyring (Keychain on macOS, Credential Manager on Windows, Secret Service on Linux). With no keyring, it goes in a credentials file that only your user can read. No flag takes a password, because arguments show up in shell history, CI logs and agent transcripts.

```bash
edna2dwc credentials show          # which account, and where it came from
edna2dwc credentials clear --gbif  # remove what `credentials set` stored
```

`doctor` also reports whether an account is configured. It names an account whose password is in the keyring without reading the password, so it never brings up a system prompt such as macOS's Keychain dialog, and neither does `credentials show`. Only a command run with `--gbif` reads the password. On macOS, the first read by a Python install other than the one that stored it asks for Keychain access, and "Always Allow" stops it asking again. Neither command prints the password.

Use a GBIF account that you create only for validation. GBIF's API takes the account's real password over HTTP Basic, and it issues no scoped token. An account with no dataset rights can do no harm if its password leaks. Sign up at [gbif.org/user/profile](https://www.gbif.org/user/profile).

## Lookup order

Sources are tried in this order. A source that is half set or unreadable stops the lookup with its finding, rather than falling through to the next.

| Source | Details |
| --- | --- |
| Environment | `EDNA2DWC_GBIF_USER` and `EDNA2DWC_GBIF_PASS`, both set. Use this in CI |
| OS keyring | Service `edna2dwc`, for the username in the credentials file |
| Credentials file | `credentials.yaml` in the per-user config directory. Refused if other users can read it |
| `~/.netrc` | The `login` and `password` of `machine api.gbif.org` |

`EDNA2DWC_CONFIG_DIR` changes where the credentials file is looked for, for a container or a second account.

A project `.env` file is not read.

## In an agent session

An agent can't set the account up for you. An `export` in one tool call is gone by the next, and a password typed into a command ends up in the transcript. `credentials set` refuses to run without a terminal to prompt at.

Run the command yourself. In Claude Code, prefix it with `!` so it runs in your shell:

```text
! edna2dwc credentials set --gbif
```

The keyring keeps the password out of transcripts, shell history, CI logs and the archive. It doesn't keep it from the agent. On macOS, the Python interpreter that ran `credentials set` can read the Keychain entry again without a prompt, and an agent's `edna2dwc` commands run on that interpreter. The environment, the credentials file and `~/.netrc` are just as readable. To limit the risk, use a validation-only account, and deny the agent access to the credentials file and the keyring tools in your harness's permission settings.

If a password reaches a recorded command anyway, `record-step` drops the whole `NAME=value` word before it writes the step to `conversion.yaml`, and says so. It drops any variable whose name has a part such as `PASS`, `SECRET`, `TOKEN`, `CREDENTIALS` or `KEY`.

## Failures

| Finding | Cause |
| --- | --- |
| `GBIF_CREDENTIALS_MISSING` | No source has an account |
| `GBIF_CREDENTIALS_PARTIAL` | Only one of the two environment variables is set, or the credentials file names a username that no source has a password for |
| `GBIF_CREDENTIALS_UNREADABLE` | The credentials file or `~/.netrc` is readable by other users, or doesn't parse. The message names the file |
| `GBIF_CREDENTIALS_REJECTED` | GBIF answered 401. The account doesn't exist on GBIF, or its password changed |
| `GBIF_VALIDATOR_UNAVAILABLE` | The account was fine, but GBIF's API couldn't be reached |
