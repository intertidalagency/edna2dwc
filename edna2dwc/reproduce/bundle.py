from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import posixpath
import re
import shlex
import shutil

from edna2dwc.common.findings import FindingsLog
from edna2dwc.conversion import artifacts
from edna2dwc.reproduce import steps_log
from edna2dwc.validation import validate

SCRIPTS_DIR_NAME = "scripts"

_STRING_LITERAL_RE = re.compile(
    r"""(?P<quote>["'])(?P<text>(?:(?!(?P=quote))[^\n]){2,}?)(?P=quote)"""
)
_FIXED_PLACE_RE = re.compile(r"^(?:/[^/]+/|[A-Za-z]:[\\/]|~[\\/]|\.\.[\\/])")
_FILE_SUFFIX_RE = re.compile(r"\.[A-Za-z0-9]{1,5}$")
_RAW_HOW = (
    "Copy the inputs inside the conversion directory, read each by a path relative to it, "
    "and name each in record-step --raw"
)


REQUIRED: dict[Path, str] = {
    artifacts.CONFIG: "the recipe: reader scripts, raw inputs, environment and taxonomy resolution",
    artifacts.ANSWERS: "every answer a person gave about the dataset",
    artifacts.RESOLVED_TAXONOMY: "the taxonomy lock: build reads no register",
}


def recorded_raw_inputs(config_path: Path) -> list[Path]:
    return [Path(path) for path in artifacts.read_recipe(config_path).get("raw_inputs") or []]


@dataclass
class BundleResult:
    files: dict[str, Path] = field(default_factory=dict)
    log: FindingsLog = field(default_factory=FindingsLog)

    @property
    def arcnames(self) -> list[str]:
        return sorted(self.files)

    def add(self, arcname: str | Path, source: Path) -> None:
        self.files[(artifacts.BUNDLE_DIR / arcname).as_posix()] = source


def collect(
    project_dir: Path,
    *,
    justfile_path: Path,
    raw_inputs: list[Path] | None = None,
    config_inputs: list[Path] | None = None,
) -> BundleResult:
    result = BundleResult()
    for path, why in REQUIRED.items():
        if (project_dir / path).exists():
            result.add(path, project_dir / path)
        else:
            result.log.add(
                "BUNDLE_ARTIFACT_MISSING",
                f"{path} is absent, so the bundle cannot replay ({why})",
                severity="error",
            )

    for sheet in sorted((project_dir / artifacts.CONFIRMED_DIR).glob("*.tsv")):
        result.add(artifacts.CONFIRMED_DIR / sheet.name, sheet)

    _collect_config_inputs(result, project_dir, config_inputs or [])

    if (project_dir / artifacts.AUDIT_RECORD).exists():
        result.add(artifacts.AUDIT_RECORD, project_dir / artifacts.AUDIT_RECORD)
    if justfile_path.exists():
        result.add("justfile", justfile_path)

    scripts_dir = project_dir / SCRIPTS_DIR_NAME
    if scripts_dir.is_dir():
        run = _scripts_the_steps_run(project_dir / artifacts.CONFIG)
        for script in sorted(scripts_dir.iterdir()):
            if script.is_file():
                arcname = f"{SCRIPTS_DIR_NAME}/{script.name}"
                result.add(arcname, script)
                if arcname not in run:
                    result.log.add(
                        "BUNDLE_SCRIPT_NOT_RUN",
                        f"{arcname} is bundled, but no step in conversion.yaml runs it: "
                        "delete it unless a reader script imports it",
                        severity="info",
                    )

    _collect_raw(result, project_dir, [project_dir / path for path in raw_inputs or []])
    steps = steps_log.load_steps(project_dir / artifacts.CONFIG)
    result.log.findings.extend(check_recipe(project_dir, steps, raw_inputs or []).findings)
    return result


def _scripts_the_steps_run(config_path: Path) -> set[str]:
    if not config_path.exists():
        return set()
    return {step.script for step in steps_log.load_steps(config_path) if step.script}


def _normal(path: Path | str) -> str:
    return posixpath.normpath(Path(path).as_posix())


def _under(path: str, directory: str) -> bool:
    return path == directory or path.startswith(f"{directory}/")


def _fixed_place(text: str) -> bool:
    return bool(_FIXED_PLACE_RE.match(text)) or Path(text).is_absolute()


@dataclass(frozen=True)
class _Recipe:
    project_dir: Path
    scripts: frozenset[str]
    raw_inputs: frozenset[str]

    def names_a_known_input(self, path: str) -> bool:
        normal = _normal(path)
        return (
            normal in self.scripts
            or _under(normal, artifacts.TABLES_DIR.as_posix())
            or any(_under(raw, normal) for raw in self.raw_inputs)
        )

    def exists(self, path: str) -> bool:
        return (self.project_dir / path).exists()


def check_recipe(
    project_dir: Path, steps: list[steps_log.Step], raw_inputs: list[Path]
) -> FindingsLog:
    log = FindingsLog()
    recipe = _Recipe(
        project_dir,
        frozenset(_normal(step.script) for step in steps if step.script),
        frozenset(_normal(path) for path in raw_inputs),
    )
    for raw in sorted(recipe.raw_inputs):
        if _under(raw, artifacts.TABLES_DIR.as_posix()):
            log.add(
                "BUNDLE_ARTIFACT_MISSING",
                f"{raw} is recorded as a raw input, but {artifacts.TABLES_DIR}/ holds what the "
                "reader scripts write, which a replay writes again. Record the file the script "
                "reads instead, with record-step --raw",
                severity="error",
            )
    if recipe.scripts and not recipe.raw_inputs:
        log.add(
            "BUNDLE_ARTIFACT_MISSING",
            "conversion.yaml records reader scripts and no raw_inputs, so reproduce/ holds no "
            "source file for them to read on replay. Record each file a reader script reads "
            "with `record-step --raw`",
            severity="error",
        )
    for step in steps:
        script = project_dir / step.script if step.script else None
        for problem in check_step(recipe, step.command, script):
            log.add("BUNDLE_ARTIFACT_MISSING", f"step {step.n}: {problem}", severity="error")
    return log


