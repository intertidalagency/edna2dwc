from __future__ import annotations

import contextlib
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Annotated

from cyclopts import Parameter
from cyclopts.types import ExistingFile, ExistingPath

from edna2dwc.cli.app import app
from edna2dwc.cli.common import (
    CommandFailed,
    Flag,
    JsonFlag,
    UsageError,
)
from edna2dwc.cli.groups import stage
from edna2dwc.common.result import CommandResult
from edna2dwc.conversion import artifacts
from edna2dwc.reproduce import compare, environment, replay, steps_log

SUMMARY_NAME = Path("comparison_summary.md")


def _reported_comparison(
    comparison: compare.ComparisonResult,
    output_path: Path,
    *,
    as_json: bool,
    rebuild_status: str | None = None,
) -> CommandResult:
    compare.write_comparison(comparison, output_path)
    text = compare.render_summary_markdown(comparison) + f"Wrote {output_path}.\n"
    body = comparison.to_dict()
    if rebuild_status is not None:
        text += f"Rebuild status: {rebuild_status}"
        body["rebuild_status"] = rebuild_status
    reported = CommandResult(command="replay", json_body=body, text=text, as_json=as_json)
    if comparison.diverged:
        print(reported.render())
        raise CommandFailed(f"Archives diverge: see {output_path}.")
    return reported


def _rebuild_failed(rebuild_status: str) -> bool:
    return rebuild_status.partition(":")[0] in {"error", "needs_decision"}


def _reported_status(rebuild_status: str, *, as_json: bool = False) -> CommandResult:
    return CommandResult(
        command="replay",
        json_body={"rebuild_status": rebuild_status, "diverged": None},
        text=f"Rebuild status: {rebuild_status}",
        as_json=as_json,
        exit_code=1 if _rebuild_failed(rebuild_status) else 0,
    )


