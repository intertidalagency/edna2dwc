from __future__ import annotations

from edna2dwc.dwca.manifest import PEOPLE_FIELDS, Manifest, Person

REQUIRED_TEXT_FIELDS = ("title", "abstract")


def required_manifest(text: str = "x") -> Manifest:
    m = Manifest()
    for name in REQUIRED_TEXT_FIELDS:
        m.set(name, text, provenance=f"{name}")
    m.set("license", "CC0-1.0", provenance="license")
    m.set("pub_date", "2024-01-15", provenance="pub_date")
    for name in PEOPLE_FIELDS:
        m.set_people(name, [Person(surname=text)], provenance=f"{name}")
    return m