def recipe_for_recording(project_dir: Path, scripts: list[str], raw_inputs: list[Path]) -> _Recipe:
    return _Recipe(
        project_dir,
        frozenset(_normal(script) for script in scripts),
        frozenset(_normal(path) for path in raw_inputs),
    )


def check_step(recipe: _Recipe, command: str, script: Path | None) -> list[str]:
    problems = [
        f"the command names {token}, which is not a recorded script, a raw input "
        f"conversion.yaml names, or a file under {artifacts.TABLES_DIR}/, so a replay from "
        f"reproduce/ does not have it. {_RAW_HOW}"
        for token in _path_tokens(command)
        if (_fixed_place(token) or recipe.exists(token)) and not recipe.names_a_known_input(token)
    ]
    if script is None or not script.is_file():
        return problems
    name = script.as_posix()
    for literal in _string_literals(script.read_text(encoding="utf-8", errors="replace")):
        if _fixed_place(literal):
            problems.append(
                f"{name} reads {literal!r}, a fixed place a replay elsewhere does not have. "
                f"{_RAW_HOW}"
            )
        elif _reads_an_unrecorded_input(recipe, literal, script.name):
            problems.append(
                f"{name} reads {literal!r}, which no --raw names, so reproduce/ will not "
                f"hold it. Record the step again with --raw {literal}"
            )
    return problems


def _reads_an_unrecorded_input(recipe: _Recipe, literal: str, script_name: str) -> bool:
    return (
        _looks_like_a_path(literal)
        and literal != script_name
        and recipe.exists(literal)
        and not recipe.names_a_known_input(literal)
    )


def _path_tokens(command: str) -> list[str]:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return []
    candidates = (token.rpartition("=")[2] for token in tokens)
    return [
        candidate
        for candidate in candidates
        if ("/" in candidate or "\\" in candidate) and "://" not in candidate
    ]


def _string_literals(text: str) -> list[str]:
    return list(dict.fromkeys(match["text"] for match in _STRING_LITERAL_RE.finditer(text)))


def _looks_like_a_path(literal: str) -> bool:
    return "://" not in literal and (
        "/" in literal or "\\" in literal or bool(_FILE_SUFFIX_RE.search(literal))
    )


def _collect_config_inputs(
    result: BundleResult, project_dir: Path, config_inputs: list[Path]
) -> None:
    for named in config_inputs:
        arcname = Path(os.path.normpath(named))
        if arcname in REQUIRED:
            continue
        if named.is_absolute() or arcname.parts[:1] == ("..",):
            result.log.add(
                "BUNDLE_ARTIFACT_MISSING",
                f"answers.yaml points at {named.as_posix()}, which is outside the conversion "
                "directory, so no bundled copy would be where the recorded command "
                "looks for it",
                severity="error",
            )
            continue
        source = project_dir / arcname
        if source.exists():
            result.add(arcname, source)
        else:
            result.log.add(
                "BUNDLE_ARTIFACT_MISSING",
                f"answers.yaml points at {named.as_posix()}, which does not exist, so a replay "
                "cannot read it",
                severity="error",
            )


def _collect_raw(result: BundleResult, project_dir: Path, raw_inputs: list[Path]) -> None:
    for source in raw_inputs:
        relative = _inside(source.absolute(), project_dir.absolute()) or _inside(
            source.resolve(), project_dir.resolve()
        )
        if relative is None:
            result.log.add(
                "BUNDLE_ARTIFACT_MISSING",
                f"{source} is a raw input outside the conversion directory "
                f"{project_dir.resolve()}, so reproduce/ can't hold it where the recorded command "
                "reads it. Move it inside and record the step again, keeping `--raw` naming the "
                "moved file, then build again",
                severity="error",
            )
        elif not source.is_file():
            result.log.add(
                "BUNDLE_ARTIFACT_MISSING",
                f"{source} is a raw input conversion.yaml names, and it is missing. Put it back "
                f"at {project_dir.resolve() / relative}, where the recorded command reads it, "
                "then build again",
                severity="error",
            )
        else:
            result.add(relative, source)


def _inside(path: Path, root: Path) -> Path | None:
    try:
        relative = Path(os.path.relpath(path, root))
    except ValueError:
        return None
    return None if relative.parts[:1] == ("..",) else relative


def write(result: BundleResult, out_dir: Path) -> list[str]:
    for arcname, source in sorted(result.files.items()):
        destination = out_dir / arcname
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    return result.arcnames


def check_declared_tables(archive_dir: Path) -> FindingsLog:
    log = FindingsLog()
    meta = archive_dir / "meta.xml"
    try:
        tables = validate.parse_meta_xml(meta) if meta.exists() else None
    except validate.ArchiveInvalidError as e:
        log.add("BUNDLE_ARTIFACT_MISSING", f"{meta} could not be read: {e}", severity="error")
        return log
    if tables is None:
        log.add("BUNDLE_ARTIFACT_MISSING", f"{meta} is missing", severity="error")
        return log
    for table in tables:
        if not (archive_dir / table.file_location).exists():
            log.add(
                "BUNDLE_ARTIFACT_MISSING",
                f"meta.xml declares {table.file_location}, which is not in {archive_dir}, so "
                "the rewritten zip leaves it out; restore the file under that name",
                severity="error",
            )
    return log
