from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from edna2dwc.common.findings import HALT_CODES
from edna2dwc.conversion import answers, artifacts
from edna2dwc.reproduce import compare, environment, steps_log


class EnvironmentUnavailableError(RuntimeError):
    def __init__(self, message: str, *, culprit: str | None = None) -> None:
        super().__init__(message)
        self.culprit = culprit


def _find_culprit(stderr: str, pins: dict[str, str]) -> str | None:
    for package in pins:
        if package in stderr:
            return package
    return None


def build_uv_run_args(env: environment.EnvironmentRecord, script: str) -> list[str]:
    args = ["uv", "run", "--python", env.python]
    for package, pinned_version in env.reconstructable_pins().items():
        if pinned_version != environment.UNKNOWN_VERSION:
            args += ["--with", f"{package}=={pinned_version}"]
    args += ["--", "sh", "-c", script]
    return args


def copy_bundle_for_replay(bundle_dir: Path, scratch_dir: Path) -> Path:
    if scratch_dir.exists():
        if not scratch_dir.is_dir():
            raise FileExistsError(f"{scratch_dir} is not a directory")
        if any(scratch_dir.iterdir()):
            raise FileExistsError(f"{scratch_dir} is not empty")
    shutil.copytree(
        bundle_dir,
        scratch_dir,
        symlinks=True,
        dirs_exist_ok=True,
    )
    (scratch_dir / artifacts.TABLES_DIR).mkdir(exist_ok=True)
    (scratch_dir / artifacts.FINDINGS).unlink(missing_ok=True)
    return scratch_dir


def run_steps(
    bundle_dir: Path,
    commands: list[str],
    env: environment.EnvironmentRecord | None,
    *,
    subprocess_run=subprocess.run,
) -> subprocess.CompletedProcess:
    script = " && ".join(commands)
    if env is None:
        args = ["sh", "-c", script]
    else:
        probe = subprocess_run(
            build_uv_run_args(env, "true"), cwd=bundle_dir, capture_output=True, text=True
        )
        if probe.returncode != 0:
            culprit = _find_culprit(probe.stderr, env.reconstructable_pins())
            raise EnvironmentUnavailableError(probe.stderr, culprit=culprit)
        args = build_uv_run_args(env, script)
    return subprocess_run(args, cwd=bundle_dir, capture_output=True, text=True)


BUILD_COMMAND = "edna2dwc build --automatic"

HALTED_AT = {code: status for status, code in HALT_CODES.items()}


def commands_for_replay(steps: list[steps_log.Step]) -> list[str]:
    return [*(step.command for step in steps), BUILD_COMMAND]


def rebuild_status(work_dir: Path, replayed: subprocess.CompletedProcess) -> str:
    findings_path = work_dir / artifacts.FINDINGS
    if not findings_path.exists():
        last = [line for line in replayed.stderr.splitlines() if line.strip()][-1:]
        return f"error: {(last or ['the replayed steps failed'])[0]}"
    findings = json.loads(findings_path.read_text(encoding="utf-8"))
    halt = next((f for f in findings if f["code"] in HALTED_AT), None)
    return f"{HALTED_AT[halt['code']]}: {halt['message']}" if halt else "ok"


def missing_scripts(bundle_dir: Path, steps: list[steps_log.Step]) -> list[str]:
    return [
        step.script for step in steps if step.script and not (bundle_dir / step.script).exists()
    ]


def default_archive_path(bundle_dir: Path) -> Path:
    answers_path = bundle_dir / artifacts.ANSWERS
    out_dir = answers.declared(answers_path, "out_dir")
    if not out_dir:
        raise ValueError(f"{answers_path} has no out_dir recorded")
    return bundle_dir / out_dir / artifacts.ZIP_NAME


def bundle_to_replay(target: Path) -> Path:
    if not (target / artifacts.ANSWERS).exists():
        return target
    try:
        archives_bundle = default_archive_path(target).parent / artifacts.BUNDLE_DIR
    except ValueError:
        return target
    return archives_bundle if archives_bundle.is_dir() else target


def shipped_archive_path(bundle_dir: Path) -> Path:
    resolved = bundle_dir.resolve()
    if resolved.name == artifacts.BUNDLE_DIR.name:
        return resolved.parent / artifacts.ZIP_NAME
    return default_archive_path(bundle_dir)


def unavailable_message(error: EnvironmentUnavailableError) -> str:
    lines = [
        "ENVIRONMENT_UNAVAILABLE: could not reconstruct the recorded environment.",
        str(error),
        "Rerun with --unpin to use today's installed versions instead.",
    ]
    if error.culprit:
        lines.append(
            f"To keep every other pin, remove {error.culprit!r} from conversion.yaml's "
            "environment block and rerun. Only that package then floats to the installed "
            "version."
        )
    return "\n".join(lines)


class RebuildFailedError(RuntimeError):
    pass


def rebuild_and_compare(
    rebuild: Callable[[], None],
    *,
    shipped: Path,
    rebuild_target: Path,
) -> compare.ComparisonResult:
    with tempfile.TemporaryDirectory() as tmp_dir:
        shipped_copy = Path(tmp_dir) / "shipped.zip"
        shutil.copyfile(shipped, shipped_copy)
        backup = Path(tmp_dir) / "rebuild_target.zip"
        had_target = rebuild_target.exists()
        if had_target:
            shutil.copyfile(rebuild_target, backup)

        keep_rebuild = False
        try:
            rebuild()
            if not rebuild_target.exists():
                raise RebuildFailedError(f"replay finished but did not write {rebuild_target}")
            comparison = compare.compare_archives(shipped_copy, rebuild_target)
            comparison.archive_sha256 = compare.archive_digest(shipped_copy)
            keep_rebuild = not comparison.diverged
        finally:
            if not keep_rebuild:
                if had_target:
                    shutil.copyfile(backup, rebuild_target)
                elif rebuild_target.exists():
                    rebuild_target.unlink()
    return comparison
