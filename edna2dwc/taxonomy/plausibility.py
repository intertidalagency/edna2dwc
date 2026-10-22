from __future__ import annotations

KINGDOM_GROUP: dict[str, str] = {}
for _kingdom in (
    "Bacteria",
    "Archaea",
    "Monera",
    "Prokaryota",
    "Prokarya",
    "Eubacteria",
    "Archaebacteria",
):
    KINGDOM_GROUP[_kingdom.casefold()] = "prokaryote"
for _kingdom in ("Animalia", "Metazoa", "Plantae", "Viridiplantae", "Fungi"):
    KINGDOM_GROUP[_kingdom.casefold()] = "eukaryote_multicellular"
for _kingdom in (
    "Protozoa",
    "Chromista",
    "Protista",
    "Chromalveolata",
    "Rhizaria",
    "Excavata",
    "Harosa",
    "Hacrobia",
    "Alveolata",
    "Stramenopiles",
    "SAR",
    "Amoebozoa",
):
    KINGDOM_GROUP[_kingdom.casefold()] = "eukaryote_protist"
for _kingdom in ("Viruses", "Virus", "Viroids"):
    KINGDOM_GROUP[_kingdom.casefold()] = "virus"
for _kingdom in ("Eukaryota", "Eukarya"):
    KINGDOM_GROUP[_kingdom.casefold()] = "eukaryote_any"

ORGANELLE_MARKERS = {"chloroplast", "mitochondria", "mitochondrion", "plastid", "apicoplast"}

_EUKARYOTE_GROUPS = {"eukaryote_multicellular", "eukaryote_protist", "eukaryote_any"}


def kingdom_group(kingdom: str) -> str | None:
    return KINGDOM_GROUP.get((kingdom or "").strip().casefold())


def is_kingdom_uninformative(kingdom: str) -> bool:
    return kingdom_group(kingdom) == "eukaryote_any"


def kingdoms_implausible(source_kingdom: str, candidate_kingdom: str) -> bool:
    source_group = kingdom_group(source_kingdom)
    candidate_group = kingdom_group(candidate_kingdom)
    if source_group is None or candidate_group is None:
        return False
    if source_group == "eukaryote_any" or candidate_group == "eukaryote_any":
        other = candidate_group if source_group == "eukaryote_any" else source_group
        return other not in _EUKARYOTE_GROUPS
    return source_group != candidate_group


def has_organelle_marker(genus: str, family: str, order: str, class_: str) -> bool:
    fields = (genus, family, order, class_)
    return any((f or "").strip().casefold() in ORGANELLE_MARKERS for f in fields)
