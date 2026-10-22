from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import shlex


SCRIPTS_DIR = Path("scripts")


@dataclass(frozen=True)
class Step:
    n: int
    command: str
    script: str | None = None
    sha256: str | None = None

    def to_dict(self) -> dict:
        if self.script is not None:
        return payload


def hash_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


    scripts_dir.mkdir(parents=True, exist_ok=True)
    content = script_path.read_bytes()
    dest = scripts_dir / script_path.name
        raise ValueError(
        )
    dest.write_bytes(content)
    return dest, hash_bytes(content)


def load_steps(config_path: Path) -> list[Step]:


    try:
    except ValueError as e:
        raise ValueError(f"command is not valid shell-quoted text: {e}") from e


        step["n"] = n
