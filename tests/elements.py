from __future__ import annotations

from xml.etree import ElementTree as ET


def child(element: ET.Element, path: str) -> ET.Element:
    found = element.find(path)
    assert found is not None, f"no element at {path!r}"
    return found


def child_text(element: ET.Element, path: str) -> str | None:
    return child(element, path).text
