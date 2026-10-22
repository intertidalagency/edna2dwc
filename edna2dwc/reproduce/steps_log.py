from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import posixpath
import re
import shlex

from edna2dwc.conversion import artifacts

SCRIPTS_DIR = Path("scripts")
_SECRET_ASSIGNMENT = re.compile(
    r"^(?:[A-Za-z0-9]*_)*(PASS|PASSWD|PASSWORD|SECRETS?|TOKENS?|CREDENTIALS?|API_?KEYS?|KEYS?)"
    r"(?:_[A-Za-z0-9]*)*=",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Step:
    n: int
    command: str
    script: str | None = None
    sha256: str | None = None

    def to_dict(self) -> dict:
        payload = {"n": self.n, "command": self.command}
        if self.script is not None:
            payload |= {"script": self.script, "sha256": self.sha256}
        return payload


def redact_command(command: str) -> str:
    args = shlex.split(command)
    kept = [arg for arg in args if not _SECRET_ASSIGNMENT.match(arg)]
    return command if kept == args else shlex.join(kept)


def hash_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def vendor_script(
    script_path: Path, scripts_dir: Path = SCRIPTS_DIR, *, replace: bool = False
) -> tuple[Path, str]:
    scripts_dir.mkdir(parents=True, exist_ok=True)
    content = script_path.read_bytes()
    dest = scripts_dir / script_path.name
    if not replace and dest.exists() and dest.read_bytes() != content:
        raise ValueError(
            f"{dest} already contains a different script. Rename {script_path.name} before "
            "recording it"
        )
    dest.write_bytes(content)
    return dest, hash_bytes(content)


def load_steps(config_path: Path) -> list[Step]:
    return [Step(**s) for s in artifacts.read_recipe(config_path).get("steps", [])]


def record_step(
    config_path: Path,
    *,
    command: str,
    script: Path,
    index: int | None = None,
) -> tuple[Step, bool]:
    raw = artifacts.read_recipe(config_path)
    existing = raw.get("steps", [])
    if (at := _logged_position(existing, script)) is None:
        step = insert_step(config_path, command=command, script=script, index=index)
        return step, False
    if index is not None:
        raise ValueError(
            f"{script.name} is already step {at + 1}, and recording it again replaces that step "
            "in place. Leave out --position"
        )
    existing[at] = _entry(command, script, replace=True)
    _write(config_path, raw, existing)
    return Step(**existing[at]), True


def _logged_position(steps: list[dict], script: Path) -> int | None:
    vendored = (SCRIPTS_DIR / script.name).as_posix()
    return next((i for i, step in enumerate(steps) if step.get("script") == vendored), None)


def insert_step(
    config_path: Path,
    *,
    command: str,
    script: Path,
    index: int | None = None,
) -> Step:
    raw = artifacts.read_recipe(config_path)
    existing = raw.get("steps", [])
    if index is not None and not (0 <= index <= len(existing)):
        raise ValueError(f"position {index + 1} is outside a log of {len(existing)} step(s)")

    first_tool = next((i for i, step in enumerate(existing) if "script" not in step), None)
    at = (len(existing) if first_tool is None else first_tool) if index is None else index
    existing.insert(at, _entry(command, script))
    _write(config_path, raw, existing)
    return Step(**existing[at])


def _entry(command: str, script: Path, *, replace: bool = False) -> dict:
    try:
        command = redact_command(command)
    except ValueError as e:
        raise ValueError(f"command is not valid shell-quoted text: {e}") from e
    if not command.strip():
        raise ValueError("command is empty: record the exact command that ran")
    _check_command_runs(command, (SCRIPTS_DIR / script.name).as_posix())
    dest, sha256 = vendor_script(script, replace=replace)
    return Step(n=0, command=command, script=dest.as_posix(), sha256=sha256).to_dict()


def _check_command_runs(command: str, vendored: str) -> None:
    named = {posixpath.normpath(token.rpartition("=")[2]) for token in shlex.split(command)}
    if vendored not in named:
        raise ValueError(
            f"command never runs {vendored}, the copy of the script a replay has. Name that "
            f"path in the command, as in python {vendored}"
        )


def record_tool_step(config_path: Path, command: str) -> Step:
    raw = artifacts.read_recipe(config_path)
    existing = raw.get("steps", [])
    tool = shlex.split(command)[:2]
    kept = [step for step in existing if shlex.split(step["command"])[:2] != tool]
    kept.append(Step(n=0, command=redact_command(command)).to_dict())
    _write(config_path, raw, kept)
    return Step(**kept[-1])


def refuse_raw_inputs_outside(root: Path, paths: tuple[Path, ...]) -> None:
    outside = [path for path in paths if not path.resolve().is_relative_to(root.resolve())]
    if outside:
        raise ValueError(
            f"{', '.join(map(str, outside))} is outside the conversion directory {root.resolve()}, "
            "so reproduce/ can't hold it where the recorded command reads it. Copy it inside, "
            "name that path in --command, and record the step again. Keep --raw naming the "
            "copy: a step with no raw input can't replay"
        )


def record_raw_inputs(config_path: Path, paths: tuple[Path, ...]) -> None:
    if not paths:
        return
    raw = artifacts.read_recipe(config_path)
    recorded = raw.get("raw_inputs") or []
    recorded += [path.as_posix() for path in paths if path.as_posix() not in recorded]
    raw["raw_inputs"] = recorded
    artifacts.write_recipe(config_path, raw)


def _write(config_path: Path, raw: dict, steps: list[dict]) -> None:
    for n, step in enumerate(steps, start=1):
        step["n"] = n
    raw["steps"] = steps
    artifacts.write_recipe(config_path, raw)
