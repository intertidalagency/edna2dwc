from __future__ import annotations

from pathlib import Path
from typing import Annotated

from cyclopts import Parameter
from cyclopts.types import ExistingFile

from edna2dwc.cli.app import app
from edna2dwc.cli.common import Flag, JsonFlag, TermsTableIn, UsageError
from edna2dwc.cli.groups import stage
from edna2dwc.common.result import CommandResult
from edna2dwc.conversion import answers, artifacts
from edna2dwc.dwca import writer
from edna2dwc.dwca.eml import EmlRenderError
from edna2dwc.terms.term_table import load_term_table


@app.command(**stage("package"))
def package_cmd(
    *,
    core_spec: Annotated[str, Parameter(name="--core")],
    extension_specs: Annotated[tuple[str, ...], Parameter(name="--extension", negative="")] = (),
    answers_path: Annotated[ExistingFile, Parameter(name="--answers")] = artifacts.ANSWERS,
    terms_table: TermsTableIn = None,
    out_dir: Annotated[Path, Parameter(name=["-o", "--out-dir"])],
    mixs_uri_style: writer.MixsUriStyle = "gensc",
    no_dna_extension: Flag = False,
    no_emof: Flag = False,
    as_json: JsonFlag = False,
) -> CommandResult:
    """Assemble a Darwin Core Archive from tables that already use Darwin Core terms.

    Takes dataset_id, created and the metadata from answers.yaml, and nothing else from it.

    Args:
        core_spec: The core table, as occurrence=PATH.
        extension_specs: An extension table, as TYPE=PATH, where TYPE is dnaderiveddata or extendedmeasurementorfact. Repeatable.
        answers_path: The answers.yaml holding the dataset metadata.
        terms_table: A Darwin Core term table to use instead of the bundled one.
        out_dir: Directory to write the archive's files and zip into.
        mixs_uri_style: MIxS term URI form.
        no_dna_extension: Keep every sequence column in the core instead of a DNADerivedData extension.
        no_emof: Don't build an eMoF extension, and publish dynamicProperties as written.
    """
    try:
        core_path, extensions = writer.resolve_table_specs(core_spec, extension_specs)
        dataset = answers.load(answers_path)
    except (writer.ArchiveBuildError, answers.AnswersError) as exc:
        raise UsageError(str(exc)) from exc
    term_table = load_term_table(terms_table)

    try:
        packaged = writer.write_archive(
            core_path=core_path,
            extensions=extensions,
            manifest=dataset.metadata,
            dataset_id=dataset.dataset_id,
            generated_at=dataset.created,
            term_table=term_table,
            out_dir=out_dir,
            mixs_uri_style=mixs_uri_style,
            no_dna_extension=no_dna_extension,
            no_emof=no_emof,
        )
    except (writer.ArchiveBuildError, EmlRenderError) as exc:
        raise UsageError(str(exc)) from exc
    moved = f". Moved to eMoF: {', '.join(packaged.measured)}" if packaged.measured else ""
    return CommandResult.of(
        "package",
        packaged.findings,
        outputs={
            "archive_dir": str(out_dir),
            "zip": str(out_dir / artifacts.ZIP_NAME),
            "measurements": packaged.measured,
        },
        text=f"Wrote archive to {out_dir} ({artifacts.ZIP_NAME}){moved}",
        as_json=as_json,
    )
