from __future__ import annotations

from pathlib import Path

from edna2dwc.build.result import ACCEPTED, BUILD, DONE, NOT_REACHED, BuildResult
from edna2dwc.common import pages
from edna2dwc.conversion import artifacts, stages

STATUS_SENTENCES = {
    "ok": "Finished. The archive is built.",
    "needs_decision": (
        "Stopped at a question only you can answer. The proposals written so far are listed "
        "below too, so they can be reviewed in the same round. After the answers, the next "
        "build writes the archive, and can still wait on a validator issue to judge."
    ),
    "needs_review": "The archive is built. Some items are waiting for review.",
    "error": "Stopped on an error.",
}
BUILT_WITH_ITEMS_LEFT = "The archive is built. The items below are still to do before it ships."


def render_markdown(result: BuildResult) -> str:
    lines = ["# Review", ""]
    items = result.items
    waiting = result.waiting
    accepted = [item for item in items if item.status == ACCEPTED]
    sentence = STATUS_SENTENCES.get(result.status, result.status)
    if result.status == "ok" and (waiting or accepted):
        sentence = BUILT_WITH_ITEMS_LEFT
    lines.append(f"**{sentence}**" + (f" {result.detail}" if result.detail else ""))
    lines.append("")

    lines += ["## Where this conversion is", ""]
    current = list(stages.PURPOSES).index(result.stage)
    for index, (stage, purpose) in enumerate(stages.PURPOSES.items()):
        name = f"{stages.position(stage)} ({purpose})"
        if index < current:
            lines.append(f"- [x] {name}")
        else:
            lines.append(f"- [ ] **Now:** {name}" if index == current else f"- [ ] {name}")
    lines.append("")

    lines += ["## Waiting on you", ""]
    if waiting:
        lines += pages.table(
            ["Item", "What", "How to close it"],
            [[item.title, item.detail, item.how] for item in waiting],
        )
        lines += ["", f"When every item above is closed, run `{BUILD}`."]
    else:
        lines.append("Nothing.")
    lines.append("")

    if accepted:
        lines += ["## Accepted by --automatic, confirm", ""]
        lines += pages.table(
            ["Item", "What", "How to confirm it"],
            [[item.title, item.detail, item.how] for item in accepted],
        )
        lines.append("")

    for heading, status in (("Done", DONE), ("Not reached yet", NOT_REACHED)):
        rows = [item for item in items if item.status == status]
        if not rows:
            continue
        lines += [f"## {heading}", ""]
        lines += pages.table(["Item", "Outcome"], [[item.title, item.detail] for item in rows])
        lines.append("")
    return "\n".join(lines)


def write(result: BuildResult, directory: Path) -> tuple[Path, Path]:
    return pages.write_page(directory / artifacts.REVIEW_PAGE, render_markdown(result))
