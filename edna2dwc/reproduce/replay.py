from __future__ import annotations

from pathlib import Path
import subprocess



class EnvironmentUnavailableError(RuntimeError):
    def __init__(self, message: str, *, culprit: str | None = None) -> None:
        super().__init__(message)
        self.culprit = culprit


def _find_culprit(stderr: str, pins: dict[str, str]) -> str | None:
    for package in pins:
        if package in stderr:
            return package
    return None


    args = ["uv", "run", "--python", env.python]
    args += ["--", "sh", "-c", script]
    return args


    bundle_dir: Path,
    *,
    subprocess_run=subprocess.run,
) -> subprocess.CompletedProcess:






    return [
    ]


    if not out_dir:


def unavailable_message(error: EnvironmentUnavailableError) -> str:
    lines = [
        "ENVIRONMENT_UNAVAILABLE: could not reconstruct the recorded environment.",
        str(error),
        "Rerun with --unpin to use today's installed versions instead.",
    ]
    if error.culprit:
        lines.append(
            f"To keep every other pin, remove {error.culprit!r} from conversion.yaml's "
        )
    return "\n".join(lines)
