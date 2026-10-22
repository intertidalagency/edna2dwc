from __future__ import annotations

from pathlib import Path

from edna2dwc.conversion import artifacts

INSPECT, DESCRIBE, READ, CONVERT, CHECK = "Inspect", "Describe", "Read", "Convert", "Check"

PURPOSES = {
    INSPECT: "find what data the files contain, and which fields GBIF and OBIS need that they lack",
    DESCRIBE: "give the dataset's title, people and license, and what each marker targets",
    READ: "read the files into one table, one row per sequence per sample",
    CONVERT: "match the names to WoRMS and GBIF, build the archive and review its proposals",
    CHECK: "audit and validate the archive, and go over the fields it is still missing",
}

COMMAND_STAGES = {
    "doctor": INSPECT,
    "inspect": INSPECT,
    "init": DESCRIBE,
    "record-step": READ,
    "assemble": READ,
    "resolve-taxonomy": CONVERT,
    "build": CONVERT,
    "audit record": CHECK,
    "evaluate": CHECK,
}


def build_stage(conversion_dir: Path) -> str:
    return CHECK if (conversion_dir / artifacts.AUDIT_RECORD).exists() else CONVERT


def position(stage: str) -> str:
    return f"Stage {list(PURPOSES).index(stage) + 1} of {len(PURPOSES)}: {stage}"


def stage_line(stage: str, next_step: str) -> str:
    return f"{position(stage)}\nNext: {next_step}"


def overview() -> list[str]:
    return [
        f"{i}. **{stage}**: {purpose}." for i, (stage, purpose) in enumerate(PURPOSES.items(), 1)
    ]
