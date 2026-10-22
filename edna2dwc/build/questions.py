from __future__ import annotations

from dataclasses import dataclass
import math

from edna2dwc.build import derive_fields
from edna2dwc.build.exclude_taxa import is_human_taxon
from edna2dwc.common.table import ROW, Table, from_rows, internal
from edna2dwc.conversion.answers import MARKER_TARGET_KINGDOMS, Answers
from edna2dwc.dwca.manifest import PEOPLE_FIELDS

QUANTITY_TYPE = "organismQuantityType"


@dataclass(frozen=True)
class MissingAnswer:
    key: str
    question: str
    example: str


def missing_answers(
    answers: Answers, table_markers: set[str], ambiguous_samples: list[str]
) -> list[MissingAnswer]:
    missing = [
        MissingAnswer(
            f"metadata.{name}",
            f"This dataset's {name} can't be derived from its tables. Find it in an EML file, "
            "a manuscript or the sample metadata, or ask the researcher. If it is waiting on "
            "the provider, leave the value blank and say so in provenance:.",
            _metadata_example(name),
        )
        for name in answers.blank_metadata()
    ]
    targets = answers.marker_targets(table_markers)
    missing += [
        _marker_question(marker)
        for marker in sorted(table_markers)
        if marker not in targets and (marker or table_markers == {""})
    ]
    missing += [
        MissingAnswer(
            f"controls.{sample_id}",
            f"Sample {sample_id!r} matched only an ambiguous control keyword in its ID, with no "
            "sample metadata to corroborate it. Is it a control to exclude, or a real sample?",
            "{value: control or sample, provenance: <why>, confirmed: <the person's reply>}",
        )
        for sample_id in ambiguous_samples
    ]
    return missing


def _metadata_example(name: str) -> str:
    if name in PEOPLE_FIELDS:
        person = (
            "{given: <given name>, surname: <surname>, organization: <organization>, "
            "email: <email>, orcid: <ORCID iD>}"
        )
        return f"{{value: [{person}], provenance: <where it came from>, confirmed: <the person's reply>}}"
    return f"{{value: <the {name}>, provenance: <where it came from>, confirmed: <the person's reply>}}"


def _marker_question(marker: str) -> MissingAnswer:
    target = (
        f"{{target: <one or more of {', '.join(MARKER_TARGET_KINGDOMS)}>, "
        "provenance: <the document and where in it>, confirmed: <the person's reply>}"
    )
    evidence = (
        "Answer from primer sequences, .qza provenance or the methods, never from the marker's "
        'name: "16S" is both a bacterial and a vertebrate mitochondrial target. The answer '
        "scopes filters.exclude_kingdoms for every row with this marker."
    )
    if not marker:
        return MissingAnswer(
            "markers",
            "What does this dataset's marker amplify? The table has no marker column, so "
            f"markers takes exactly one entry, under any name. {evidence}",
            f"{{<marker name>: {target}}}",
        )
    return MissingAnswer(
        f"markers.{marker}", f"What does the {marker!r} marker amplify? {evidence}", target
    )


def _is_fraction(count: str) -> bool:
    try:
        value = float(count)
    except ValueError:
        return False
    return math.isfinite(value) and not value.is_integer()


def quantity_questions(table: Table, quantity_types: dict[str, str]) -> list[MissingAnswer]:
    count = table.text("count")
    distinct = table.rows(f"SELECT DISTINCT {count} FROM {table.name}")
    fraction = internal("fraction")
    from_rows(
        table.con,
        "fraction_counts",
        {fraction: "VARCHAR"},
        [(value,) for (value,) in distinct if _is_fraction(value)],
    )
    found = table.rows(
        f"SELECT {table.text('marker')}, count(*), arg_min({count}, {ROW}) FROM {table.name} "
        f"WHERE {count} IN (SELECT {fraction} FROM fraction_counts) GROUP BY 1"
    )
    return [
        _quantity_question(marker, rows, first)
        for marker, rows, first in sorted(found)
        if marker not in quantity_types
    ]


def _quantity_question(marker: str, count: int, first: str) -> MissingAnswer:
    rows = f"{count} row(s) of marker {marker!r}" if marker else f"{count} row(s)"
    section = f"markers.{marker}.constants" if marker else "constants"
    return MissingAnswer(
        f"{section}.{QUANTITY_TYPE}",
        f"{rows} have a count that is not a whole number, such as {first}, so count "
        "can't be a number of DNA sequence reads. What does it measure? The answer labels "
        "organismQuantity. Find it in the methods, or ask the researcher. "
        f"A dataset-wide constants.{QUANTITY_TYPE} answers it for every marker.",
        "{value: <what count measures, such as relative abundance>, provenance: <the document and where in it>}",
    )


def human_question(
    table: Table, humans: Table, quantity_types: dict[str, str]
) -> MissingAnswer | None:
    counts = table.rows(
        f"SELECT {table.text('marker', 'row')}, {table.text('count', 'row')}, count(*) "
        f"FROM {table.name} AS row JOIN {humans.name} ON {is_human_taxon(table, 'row', humans)} "
        "GROUP BY ALL"
    )
    if not counts:
        return None
    rows = sum(found for _, _, found in counts)
    reads = derive_fields.total_reads(counts, quantity_types)
    amount = f"{rows} row(s), {reads} reads," if reads else f"{rows} row(s)"
    return MissingAnswer(
        "filters.exclude_human",
        f"{amount} resolve to humans (Homo). Human DNA in an "
        "environmental sample is usually contamination from handling. Should they be left "
        "out of the archive (true)? Publish them (false) only if the study set out to detect "
        "people.",
        "{value: true or false, provenance: <why>, confirmed: <the person's reply>}",
    )
