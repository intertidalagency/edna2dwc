# skills/

This directory contains `edna2dwc`'s agent skill: `SKILL.md` and the reference files it points at. The skill teaches a coding agent to drive the installed CLI. It needs no particular harness.

To install it, copy or symlink `convert-edna-to-dwc/` into your agent's skills directory. The README's installation section has the details.

This directory is not packaged into the wheel. `.agents/skills/convert-edna-to-dwc` and `.claude/skills/convert-edna-to-dwc` symlink back to it, so this repository loads its own skill during development. Skills for developing this repository sit beside the `.claude/` link and are not tracked. See `CONTRIBUTING.md`.
