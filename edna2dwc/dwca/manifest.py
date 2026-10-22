from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
import xml.etree.ElementTree as ET

PEOPLE_FIELDS = ("creators", "contacts")
MANIFEST_FIELDS = (
    "title",
    "abstract",
    "license",
    "creators",
    "contacts",
    "methods_description",
    "geographic_description",
    "pub_date",
    "bounding_box",
    "project",
)
REQUIRED_METADATA = ("title", "creators", "abstract", "license", "contacts", "pub_date")
GBIF_LICENSES = {
    "CC0-1.0": (
        "Public Domain (CC0 1.0)",
        "http://creativecommons.org/publicdomain/zero/1.0/legalcode",
    ),
    "CC-BY-4.0": (
        "Creative Commons Attribution (CC-BY) 4.0",
        "http://creativecommons.org/licenses/by/4.0/legalcode",
    ),
    "CC-BY-NC-4.0": (
        "Creative Commons Attribution Non Commercial (CC-BY-NC) 4.0",
        "http://creativecommons.org/licenses/by-nc/4.0/legalcode",
    ),
}
PUB_DATE_PATTERN = re.compile(r"\d{4}(-\d{2}-\d{2})?")
PERSON_KEYS = ("given", "surname", "organization", "email", "orcid")
BOUNDING_BOX_KEYS = ("west", "south", "east", "north")
PROJECT_KEYS = ("title", "personnel", "funding")
GIVEN_ONLY_FROM_A_SOURCE = ("project",)


def gbif_license(value: str) -> str | None:
    text = value.strip().casefold()
    for license_id, (_title, url) in GBIF_LICENSES.items():
        address = url.split("//", 1)[1].removesuffix("legalcode")
        if text == license_id.casefold() or address in text:
            return license_id
    return None


@dataclass(frozen=True)
class Person:
    given: str = ""
    surname: str = ""
    organization: str = ""
    email: str = ""
    orcid: str = ""


@dataclass(frozen=True)
class ProjectMember:
    person: Person
    role: str


@dataclass(frozen=True)
class Project:
    title: str
    personnel: tuple[ProjectMember, ...]
    funding: str = ""


@dataclass(frozen=True)
class BoundingBox:
    west: float
    south: float
    east: float
    north: float


@dataclass
class Manifest:
    values: dict[str, str] = field(default_factory=dict)
    people: dict[str, list[Person]] = field(default_factory=dict)
    bounding_box: BoundingBox | None = None
    project: Project | None = None
    provenance: dict[str, str] = field(default_factory=dict)
    confirmed: dict[str, str] = field(default_factory=dict)
    version: int = 1

    def set(self, field_name: str, value: str, *, provenance: str, confirmed: str = "") -> None:
        self._record(field_name, provenance, confirmed)
        self.values[field_name] = value

    def set_people(
        self, field_name: str, people: list[Person], *, provenance: str, confirmed: str = ""
    ) -> None:
        self._record(field_name, provenance, confirmed)
        self.people[field_name] = list(people)

    def set_bounding_box(self, box: BoundingBox, *, provenance: str, confirmed: str = "") -> None:
        self._record("bounding_box", provenance, confirmed)
        self.bounding_box = box

    def set_project(self, project: Project, *, provenance: str, confirmed: str = "") -> None:
        self._record("project", provenance, confirmed)
        self.project = project

    def leave_blank(self, field_name: str, *, provenance: str, confirmed: str = "") -> None:
        self._record(field_name, provenance, confirmed)

    def is_open(self, field_name: str) -> bool:
        return not self.is_set(field_name) and field_name not in self.provenance

    def blank_required(self) -> list[str]:
        return [name for name in REQUIRED_METADATA if not self.is_set(name)]

    def _record(self, field_name: str, provenance: str, confirmed: str) -> None:
        self.provenance[field_name] = provenance
        if confirmed:
            self.confirmed[field_name] = confirmed

    def is_set(self, field_name: str) -> bool:
        if field_name == "bounding_box":
            return self.bounding_box is not None
        if field_name == "project":
            return self.project is not None
        return bool(self.values.get(field_name) or self.people.get(field_name))

    def ask_list(self) -> list[str]:
        priority = ("title", "license", "creators", "abstract", "contacts")
        ordered = [*priority, *(f for f in MANIFEST_FIELDS if f not in priority)]
        return [f for f in ordered if f not in GIVEN_ONLY_FROM_A_SOURCE and self.is_open(f)]


_EML_TEXT_XPATHS = {
    "title": ".//{*}title",
    "abstract": ".//{*}abstract/{*}para",
    "geographic_description": ".//{*}geographicDescription",
    "pub_date": ".//{*}pubDate",
}
_EML_PEOPLE_XPATHS = {
    "creators": ".//{*}dataset/{*}creator",
    "contacts": ".//{*}dataset/{*}contact",
}
_EML_BOUNDING_COORDINATES = {
    "west": "{*}westBoundingCoordinate",
    "south": "{*}southBoundingCoordinate",
    "east": "{*}eastBoundingCoordinate",
    "north": "{*}northBoundingCoordinate",
}


def _text(element: ET.Element, xpath: str) -> str:
    found = element.find(xpath)
    return (found.text or "").strip() if found is not None else ""


def _orcid(party: ET.Element) -> str:
    for user_id in party.findall("{*}userId"):
        if "orcid" in user_id.get("directory", "").casefold():
            return (user_id.text or "").strip().rstrip("/").rsplit("/", 1)[-1]
    return ""


def _person(party: ET.Element) -> Person:
    return Person(
        given=_text(party, "{*}individualName/{*}givenName"),
        surname=_text(party, "{*}individualName/{*}surName"),
        organization=_text(party, "{*}organizationName"),
        email=_text(party, "{*}electronicMailAddress"),
        orcid=_orcid(party),
    )


def _bounding_box(root: ET.Element) -> BoundingBox | None:
    coordinates = root.find(".//{*}boundingCoordinates")
    if coordinates is None:
        return None
    try:
        return BoundingBox(
            **{
                key: float(_text(coordinates, xpath))
                for key, xpath in _EML_BOUNDING_COORDINATES.items()
            }
        )
    except ValueError:
        return None


def eml_provenance(field_name: str) -> str:
    return f"eml.xml {field_name}"


def harvest_eml(eml_path: Path) -> Manifest:
    root = ET.parse(eml_path).getroot()
    manifest = Manifest()
    for field_name, xpath in _EML_TEXT_XPATHS.items():
        if text := _text(root, xpath):
            manifest.set(field_name, text, provenance=eml_provenance(field_name))
    for field_name, xpath in _EML_PEOPLE_XPATHS.items():
        people = [_person(party) for party in root.findall(xpath)]
        if named := [person for person in people if person.surname or person.organization]:
            manifest.set_people(field_name, named, provenance=eml_provenance(field_name))
    if box := _bounding_box(root):
        manifest.set_bounding_box(box, provenance=eml_provenance("bounding_box"))
    return manifest


@dataclass
class InitScanResult:
    manifest: Manifest
    eml_paths: list[Path]


def init_scan(scan_dir: Path) -> InitScanResult:
    eml_paths = sorted(scan_dir.glob("**/eml.xml"))
    manifest = harvest_eml(eml_paths[0]) if eml_paths else Manifest()
    return InitScanResult(manifest=manifest, eml_paths=eml_paths)
