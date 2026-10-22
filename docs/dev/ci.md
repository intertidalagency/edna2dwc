# CI

## Workflow security

A `zizmor` audit runs on every pull request and every push to `main`, and must report no findings. `just lint` runs it offline. For the full audit, run it with both flags:

```bash
uvx zizmor --persona=pedantic --gh-token="$(gh auth token)" .
```

Without the token, `zizmor` skips `known-vulnerable-actions`. Without `pedantic`, it skips container image pins.

## Pins

Pin each action and container image to a SHA, with the version in a trailing comment. Dependabot updates action pins and `uv.lock` with a seven-day cooldown, and `[tool.uv] exclude-newer = "7 days"` gives Python packages the same delay. The install job and the test job on the newest versions skip that delay, because a user's install doesn't wait.

Dependabot can't see the Bioconductor container image in the workflow file. On a new Bioconductor release, resolve the `bioconductor/bioconductor_docker` tag to a digest by hand and keep the tag in the comment.
