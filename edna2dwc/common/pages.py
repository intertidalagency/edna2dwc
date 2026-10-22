from __future__ import annotations

from html import escape
from pathlib import Path

from markdown_it import MarkdownIt

STYLE = """
:root { color-scheme: light dark; }
body { font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; max-width: 60rem;
       margin: 2rem auto; padding: 0 1.5rem; }
h1, h2, h3 { line-height: 1.2; margin-top: 2rem; }
table { border-collapse: collapse; width: 100%; margin: 1rem 0; font-size: 0.95em; }
th, td { border: 1px solid #8884; padding: 0.4rem 0.6rem; text-align: left;
         vertical-align: top; }
th { background: #8882; }
code { font: 0.9em ui-monospace, SFMono-Regular, Menlo, monospace; background: #8882;
       padding: 0.1em 0.3em; border-radius: 3px; }
pre { background: #8882; padding: 0.8rem 1rem; overflow-x: auto; border-radius: 4px; }
pre code { background: none; padding: 0; }
""".strip()

_renderer = MarkdownIt("commonmark", {"html": False}).enable("table")


def _table_row(cells: list[str]) -> str:
    return "| " + " | ".join(cell.replace("|", "\\|").replace("\n", " ") for cell in cells) + " |"


def table(header: list[str], rows: list[list[str]]) -> list[str]:
    return [_table_row(header), _table_row(["---"] * len(header)), *map(_table_row, rows)]


def to_html(markdown: str, *, fallback_title: str = "") -> str:
    heading = next((line[2:] for line in markdown.splitlines() if line.startswith("# ")), "")
    title = escape(heading or fallback_title)
    body = _renderer.render(markdown)
    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{title}</title>\n<style>\n{STYLE}\n</style>\n</head>\n<body>\n{body}</body>\n</html>\n"
    )


def write_page(path: Path, markdown: str) -> tuple[Path, Path]:
    html_path = path.with_suffix(".html")
    path.write_text(markdown, encoding="utf-8")
    html_path.write_text(to_html(markdown, fallback_title=path.stem), encoding="utf-8")
    return path, html_path