@app.command(**stage("replay"))
def replay_cmd(
    *targets: Annotated[ExistingPath, Parameter(required=True)],
    dry_run: Flag = False,
    unpin: Flag = False,
    compare_flag: Annotated[bool, Parameter(name="--compare", negative="")] = False,
    check_flag: Annotated[bool, Parameter(name="--check", negative="")] = False,
    against_path: Annotated[ExistingFile | None, Parameter(name="--against")] = None,
    scratch_dir: Annotated[Path | None, Parameter(name="--scratch-dir")] = None,
    output_path: Annotated[Path | None, Parameter(name=["-o", "--output"])] = None,
    as_json: JsonFlag = False,
) -> CommandResult:
    """Reproduce a conversion from conversion.yaml, or compare two archives.

    Prints the rebuild's status on the last line. Succeeds when the rebuild ends ok or needs_review, and fails when it ends in error or writes no archive. If the recorded package versions can't be installed, replay stops and says so. Rerun with --unpin to use the installed versions instead.

    Args:
        targets: One bundle directory to replay, or a conversion directory, which replays the reproduce/ beside its archive. With --compare, two archive zips, OLD then NEW.
        dry_run: Print the recorded commands and exit. Ignored with --compare.
        unpin: Run the steps under the installed package versions instead of the recorded ones, still through uv run, so python is always on the path. Ignored with --compare.
        compare_flag: Compare two archives instead of replaying one.
        check_flag: Replay, then compare the rebuilt archive against the shipped one.
        against_path: The shipped archive --check compares against. Defaults to the dwca.zip beside a reproduce/ bundle, or to the archive in the out_dir answers.yaml names.
        scratch_dir: Empty or absent directory to replay in. Defaults to a new temporary directory, which --check deletes afterwards.
        output_path: Where --compare and --check write their Markdown summary, with a .json twin beside it. Defaults to comparison_summary.md, in the current directory for --compare and beside the shipped archive for --check, never inside the bundle.
    """
    if compare_flag and check_flag:
        raise UsageError("--compare and --check are mutually exclusive")

    if compare_flag:
        if len(targets) != 2:
            raise UsageError("--compare requires exactly two archives: OLD.zip NEW.zip")
        old_zip, new_zip = targets
        return _reported_comparison(
            compare.compare_archives(old_zip, new_zip),
            output_path or SUMMARY_NAME,
            as_json=as_json,
        )

    if len(targets) != 1:
        raise UsageError("replay takes exactly one bundle directory (see --compare)")
    if not targets[0].is_dir():
        raise UsageError(f"{targets[0]} is not a directory")
    bundle_dir = replay.bundle_to_replay(targets[0])

    config_path = bundle_dir / artifacts.CONFIG
    steps = steps_log.load_steps(config_path)
    commands = replay.commands_for_replay(steps)
    if dry_run:
        return CommandResult(command="replay", text="\n".join(commands))

    missing = replay.missing_scripts(bundle_dir, steps)
    if missing:
        raise CommandFailed(
            "SCRIPT_MISSING: " + "; ".join(f"{s} is absent from {bundle_dir}" for s in missing)
        )

    recorded_env = environment.load_environment(config_path)
    if recorded_env is None:
        raise UsageError(f"{config_path} has no recorded environment to replay against")
    current_env = environment.capture_current_environment()
    progress = sys.stderr if as_json else sys.stdout
    for row in environment.version_diff_table(recorded_env, current_env):
        marker = "*" if row["changed"] else " "
        print(
            f"{marker} {row['package']}: recorded {row['recorded']}, current {row['current']}",
            file=progress,
        )
    if not unpin and recorded_env.edna2dwc_version != current_env.edna2dwc_version:
        print(
            f"NOTE: this archive was built by edna2dwc "
            f"{recorded_env.edna2dwc_version}, and replays here on "
            f"{current_env.edna2dwc_version}. Every other recorded version is reconstructed.",
            file=progress,
        )

    def run_replay(work_dir: Path) -> subprocess.CompletedProcess:
        try:
            result = replay.run_steps(work_dir, commands, current_env if unpin else recorded_env)
        except replay.EnvironmentUnavailableError as e:
            raise CommandFailed(replay.unavailable_message(e)) from e
        print(result.stdout, file=progress)
        return result

    def rebuild_status(work_dir: Path) -> str:
        return replay.rebuild_status(work_dir, run_replay(work_dir))

    def copy_to(scratch: Path) -> Path:
        try:
            return replay.copy_bundle_for_replay(bundle_dir, scratch)
        except FileExistsError as e:
            raise UsageError(f"{e}. Point --scratch-dir at an empty or absent directory") from e

    if check_flag:
        print(f"Replaying a copy of {bundle_dir}; the bundle itself is only read.", file=progress)
        try:
            recorded_archive = replay.shipped_archive_path(bundle_dir)
        except ValueError as e:
            raise UsageError(str(e)) from e
        shipped = against_path or recorded_archive
        if not shipped.exists():
            raise UsageError(f"{shipped} does not exist. Pass --against")
        with contextlib.ExitStack() as stack:
            work_dir = copy_to(
                scratch_dir
                if scratch_dir is not None
                else Path(
                    stack.enter_context(tempfile.TemporaryDirectory(prefix="edna2dwc-replay-"))
                )
                / bundle_dir.name
            )
            rebuild_target = replay.default_archive_path(work_dir)
            statuses = []

            def rebuild() -> None:
                statuses.append(rebuild_status(work_dir))
                if _rebuild_failed(statuses[0]):
                    raise replay.RebuildFailedError(statuses[0])

            try:
                comparison = replay.rebuild_and_compare(
                    rebuild, shipped=shipped, rebuild_target=rebuild_target
                )
            except replay.RebuildFailedError as e:
                if statuses and _rebuild_failed(statuses[0]):
                    return _reported_status(statuses[0], as_json=as_json)
                raise CommandFailed(str(e)) from e

        return _reported_comparison(
            comparison,
            output_path or shipped.parent / SUMMARY_NAME,
            as_json=as_json,
            rebuild_status=statuses[0],
        )

    work_dir = copy_to(
        scratch_dir
        if scratch_dir is not None
        else Path(tempfile.mkdtemp(prefix="edna2dwc-replay-"))
    )
    print(
        f"Replaying a copy of {bundle_dir} in {work_dir}; the bundle itself is only read.",
        file=progress,
    )
    return _reported_status(rebuild_status(work_dir), as_json=as_json)
