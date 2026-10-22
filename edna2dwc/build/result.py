from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from edna2dwc.build.derive_fields import PROPOSED_SAMPLES
from edna2dwc.build.questions import MissingAnswer
from edna2dwc.build.sheets import (
    CONTROL_ROSTER,
    DERIVED_VALUES,
    SHEETS,
    TAXA,
    TERM_MAPPING,
    Sheet,
    SheetReview,
)
from edna2dwc.common.findings import HALT_CODES, default_severity
from edna2dwc.common.text import first_few
from edna2dwc.conversion import artifacts, stages
from edna2dwc.dwca.eml import PROFILE_REQUIRED_ELEMENTS

WAITING = "waiting on you"
ACCEPTED = "accepted by --automatic"
DONE = "done"
NOT_REACHED = "not reached yet"

BUILD = "edna2dwc build"

LISTED_UNCONFIRMED = 10


@dataclass(frozen=True)
class ReviewItem:
    kind: str
    title: str
    status: str
    detail: str
    how: str


@dataclass
class BuildResult:
    status: str
    detail: str
    archive_dir: Path | None = None
    missing_answers: list[MissingAnswer] = field(default_factory=list)
    sheets: list[SheetReview] = field(default_factory=list)
    blank_metadata: list[str] = field(default_factory=list)
    unconfirmed: list[str] = field(default_factory=list)
    adjudications_needed: list[str] = field(default_factory=list)
    missing_eml_elements: list[str] = field(default_factory=list)
    automatic: bool = False
    refused: bool = False
    findings: list[dict] = field(default_factory=list)
    stage: str = stages.CONVERT

    @property
    def unconfirmed_count(self) -> int:
        return len(self.unconfirmed) + sum(review.rows.unconfirmed for review in self.sheets)

    @property
    def unconfirmed_sheet_rows(self) -> list[str]:
        return [review.unconfirmed_summary for review in self.sheets if review.rows.unconfirmed]

    @property
    def open_sheets(self) -> list[SheetReview]:
        return [] if self.automatic else [review for review in self.sheets if review.open]

    @property
    def items(self) -> list[ReviewItem]:
        return (
            _error_items(self)
            + _answer_items(self)
            + _blank_items(self)
            + _unconfirmed_items(self)
            + _adjudication_items(self)
            + _sheet_items(self)
        )

    @property
    def waiting(self) -> list[ReviewItem]:
        return [item for item in self.items if item.status == WAITING]

    @property
    def halt_finding(self) -> dict | None:
        if not self.detail:
            return None
        code = HALT_CODES[self.status]
        return {
            "code": code,
            "severity": default_severity(code),
            "message": self.detail,
            "count": 1,
        }

    @property
    def next_step(self) -> str:
        if self.status == "error":
            return f"fix the error above, then `{BUILD}`"
        if waiting := self.waiting:
            return (
                f'close the {len(waiting)} item(s) under "Waiting on you" in '
                f"{artifacts.REVIEW_PAGE}, then `{BUILD}`"
            )
        archive = self.archive_dir.as_posix() if self.archive_dir else "<archive_dir>"
        if self.stage == stages.CHECK:
            return f"`edna2dwc evaluate {archive}`"
        return (
            f"Stage 5, Check: audit the archive with `edna2dwc audit prompt {archive}`, "
            "then `edna2dwc audit record`"
        )

    @property
    def exit_code(self) -> int:
        return 1 if self.status == "error" else 0


def _error_items(result: BuildResult) -> list[ReviewItem]:
    if result.status != "error":
        return []
    return [
        ReviewItem(
            "error",
            "The build stopped on an error",
            WAITING,
            result.detail,
            f"Fix what it names, then `{BUILD}`",
        )
    ]


def _answer_items(result: BuildResult) -> list[ReviewItem]:
    return [
        ReviewItem(
            "answer",
            missing.key,
            WAITING,
            missing.question,
            f"Set `{missing.key}` in `{artifacts.ANSWERS}` to `{missing.example}`, then `{BUILD}`",
        )
        for missing in result.missing_answers
    ]


def _blank_items(result: BuildResult) -> list[ReviewItem]:
    return [
        ReviewItem(
            "answer",
            f"metadata.{name}",
            WAITING,
            _blank_detail(name, result.missing_eml_elements),
            f"Set `metadata.{name}` in `{artifacts.ANSWERS}`, then `{BUILD}`",
        )
        for name in result.blank_metadata
    ]


def _unconfirmed_items(result: BuildResult) -> list[ReviewItem]:
    used = (
        " They were used as written under --automatic, so the archive carries them unreviewed."
        if result.automatic
        else " The archive is built with them, and waits here until a person has seen each one."
    )
    sections = {
        **{
            section: (len(keys), _listed(keys))
            for section, keys in _by_section(result.unconfirmed).items()
        },
        **{
            review.sheet.confirmed.as_posix(): (
                review.rows.unconfirmed,
                first_few(
                    [f"`{row}`" for row in review.rows.first_unconfirmed],
                    LISTED_UNCONFIRMED,
                    review.rows.unconfirmed,
                ),
            )
            for review in result.sheets
            if review.rows.unconfirmed
        },
    }
    return [
        ReviewItem(
            "answer",
            section,
            ACCEPTED if result.automatic else WAITING,
            f"{count} answer(s) no person has confirmed: {listed}.{used}",
            f"Ask the researcher about each, then paste their reply into its `confirmed` "
            f'{_confirmed_location(section)}, such as `confirmed: "PI: yes, V4 primers"`, '
            f"then `{BUILD}`. With nobody to ask, leave `confirmed` empty and run "
            f"`{BUILD} --automatic`; never write it yourself",
        )
        for section, (count, listed) in sections.items()
    ]


