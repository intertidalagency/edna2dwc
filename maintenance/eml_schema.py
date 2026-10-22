from __future__ import annotations

from pathlib import Path
import re

import httpx

ENTRY_POINT = "https://rs.gbif.org/schema/eml-gbif-profile/1.2/eml.xsd"

_ABSOLUTE_URL_FILENAMES = {
    "http://www.w3.org/2001/xml.xsd": "w3-xml.xsd",
    "http://www.w3.org/2009/01/xml.xsd": "w3-xml-2009.xsd",
    "http://rs.gbif.org/schema/xml.xsd": "gbif-xml.xsd",
}


def _local_name(location: str) -> str:
    if location in _ABSOLUTE_URL_FILENAMES:
        return _ABSOLUTE_URL_FILENAMES[location]
    if location.startswith("http"):


def find_schema_locations(text: str) -> list[str]:
    return re.findall(r'schemaLocation="([^"]+)"', text)


def rewrite_schema_locations(text: str, locations: list[str]) -> str:
    for location in locations:
        text = text.replace(
            f'schemaLocation="{location}"', f'schemaLocation="{_local_name(location)}"'
        )
    return text


def fetch_schema_set(entry_point: str, client: httpx.Client) -> dict[str, str]:
    base = entry_point.rsplit("/", 1)[0] + "/"
    seen: set[str] = set()
    queue = [entry_point]
    texts: dict[str, str] = {}

    while queue:
        location = queue.pop()
        if location in seen:
            continue
        seen.add(location)
        url = location if location.startswith("http") else base + location
        response = client.get(url)
        response.raise_for_status()
        text = response.text
        referenced = find_schema_locations(text)
        queue.extend(loc for loc in referenced if loc not in seen)
        texts[_local_name(location)] = rewrite_schema_locations(text, referenced)

    return texts


def write_schema_set(texts: dict[str, str], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename, text in texts.items():
        (output_dir / filename).write_text(text, encoding="utf-8")


def main() -> None:
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        texts = fetch_schema_set(ENTRY_POINT, client)
    write_schema_set(texts, OUTPUT_DIR)
    print(f"Wrote {len(texts)} schema file(s) to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
