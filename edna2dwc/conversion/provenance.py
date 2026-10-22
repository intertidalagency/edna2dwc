from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from edna2dwc.common.text import first_few

PROVENANCE = "provenance"
CONFIRMED = "confirmed"
ANSWER_COLUMNS = (PROVENANCE, CONFIRMED)

SHAPE = (
    "{{{value}provenance: <what the answer rests on>, confirmed: <a person's reply, or empty>}}"
)

NOT_A_PERSONS_WORDS = frozenset(
    {
        "agent",
        "ai",
        "assistant",
        "assumed",
        "auto",
        "automated",
        "automatic",
        "automatically",
        "claude",
        "confirmed",
        "data",
        "default",
        "derived",
        "document",
        "false",
        "inferred",
        "llm",
        "model",
        "n/a",
        "na",
        "no",
        "none",
        "ok",
        "pending",
        "reviewed",
        "script",
        "self",
        "source",
        "tbd",
        "todo",
        "tool",
        "true",
        "verified",
        "yes",
    }
)
LEAVE_EMPTY = (
    'confirmed holds a person\'s reply, as they gave it, such as "J. Smith: yes". Leave it '
    "empty until someone replies; with nobody to ask, run build --automatic, which uses the "
    "answer and says nobody confirmed it"
)


def not_a_persons_reply(confirmed: str) -> str:
    if confirmed.strip().rstrip(".,;:!?-").casefold() in NOT_A_PERSONS_WORDS:
        return f"confirmed: {confirmed!r} names no person who replied. {LEAVE_EMPTY}"
    return ""


class AnswerError(ValueError):
    pass


class SheetRefused(ValueError):
    pass


@dataclass(frozen=True)
class Answer:
    value: object
    provenance: str
    confirmed: str = ""

    @property
    def blank(self) -> bool:
        return self.value is None or self.value == "" or self.value == []

    @property
    def unconfirmed(self) -> bool:
        return not self.confirmed.strip()


def shape(value_key: str | None = "value", example: str = "...") -> str:
    return SHAPE.format(value=f"{value_key}: {example}, " if value_key else "")


def parse_answer(
    entry: object,
    where: str,
    *,
    value_key: str | None = "value",
    extra_keys: tuple[str, ...] = (),
    may_be_blank: bool = False,
) -> Answer:
    expected = f"{where} must be {shape(value_key)}"
    if not isinstance(entry, dict):
        raise AnswerError(f"{expected}, not {entry!r}")
    allowed = {PROVENANCE, CONFIRMED, *extra_keys, *([value_key] if value_key else [])}
    unknown = sorted(str(key) for key in entry if key not in allowed)
    if unknown == ["value"] and value_key and value_key != "value":
        raise AnswerError(f"{where}: {where.split('.')[0]} take {value_key}:, not value:")
    if unknown:
        raise AnswerError(
            f"{where}: unknown key(s) {', '.join(unknown)}; expected {', '.join(sorted(allowed))}"
        )
    answer = Answer(
        entry.get(value_key) if value_key else None,
        _text(entry.get(PROVENANCE)),
        _text(entry.get(CONFIRMED)),
    )
    if value_key and answer.blank and not may_be_blank:
        raise AnswerError(f"{where} needs a {value_key}:")
    if not answer.provenance:
        raise AnswerError(
            f"{where} needs provenance: saying what the answer rests on, such as the document and "
            "where in it, the data it was read from, or why it was chosen"
        )
    if problem := not_a_persons_reply(answer.confirmed):
        raise AnswerError(f"{where}: {problem}")
    return answer


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def unconfirmed_answers(raw: object, key: str = "") -> list[str]:
    if not isinstance(raw, dict):
        return []
    answered = _text(raw.get(PROVENANCE))
    found = [key] if answered and not _text(raw.get(CONFIRMED)) else []
    return found + [
        answer
        for name, value in raw.items()
        for answer in unconfirmed_answers(value, f"{key}.{name}" if key else str(name))
    ]


def sheet_answer(row: Mapping[str, str | None]) -> Answer:
    return Answer(None, _text(row.get(PROVENANCE)), _text(row.get(CONFIRMED)))


def refuse_machine_confirmed(
    sheet: Path, rows: list[tuple[str, Mapping[str, str | None]]]
) -> None:
    problems = [
        f"{key}: {problem}"
        for key, row in rows
        if (problem := not_a_persons_reply(_text(row.get(CONFIRMED))))
    ]
    if problems:
        raise SheetRefused(f"{sheet.as_posix()}: {'; '.join(problems[:3])}")


def refuse_unprovenanced(
    sheet: Path, rows: list[str], limit: int = 10, total: int | None = None
) -> None:
    total = len(rows) if total is None else total
    if not total:
        return
    raise SheetRefused(
        f"{sheet.as_posix()}: {total} row(s) change the proposal with nothing in the "
        f"{PROVENANCE} column: {first_few(rows, limit, total)}. Put what each change rests on in {PROVENANCE}, and "
        f"a person's reply in {CONFIRMED}, or leave {CONFIRMED} empty for a person to fill"
    )