def _by_section(keys: list[str]) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    for key in keys:
        sections.setdefault(_section_of(key), []).append(key)
    return sections


def _section_of(key: str) -> str:
    return key.rsplit(".", 1)[0] if "." in key else key


def _listed(keys: list[str]) -> str:
    return first_few([f"`{key}`" for key in keys], LISTED_UNCONFIRMED)


def _confirmed_location(section: str) -> str:
    if section.startswith(f"{artifacts.CONFIRMED_DIR.as_posix()}/"):
        return f"column of `{section}`"
    return f"field in `{artifacts.ANSWERS}`"


def _adjudication_items(result: BuildResult) -> list[ReviewItem]:
    return [
        ReviewItem(
            "adjudication",
            "Finding to judge",
            WAITING,
            message,
            f"If the archive is right as it is, add the line it names under `adjudications:` "
            f"in `{artifacts.ANSWERS}`, with its provenance and the person's reply in "
            f"`confirmed`. Otherwise correct the data. Then `{BUILD}`",
        )
        for message in result.adjudications_needed
    ]


def _blank_detail(name: str, missing_eml_elements: list[str]) -> str:
    element = PROFILE_REQUIRED_ELEMENTS.get(name)
    if element in missing_eml_elements:
        return (
            f"Blank, so `eml.xml` has no `<{element}>`. GBIF's EML profile requires one, so "
            "the archive can't be published until it is set."
        )
    return "Blank, so left out of the archive, which can't be published until it is set."


def _sheet_items(result: BuildResult) -> list[ReviewItem]:
    reviews = {review.sheet: review for review in result.sheets}
    items = []
    for sheet in SHEETS:
        title = f"{sheet.name}: {sheet.title}"
        review = reviews.get(sheet)
        if review is None:
            items.append(
                ReviewItem("proposal", title, NOT_REACHED, f"`{sheet.proposal.as_posix()}`", "")
            )
        elif review.confirmed:
            items.append(ReviewItem("proposal", title, DONE, _applied_detail(review), ""))
        elif not review.reason:
            items.append(ReviewItem("proposal", title, DONE, "Nothing to review", ""))
        elif result.automatic:
            items.append(
                ReviewItem(
                    "proposal",
                    title,
                    ACCEPTED,
                    f"Used as written: {review.reason}. The proposal is "
                    f"`{sheet.proposal.as_posix()}`.",
                    _how_to_close(sheet),
                )
            )
        else:
            items.append(
                ReviewItem(
                    "proposal",
                    title,
                    WAITING,
                    f"{review.reason}. The proposal is `{sheet.proposal.as_posix()}`.",
                    _how_to_close(sheet),
                )
            )
    return items


def _applied_detail(review: SheetReview) -> str:
    applied = f"Applied `{review.sheet.confirmed.as_posix()}`"
    if not review.rows.changed:
        return applied
    return (
        f"{applied}: {review.rows.changed} row(s) changed, {review.rows.unconfirmed} not confirmed"
    )


def _how_to_close(sheet: Sheet) -> str:
    return _how_to_confirm(sheet) + _ROW_NOTES.get(sheet, "")


_PROVENANCE_NOTE = (
    ". In each row you change, put what the change rests on in `provenance` and the person's "
    "reply in `confirmed`"
)
_ROW_NOTES = {
    TERM_MAPPING: (
        f"{_PROVENANCE_NOTE}. Target `extendedmeasurementorfact` makes a column measurement "
        "rows, target `dynamicProperties` keeps it in dynamicProperties, and a blank target "
        "with basis `internal` leaves it out of the archive. The `measurement` column shows "
        "the type and unit build publishes and only informs: set a unit under `units:` in "
        f"`{artifacts.ANSWERS}`"
    ),
    TAXA: (
        f"{_PROVENANCE_NOTE}. A row that changes `scientificName` gives the new name's "
        "`scientificNameID`, `taxonRank` and `scientificNameAuthorship`, or leaves each you "
        "don't know blank"
    ),
    DERIVED_VALUES: (
        f"{_PROVENANCE_NOTE}. The proposal holds the first {PROPOSED_SAMPLES} samples. To "
        "correct a later sample, add its row under the same header, filling only its `sampleID`, "
        "`featureID`, `provenance`, `confirmed` and the values you change. An empty cell keeps the "
        "derived value"
    ),
}


def _how_to_confirm(sheet: Sheet) -> str:
    if sheet is CONTROL_ROSTER:
        return (
            f"Settle each sample under `controls:` in `{artifacts.ANSWERS}`, as `<sampleID>: "
            "{value: control or sample, provenance: <why>, confirmed: <the person's reply>}`, then "
            f"`{BUILD}`. An answer settles any sample"
        )
    return (
        f"Write `{sheet.confirmed.as_posix()}` with the header of "
        f"`{sheet.proposal.as_posix()}` and only the rows you change, then `{BUILD}`. A "
        "header alone accepts the proposal. Rows you leave out follow the proposal on every build"
    )
