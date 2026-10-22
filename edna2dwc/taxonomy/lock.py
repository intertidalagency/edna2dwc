from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from edna2dwc.common.result import CommandResult
from edna2dwc.common.table import connect, read_tsv
from edna2dwc.common.tsv import read_tab_separated_rows
from edna2dwc.common.version import installed_version
from edna2dwc.conversion import answers as answers_file
from edna2dwc.conversion import artifacts
from edna2dwc.conversion.intermediate import markers, require_intermediate
from edna2dwc.taxonomy import derive_lineage, gbif, resolve_taxonomy, worms


def run(
    *,
    open_registers: resolve_taxonomy.OpenRegisters,
    output_path: Path = artifacts.RESOLVED_TAXONOMY,
    as_json: bool = False,
) -> CommandResult:
    answers = answers_file.load(artifacts.ANSWERS)
    require_intermediate(artifacts.INTERMEDIATE)
    with connect() as con:
        source = read_tsv(con, artifacts.INTERMEDIATE, "source")
        scopes = answers.taxonomy_scopes(markers(source))
        lineage = derive_lineage.derive_lineage(source, scopes=scopes)
    settings_by_scope = {
        scope: answers.taxonomy_for(scope)
        for scope in {row["taxonomy_scope"] for row in lineage.lineage_rows}
    }
    result = resolve_taxonomy.step(
        lineage_rows=lineage.lineage_rows,
        output_path=output_path,
        settings_by_scope=settings_by_scope,
        open_registers=open_registers,
        as_json=as_json,
    )
    if output_path.resolve() == artifacts.RESOLVED_TAXONOMY.resolve():
        consulted = {r for settings in settings_by_scope.values() for r in settings.registers}
        _record_resolution(artifacts.CONFIG, consulted=consulted)
    return replace(result, next_step="`edna2dwc build`")


def _record_resolution(config_path: Path, *, consulted: set[str]) -> None:
    raw = artifacts.read_recipe(config_path)
    base_urls = {"worms": worms.BASE_URL, "gbif": gbif.BASE_URL}
    registers = {name: url for name, url in base_urls.items() if name in consulted}
    raw["resolve_taxonomy"] = {
        "resolved_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "edna2dwc_version": installed_version(),
        "registers": registers,
    }
    artifacts.write_recipe(config_path, raw)


class StaleLock(Exception):
    pass


def read(
    root: Path, lineage_rows: list[dict[str, str]], answers: answers_file.Answers
) -> list[dict[str, str]]:
    if not (root / artifacts.RESOLVED_TAXONOMY).exists():
        raise StaleLock(
            f"{artifacts.RESOLVED_TAXONOMY} does not exist. Run `edna2dwc resolve-taxonomy` to "
            "resolve the table's lineages against the registers, then build again."
        )
    lock = list(read_tab_separated_rows(root / artifacts.RESOLVED_TAXONOMY))
    locked = {row["lineage_key"] for row in lock}
    if absent := [row for row in lineage_rows if row["lineage_key"] not in locked]:
        raise StaleLock(
            f"{artifacts.RESOLVED_TAXONOMY} has no row for {len(absent)} lineage(s) of this "
            "table. Run `edna2dwc resolve-taxonomy` to resolve it again, then build again. Names "
            "already looked up come from the match cache."
        )
    lineage_keys = {row["lineage_key"] for row in lineage_rows}
    used = [row for row in lock if row["lineage_key"] in lineage_keys]
    _check_settings(used, lineage_rows, answers)
    return used


def _check_settings(
    lock: list[dict[str, str]], lineage_rows: list[dict[str, str]], answers: answers_file.Answers
) -> None:
    scopes = {row["lineage_key"]: row["taxonomy_scope"] for row in lineage_rows}
    stale = [
        (row.get(resolve_taxonomy.SETTINGS_COLUMN, ""), expected)
        for row in lock
        if row.get(resolve_taxonomy.SETTINGS_COLUMN, "")
        != (expected := answers.taxonomy_for(scopes[row["lineage_key"]]).describe())
    ]
    if stale:
        resolved_under, expected = stale[0]
        raise StaleLock(
            f"{artifacts.RESOLVED_TAXONOMY} resolved {len(stale)} lineage(s) under other "
            f"taxonomy settings than {artifacts.ANSWERS} gives them now, such as "
            f"{resolved_under or 'no recorded settings'!r} where {artifacts.ANSWERS} says "
            f"{expected!r}. Run `edna2dwc resolve-taxonomy` to resolve again, then build again. "
            "Names already looked up come from the match cache."
        )
