from __future__ import annotations

from pathlib import Path

import platformdirs

from edna2dwc.cli.app import app
from edna2dwc.cli.common import CommandFailed, Flag, JsonFlag, OutputPath, UsageError
from edna2dwc.cli.groups import stage
from edna2dwc.common.result import CommandResult
from edna2dwc.common.tsv import NotTabSeparatedError
from edna2dwc.conversion import answers, artifacts
from edna2dwc.conversion.intermediate import IntermediateMissing
from edna2dwc.taxonomy import lock
from edna2dwc.taxonomy.gbif import GbifError
from edna2dwc.taxonomy.resolve_taxonomy import register_clients
from edna2dwc.taxonomy.worms import WormsBatchAlignmentError, WormsError


def _match_cache_dir(*, refresh: bool) -> Path | None:
    return None if refresh else Path(platformdirs.user_cache_dir("edna2dwc")) / "taxonomy"


def _outage_advice(*, cache_bypassed: bool) -> str:
    if cache_bypassed:
        return (
            "--refresh kept nothing this pass looked up, so retry live with "
            "`edna2dwc resolve-taxonomy --refresh`; rerunning it without --refresh runs "
            "against what is already in the cache"
        )
    return (
        "Rerun `edna2dwc resolve-taxonomy` to resume: every name the register did answer "
        "is in the on-disk match cache, so the rerun asks only for the rest"
    )


def _misalignment_advice() -> str:
    return (
        "WoRMS answered here rather than going quiet, so rerunning sends the same "
        "batch again, which helps only once the register's response has changed"
    )


@app.command(**stage("resolve-taxonomy"))
def resolve_taxonomy_cmd(
    *,
    refresh: Flag = False,
    output_path: OutputPath = artifacts.RESOLVED_TAXONOMY,
    as_json: JsonFlag = False,
) -> CommandResult:
    """Resolve each lineage in occurrence_long.tsv against the registers, under the taxonomy settings in answers.yaml.

    Runs in the conversion directory and writes resolved_taxonomy.tsv, which build reads without calling a register. Each row records the settings it was resolved under and the findings it raised. taxonomy.registers lists the registers to try at each name, in order: [worms, gbif] by default, [worms] never asks GBIF, [gbif] never asks WoRMS. A name WoRMS confirms gets its LSID as scientificNameID; a name only GBIF resolves gets its GBIF species URL, which OBIS can't tie to WoRMS. A marker's own taxonomy: block in markers: overrides the dataset-wide one for its rows, so a prokaryote marker can take registers: [worms] alone. Non-confident matches are refused unless require_confident: false keeps them, flagged for review. Run it again after the table or any taxonomy: block changes; build stops until you do. Names already looked up come from the match cache.

    Args:
        refresh: Look up every name live, bypassing the match cache, and don't update the cache.
        output_path: Where to write the table. Write somewhere other than resolved_taxonomy.tsv to try a setting without replacing what build reads.
    """
    try:
        return lock.run(
            open_registers=register_clients(_match_cache_dir(refresh=refresh)),
            output_path=output_path,
            as_json=as_json,
        )
    except (answers.AnswersError, IntermediateMissing, NotTabSeparatedError) as error:
        raise UsageError(str(error)) from error
    except WormsBatchAlignmentError as refusal:
        raise CommandFailed(f"{refusal}. {_misalignment_advice()}") from refusal
    except (WormsError, GbifError) as outage:
        raise CommandFailed(f"{outage}. {_outage_advice(cache_bypassed=refresh)}") from outage
