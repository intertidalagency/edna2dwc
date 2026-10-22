from __future__ import annotations

from dataclasses import Field, asdict, dataclass, field, fields, replace
from datetime import datetime
import json
import math
from pathlib import Path
import re
from string import Template
from typing import TYPE_CHECKING, Any, Literal, TypeVar, get_args, get_origin, get_type_hints

import yaml

import edna2dwc
from edna2dwc.conversion import artifacts
from edna2dwc.conversion.provenance import Answer, AnswerError, parse_answer, unconfirmed_answers
from edna2dwc.dwca.manifest import (
    BOUNDING_BOX_KEYS,
    GBIF_LICENSES,
    MANIFEST_FIELDS,
    PEOPLE_FIELDS,
    PERSON_KEYS,
    PROJECT_KEYS,
    PUB_DATE_PATTERN,
    REQUIRED_METADATA,
    BoundingBox,
    Manifest,
    Person,
    Project,
    ProjectMember,
    gbif_license,
)
from edna2dwc.dwca.writer import MIXS_URI_STYLES, MixsUriStyle
from edna2dwc.terms.map_terms import JOINED_FIELDS
from edna2dwc.terms.term_states import ASSAY_TYPES, AssayType

if TYPE_CHECKING:
    from _typeshed import DataclassInstance

TerminalFallback = Literal["incertae-sedis", "biota"]
Register = Literal["worms", "gbif"]
REGISTERS: tuple[Register, ...] = get_args(Register)

LOD_TERM = "pcr_primer_lod"
ANSWERS_TEMPLATE = Path(edna2dwc.__file__).parent / "templates" / "answers.yaml"
PER_RECORD_TERMS = frozenset(
    {"occurrenceID", "eventID", "materialSampleID", "taxonID", "organismID"}
)

_ORCID_RE = re.compile(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]")
_COORDINATE_LIMITS = {"west": 180, "south": 90, "east": 180, "north": 90}

CONTROL_CLASSIFICATIONS = ("control", "sample")

_EUKARYOTE_KINGDOMS = frozenset({"Animalia", "Plantae", "Fungi", "Chromista", "Protozoa"})
MARKER_TARGET_KINGDOMS = {
    "prokaryotes": frozenset({"Bacteria", "Archaea"}),
    "bacteria": frozenset({"Bacteria"}),
    "archaea": frozenset({"Archaea"}),
    "eukaryotes": _EUKARYOTE_KINGDOMS,
    "animals": frozenset({"Animalia"}),
    "vertebrates": frozenset({"Animalia"}),
    "plants": frozenset({"Plantae"}),
    "fungi": frozenset({"Fungi"}),
    "universal": _EUKARYOTE_KINGDOMS | {"Bacteria", "Archaea", "Viruses"},
}


class DatasetIdError(ValueError):
    pass


_UNCARRIABLE_IN_DATASET_ID = (
    ("\t", "tab"),
    ("\n", "newline"),
    ("\r", "carriage return"),
)


def validate_dataset_id(dataset_id: str) -> None:
    if not dataset_id.strip():
        raise DatasetIdError(
            "dataset_id is blank, so every occurrenceID would key on nothing but ':'"
        )
    if ":" in dataset_id:
        raise DatasetIdError(
            f"dataset_id contains a colon, which separates the parts of an occurrenceID"
            f": {dataset_id!r}"
        )
    for character, name in _UNCARRIABLE_IN_DATASET_ID:
        if character in dataset_id:
            raise DatasetIdError(
                f"dataset_id contains a {name}, which build collapses to a space, so the "
                f"occurrenceID shipped would not be the one recorded: {dataset_id!r}"
            )


class AnswersError(ValueError):
    pass


class AdjudicationsError(AnswersError):
    pass


ADJUDICATIONS_EXAMPLE = (
    "adjudications: {ON_LAND: {status: accepted, provenance: <why the records are right>, "
    "confirmed: <the person's reply>}}"
)


def parse_adjudications(entries: object, where: str) -> dict[str, str]:
    if entries is None:
        return {}
    if not isinstance(entries, dict):
        raise AdjudicationsError(
            f"{where}: adjudications: maps each issue class to a status, its provenance and a "
            f"person's confirmation, as {ADJUDICATIONS_EXAMPLE}, not {entries!r}"
        )
    out = {}
    for category, entry in entries.items():
        try:
            answer = parse_answer(entry, f"adjudications.{category}", value_key="status")
        except AnswerError as error:
            raise AdjudicationsError(f"{where}: {error}, as {ADJUDICATIONS_EXAMPLE}") from error
        if answer.value not in ("accepted", "rejected"):
            raise AdjudicationsError(
                f"{where}: {category!r} has status {answer.value!r}, expected accepted or rejected"
            )
        if not answer.unconfirmed:
            out[str(category)] = str(answer.value)
    return out


def target_kingdoms(answer: str) -> frozenset[str]:
    targets = [target.strip() for target in answer.split(",")]
    unknown = [target for target in targets if target.casefold() not in MARKER_TARGET_KINGDOMS]
    if unknown:
        raise ValueError(
            f"{', '.join(map(repr, unknown))} is not a marker target: answer one or more of "
            f"{', '.join(MARKER_TARGET_KINGDOMS)}"
        )
    return frozenset().union(*(MARKER_TARGET_KINGDOMS[t.casefold()] for t in targets))


def _registers(value: Any, where: str, path: Path) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(register, str) for register in value)
        or len(set(value)) != len(value)
        or not set(value) <= set(REGISTERS)
    ):
        raise AnswersError(
            f"{path}: {where} must list one or both of {', '.join(REGISTERS)}, each "
            f"once, in the order to try them, not {value!r}"
        )
    return tuple(value)


def _answered_flag(entry: Any, where: str, path: Path) -> bool | None:
    if entry is None:
        return None
    value = _answer(entry, where, path).value
    if not isinstance(value, bool):
        raise AnswersError(
            f"{path}: {where} must be null or "
            f"{{value: true or false, provenance: <why>, confirmed: <a person's reply>}}, "
            f"not {entry!r}"
        )
    return value


def _kingdoms(value: Any, where: str, path: Path) -> list[str]:
    known = {kingdom.casefold(): kingdom for kingdom in MARKER_TARGET_KINGDOMS["universal"]}
    if not isinstance(value or [], list):
        raise AnswersError(
            f"{path}: {where} must be a list of kingdoms, such as "
            f"exclude_kingdoms: [Bacteria], not {value!r}"
        )
    requested = [str(kingdom) for kingdom in value or []]
    if unknown := [kingdom for kingdom in requested if kingdom.casefold() not in known]:
        raise AnswersError(
            f"{path}: {where}: {', '.join(map(repr, unknown))} is not a "
            f"kingdom: name one or more of {', '.join(sorted(known.values()))}"
        )
    return [known[kingdom.casefold()] for kingdom in requested]


def _sample_metadata(value: Any, where: str, path: Path) -> Path | None:
    named = _text(value, where, path, "tables/samples.csv")
    if named is None:
        return None
    if not (path.parent / named).is_file():
        raise AnswersError(
            f"{path}: {where} names {named}, which is not a file under "
            f"{path.parent.resolve().as_posix()}. Give the path of the sample metadata table "
            "relative to this directory, or set it to null"
        )
    return Path(named)


def _column(example: str) -> Any:
    return field(default=None, metadata={"example": example})


def _term_reasons(value: Any, where: str, path: Path) -> dict[str, str]:
    declared = value or {}
    if not isinstance(declared, dict):
        raise AnswersError(
            f"{path}: {where} must map each term to a reason, not a {type(declared).__name__}"
        )
    return {
        str(term): _answer(entry, f"{where}.{term}", path, value_key=None).provenance
        for term, entry in declared.items()
    }


@dataclass(frozen=True)
class TaxonomySettings:
    registers: tuple[str, ...] = field(default=REGISTERS, metadata={"parse": _registers})
    marine_only: bool = False
    require_confident: bool = True
    refresh_labels: bool = False
    terminal_fallback: TerminalFallback = "incertae-sedis"

    def describe(self) -> str:
        return "; ".join(
            f"{setting.name}: {_describe_setting(getattr(self, setting.name))}"
            for setting in fields(self)
        )


def _describe_setting(value: object) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, tuple):
        return ", ".join(value)
    return str(value)


@dataclass(frozen=True)
class MarkerTarget:
    target: str
    provenance: str
    constants: dict[str, tuple[str, str]] = field(default_factory=dict)
    taxonomy: TaxonomySettings | None = None
    exclude_taxa: tuple[str, ...] = ()


@dataclass(frozen=True)
class Filters:
    exclude_human: bool | None = field(default=None, metadata={"parse": _answered_flag})
    exclude_kingdoms: list[str] = field(default_factory=list, metadata={"parse": _kingdoms})
    sample_metadata: Path | None = field(default=None, metadata={"parse": _sample_metadata})
    sample_type_col: str | None = _column("sample_type")
    occurrence_type_col: str | None = _column("sample_type")


@dataclass(frozen=True)
class DeriveFields:
    timestamp_col_a: str | None = _column("collection_date")
    timestamp_col_b: str | None = _column("event_date")
    emit_absences: bool = False


@dataclass(frozen=True)
class TermStates:
    assay_type: AssayType = "metabarcoding"
    not_applicable: dict[str, str] = field(default_factory=dict, metadata={"parse": _term_reasons})
    ask: dict[str, str] = field(default_factory=dict, metadata={"parse": _term_reasons})
    impossible: dict[str, str] = field(default_factory=dict, metadata={"parse": _term_reasons})


@dataclass(frozen=True)
class BuildOptions:
    no_dna_extension: bool = False
    no_emof: bool = False
    mixs_uri_style: MixsUriStyle = "gensc"


@dataclass
class Answers:
    dataset_id: str
    created: str
    out_dir: Path
    metadata: Manifest
    markers: dict[str, MarkerTarget]
    controls: dict[str, str]
    constants: dict[str, tuple[str, str]]
    units: dict[str, tuple[str, str]]
    taxonomy: TaxonomySettings
    filters: Filters
    derive_fields: DeriveFields
    term_states: TermStates
    adjudications: dict[str, str]
    build: BuildOptions
    unconfirmed: list[str]

    def blank_metadata(self) -> list[str]:
        return [name for name in REQUIRED_METADATA if self.metadata.is_open(name)]

    def marker_targets(self, table_markers: set[str]) -> dict[str, MarkerTarget]:
        if table_markers == {""} and len(self.markers) == 1:
            return {"": next(iter(self.markers.values()))}
        return {marker: self.markers[marker] for marker in table_markers if marker in self.markers}

    def taxonomy_scopes(self, table_markers: set[str]) -> dict[str, str]:
        return {
            marker: name
            for marker, target in self.marker_targets(table_markers).items()
            for name, entry in self.markers.items()
            if entry is target and target.taxonomy is not None
        }

    def taxonomy_for(self, scope: str) -> TaxonomySettings:
        marker_settings = self.markers[scope].taxonomy if scope else None
        return marker_settings or self.taxonomy

    def referenced_inputs(self) -> list[Path]:
        sample_metadata = self.filters.sample_metadata
        return [sample_metadata] if sample_metadata is not None else []


_SECTIONS = {section.name for section in fields(Answers)} - {"unconfirmed"}

WORKING_DIRS = (artifacts.PROPOSED_DIR, artifacts.CONFIRMED_DIR)


def _check_out_dir(out_dir: Path, path: Path) -> None:
    root = path.parent.resolve()
    resolved = (root / out_dir).resolve()
    if out_dir.is_absolute() or ".." in out_dir.parts or not resolved.is_relative_to(root):
        raise AnswersError(
            f"{path}: out_dir {str(out_dir)!r} must be a relative path to a directory inside the "
            "conversion directory, such as archive, with no .. and no symbolic link out of it. "
            "build empties it every time"
        )
    within = resolved.relative_to(root).parts
    if not within or within[0].casefold() in {name.as_posix() for name in WORKING_DIRS}:
        raise AnswersError(
            f"{path}: out_dir {str(out_dir)!r} must be a directory of its own, such as archive. "
            "build empties it every time, so it can't be the conversion directory or be in "
            f"{' or '.join(name.as_posix() for name in WORKING_DIRS)}"
        )


Settings = TypeVar("Settings", bound="DataclassInstance")


def _section(raw: dict, name: str, path: Path) -> dict:
    section = raw.get(name) or {}
    if not isinstance(section, dict):
        raise AnswersError(f"{path}: {name}: must be a mapping, not a {type(section).__name__}")
    return section


def _section_settings(raw: dict, name: str, defaults: Settings, path: Path) -> Settings:
    return _settings(_section(raw, name, path), name, defaults, path)


def _settings(section: dict, where: str, defaults: Settings, path: Path) -> Settings:
    settings = fields(defaults)
    _reject_unknown(section, {setting.name for setting in settings}, f"{where}.", path)
    kinds = get_type_hints(type(defaults))
    given = {
        setting.name: _setting(
            section[setting.name], setting, kinds[setting.name], f"{where}.{setting.name}", path
        )
        for setting in settings
        if setting.name in section
    }
    return replace(defaults, **given)


def _setting(value: object, setting: Field, kind: object, where: str, path: Path) -> object:
    if parse := setting.metadata.get("parse"):
        return parse(value, where, path)
    if example := setting.metadata.get("example"):
        return _text(value, where, path, example)
    if isinstance(value, dict):
        raise AnswersError(
            f"{path}: {where} {SETTING_NOT_ANSWER}, such as "
            f"{setting.name}: {_describe_setting(setting.default)}"
        )
    if kind is bool and not isinstance(value, bool):
        raise AnswersError(f"{path}: {where} must be true or false, not {value!r}")
    if get_origin(kind) is Literal and value not in get_args(kind):
        raise AnswersError(
            f"{path}: {where} must be one of {', '.join(get_args(kind))}, not {value!r}"
        )
    return value


def _reject_unknown(mapping: dict, allowed: set[str], prefix: str, path: Path) -> None:
    unknown = sorted(str(key) for key in mapping if key not in allowed)
    if unknown:
        cut_at_a_comma = (
            ". A key with a space is often a value cut at a comma: put a value that holds a "
            'comma in quotes, such as organization: "Fisheries Dept, Marine Bureau"'
            if any(" " in key for key in unknown)
            else ""
        )
        raise AnswersError(
            f"{path}: unknown key(s) {', '.join(prefix + key for key in unknown)}; "
            f"expected one of {', '.join(sorted(allowed))}{cut_at_a_comma}"
        )


SETTING_NOT_ANSWER = (
    "is a setting, not an answer, so it takes a plain value rather than "
    "{value, provenance, confirmed}"
)


def _text(value: object, where: str, path: Path, example: str) -> str | None:
    if value is None or value == "":
        return None
    name = where.rsplit(".", 1)[-1]
    if isinstance(value, dict):
        raise AnswersError(f"{path}: {where} {SETTING_NOT_ANSWER}, such as {name}: {example}")
    if not isinstance(value, str):
        raise AnswersError(
            f"{path}: {where} must be text, such as {name}: {example}, not {value!r}"
        )
    return value


def _people(value: object, name: str, path: Path) -> list[Person]:
    if not isinstance(value, list):
        raise AnswersError(
            f"{path}: metadata.{name}.value must be a list of people, each a mapping of "
            f"{', '.join(PERSON_KEYS)}, not {value!r}"
        )
    return [
        _person(entry, f"metadata.{name}.value[{index}]", path)
        for index, entry in enumerate(value)
    ]


def _person(entry: object, where: str, path: Path, *, extra_keys: tuple[str, ...] = ()) -> Person:
    keys = (*PERSON_KEYS, *extra_keys)
    if not isinstance(entry, dict):
        raise AnswersError(f"{path}: {where} must be a mapping of {', '.join(keys)}")
    _reject_unknown(entry, set(keys), f"{where}.", path)
    person = Person(**{key: str(entry.get(key) or "").strip() for key in PERSON_KEYS})
    if not (person.surname or person.organization):
        raise AnswersError(f"{path}: {where} needs a surname or an organization")
    if person.orcid and not _ORCID_RE.fullmatch(person.orcid):
        raise AnswersError(
            f"{path}: {where}.orcid must be the bare identifier, such as "
            f"0000-0002-1825-0097, not {person.orcid!r}"
        )
    return person


def _project(value: object, path: Path) -> Project:
    where = "metadata.project.value"
    if not isinstance(value, dict):
        raise AnswersError(f"{path}: {where} must be a mapping of {', '.join(PROJECT_KEYS)}")
    _reject_unknown(value, set(PROJECT_KEYS), f"{where}.", path)
    title = str(value.get("title") or "").strip()
    personnel = value.get("personnel") or []
    if not title or not isinstance(personnel, list) or not personnel:
        raise AnswersError(
            f"{path}: {where} needs a title and at least one person under personnel, each "
            "with a role, as written in the source. Leave project out if the source names "
            "no project, even when it names funding: the GBIF EML profile writes funding only "
            "inside a project"
        )
    members = []
    for index, entry in enumerate(personnel):
        where_person = f"{where}.personnel[{index}]"
        person = _person(entry, where_person, path, extra_keys=("role",))
        role = str(entry.get("role") or "").strip()
        if not role:
            raise AnswersError(
                f"{path}: {where_person} needs a role, such as principalInvestigator"
            )
        members.append(ProjectMember(person, role))
    return Project(title, tuple(members), str(value.get("funding") or "").strip())


def _bounding_box(value: object, path: Path) -> BoundingBox:
    shape = f"a mapping of {', '.join(BOUNDING_BOX_KEYS)} in decimal degrees"
    if not isinstance(value, dict):
        raise AnswersError(f"{path}: metadata.bounding_box.value must be {shape}, not {value!r}")
    _reject_unknown(value, set(BOUNDING_BOX_KEYS), "metadata.bounding_box.value.", path)
    for key, limit in _COORDINATE_LIMITS.items():
        coordinate = value.get(key)
        if (
            isinstance(coordinate, bool)
            or not isinstance(coordinate, int | float)
            or not math.isfinite(coordinate)
            or abs(coordinate) > limit
        ):
            raise AnswersError(
                f"{path}: metadata.bounding_box.value.{key} must be a number of decimal degrees "
                f"from -{limit} to {limit}, not {coordinate!r}"
            )
    box = BoundingBox(**{key: value[key] for key in BOUNDING_BOX_KEYS})
    if box.south > box.north:
        raise AnswersError(
            f"{path}: metadata.bounding_box.value.south ({box.south}) is north of "
            f"north ({box.north}); are they swapped?"
        )
    return box


def _answer(entry: object, where: str, path: Path, **shape) -> Answer:
    try:
        return parse_answer(entry, where, **shape)
    except AnswerError as error:
        raise AnswersError(f"{path}: {error}") from error


def _unanswered(entry: object) -> bool:
    return entry is None or (
        isinstance(entry, dict) and not any(str(value or "").strip() for value in entry.values())
    )


def _metadata(raw: dict, path: Path) -> Manifest:
    section = _section(raw, "metadata", path)
    _reject_unknown(section, {*MANIFEST_FIELDS, "version"}, "metadata.", path)
    metadata = Manifest(version=_version(section.get("version", 1), path))
    for name, entry in section.items():
        if name == "version" or _unanswered(entry):
            continue
        answer = _answer(entry, f"metadata.{name}", path, may_be_blank=True)
        value = answer.value
        where = {"provenance": answer.provenance, "confirmed": answer.confirmed}
        if answer.blank:
            metadata.leave_blank(name, **where)
            continue
        _check_decided_at_publication(name, str(value), path)
        if name in PEOPLE_FIELDS:
            metadata.set_people(name, _people(value, name, path), **where)
        elif name == "bounding_box":
            metadata.set_bounding_box(_bounding_box(value, path), **where)
        elif name == "project":
            metadata.set_project(_project(value, path), **where)
        else:
            metadata.set(name, str(value), **where)
    return metadata


def _version(value: object, path: Path) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise AnswersError(
            f"{path}: metadata.version must be a whole number from 1, raised by one each time "
            f"a corrected archive is republished, not {value!r}"
        )
    return value


def _check_decided_at_publication(name: str, value: str, path: Path) -> None:
    if name == "license" and gbif_license(value) is None:
        raise AnswersError(
            f"{path}: metadata.license must be one of the licenses GBIF accepts, "
            f"{', '.join(GBIF_LICENSES)}, not {value!r}. If the rights holder hasn't chosen "
            "one, leave the value blank and say so in provenance:"
        )
    if name == "pub_date" and not PUB_DATE_PATTERN.fullmatch(value):
        raise AnswersError(
            f"{path}: metadata.pub_date must be YYYY or YYYY-MM-DD, not {value!r}. If it "
            "isn't decided yet, leave the value blank and say so in provenance:"
        )


def _taxonomy(
    section: object, where: str, path: Path, inherited: TaxonomySettings
) -> TaxonomySettings:
    if not isinstance(section, dict):
        raise AnswersError(f"{path}: {where}: must be a mapping, not {section!r}")
    return _settings(section, where, inherited, path)


def _markers(raw: dict, path: Path, taxonomy: TaxonomySettings) -> dict[str, MarkerTarget]:
    section = raw.get("markers") or {}
    if not isinstance(section, dict):
        raise AnswersError(
            f"{path}: markers: must map each marker to {{target: ..., provenance: ..., confirmed: ...}}"
        )
    markers = {}
    for marker, entry in section.items():
        answer = _answer(
            entry,
            f"markers.{marker}",
            path,
            value_key="target",
            extra_keys=("constants", "taxonomy", "exclude_taxa"),
        )
        target = str(answer.value)
        try:
            target_kingdoms(target)
        except ValueError as error:
            raise AnswersError(f"{path}: markers.{marker}: {error}") from error
        constants = _constant_specs(entry.get("constants"), f"markers.{marker}.constants", path)
        marker_taxonomy = (
            _taxonomy(entry["taxonomy"], f"markers.{marker}.taxonomy", path, taxonomy)
            if entry.get("taxonomy")
            else None
        )
        markers[str(marker)] = MarkerTarget(
            target,
            answer.provenance,
            constants,
            marker_taxonomy,
            _excluded_taxa(entry.get("exclude_taxa"), f"markers.{marker}.exclude_taxa", path),
        )
    return markers


def _excluded_taxa(entry: object, where: str, path: Path) -> tuple[str, ...]:
    if entry is None:
        return ()
    names = _answer(entry, where, path).value
    if not isinstance(names, list) or not all(isinstance(n, str) and n.strip() for n in names):
        raise AnswersError(f"{path}: {where}.value must be a list of taxon names")
    return tuple(name.strip() for name in names)


def _controls(raw: dict, path: Path) -> dict[str, str]:
    section = raw.get("controls") or {}
    if not isinstance(section, dict):
        raise AnswersError(
            f"{path}: controls: must map each sampleID to {{value: control or sample, "
            "provenance: ..., confirmed: ...}}"
        )
    controls = {}
    for sample_id, entry in section.items():
        value = _answer(entry, f"controls.{sample_id}", path).value
        if value not in CONTROL_CLASSIFICATIONS:
            raise AnswersError(
                f"{path}: controls.{sample_id}.value must be one of "
                f"{', '.join(CONTROL_CLASSIFICATIONS)}, not {value!r}"
            )
        controls[str(sample_id)] = str(value)
    return controls


def _units(raw: dict, path: Path) -> dict[str, tuple[str, str]]:
    section = raw.get("units") or {}
    if not isinstance(section, dict):
        raise AnswersError(
            f"{path}: units: must map each column to {{value: <unit>, provenance: ..., confirmed: ...}}"
        )
    units = {}
    for column, entry in section.items():
        answer = _answer(entry, f"units.{column}", path)
        units[str(column)] = (str(answer.value), answer.provenance)
    return units


def _constant_specs(declared, label: str, path: Path) -> dict[str, tuple[str, str]]:
    declared = declared or {}
    if not isinstance(declared, dict):
        raise AnswersError(
            f"{path}: {label}: must map each term to {{value: ..., provenance: ..., "
            f"confirmed: ...}}, not a {type(declared).__name__}"
        )
    constants: dict[str, tuple[str, str]] = {}
    for term, spec in declared.items():
        if term in PER_RECORD_TERMS:
            raise AnswersError(
                f"{path}: {label}.{term} identifies one record, event, sample or sequence, so "
                "one value for every row would be wrong. Put the column that distinguishes "
                "them in the intermediate table under that name, or leave the term blank"
            )
        if term in JOINED_FIELDS:
            raise AnswersError(
                f"{path}: {label}.{term} would overwrite a term the taxonomy join writes from "
                f"{artifacts.RESOLVED_TAXONOMY}, even on rows no register resolved. To change a "
                f"taxon, put its row in {artifacts.CONFIRMED_DIR.as_posix()}/taxa.tsv with "
                "its provenance and confirmed columns filled"
            )
        answer = _answer(spec, f"{label}.{term}", path)
        constants[term] = (str(answer.value), answer.provenance)
    return constants


def _check_constants_not_given_twice(
    constants: dict[str, tuple[str, str]], markers: dict[str, MarkerTarget], path: Path
) -> None:
    for marker, target in markers.items():
        twice = sorted(constants.keys() & target.constants.keys())
        if twice:
            raise AnswersError(
                f"{path}: {', '.join(twice)} is under both constants: and "
                f"markers.{marker}.constants:. Give each term in one place"
            )


def _harvested_value(harvested: Manifest, name: str) -> object:
    if name in PEOPLE_FIELDS:
        return [
            {key: value for key, value in asdict(person).items() if value}
            for person in harvested.people.get(name, [])
        ]
    if name == "bounding_box":
        return asdict(harvested.bounding_box) if harvested.bounding_box else None
    return harvested.values.get(name, "")


def _metadata_answer(harvested: Manifest, name: str) -> str:
    value = json.dumps(_harvested_value(harvested, name))
    provenance = json.dumps(harvested.provenance.get(name, ""))
    return f'  {name}: {{value: {value}, provenance: {provenance}, confirmed: ""}}'


class _TupleOnOneLineDumper(yaml.SafeDumper):
    pass


_TupleOnOneLineDumper.add_representer(
    tuple,
    lambda dumper, items: dumper.represent_sequence(
        "tag:yaml.org,2002:seq", items, flow_style=True
    ),
)


def _section_defaults(name: str, defaults: DataclassInstance) -> str:
    return yaml.dump(
        {name: asdict(defaults)}, Dumper=_TupleOnOneLineDumper, sort_keys=False
    ).rstrip()


def skeleton(*, dataset_id: str, created: str, out_dir: Path, harvested: Manifest) -> str:
    return Template(ANSWERS_TEMPLATE.read_text(encoding="utf-8")).substitute(
        dataset_id=json.dumps(dataset_id),
        created=json.dumps(created),
        out_dir=json.dumps(str(out_dir)),
        licenses=", ".join(GBIF_LICENSES),
        metadata_answers="\n".join(_metadata_answer(harvested, name) for name in MANIFEST_FIELDS),
        marker_targets=", ".join(MARKER_TARGET_KINGDOMS),
        assay_types=" or ".join(ASSAY_TYPES),
        mixs_uri_styles=" or ".join(MIXS_URI_STYLES),
        taxonomy=_section_defaults("taxonomy", TaxonomySettings()),
        filters=_section_defaults("filters", Filters()),
        derive_fields=_section_defaults("derive_fields", DeriveFields()),
        term_states=_section_defaults("term_states", TermStates()),
        build=_section_defaults("build", BuildOptions()),
    )


def _read(path: Path) -> dict:
    if not path.exists():
        raise AnswersError(f"{path} does not exist. Run `edna2dwc init` to write it")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as error:
        raise AnswersError(f"{path}: is not readable as YAML: {error}") from error
    if not isinstance(raw, dict):
        raise AnswersError(f"{path}: must be a YAML mapping, not a {type(raw).__name__}")
    return raw


def declared(path: Path, key: str) -> Any:
    return _read(path).get(key)


def declared_out_dir(path: Path) -> Path | None:
    try:
        out_dir = Path(str(_read(path).get("out_dir") or ""))
        _check_out_dir(out_dir, path)
    except AnswersError:
        return None
    return out_dir


def load(path: Path) -> Answers:
    raw = _read(path)
    _reject_unknown(raw, _SECTIONS, "", path)
    missing = [name for name in ("dataset_id", "created", "out_dir") if not raw.get(name)]
    if missing:
        raise AnswersError(f"{path}: missing required field(s): {', '.join(missing)}")
    if not isinstance(raw["dataset_id"], str):
        raise AnswersError(f"{path}: dataset_id must be a string; got {raw['dataset_id']!r}")
    out_dir = _text(raw["out_dir"], "out_dir", path, "archive")
    if out_dir is None:
        raise AnswersError(f"{path}: out_dir must name a directory, such as out_dir: archive")
    try:
        validate_dataset_id(raw["dataset_id"])
    except DatasetIdError as error:
        raise AnswersError(f"{path}: {error}") from error
    try:
        datetime.fromisoformat(str(raw["created"]))
    except ValueError as error:
        raise AnswersError(
            f"{path}: created must be an ISO 8601 datetime; got {raw['created']!r}"
        ) from error
    _check_out_dir(Path(out_dir), path)

    taxonomy = _taxonomy(raw.get("taxonomy") or {}, "taxonomy", path, TaxonomySettings())
    filters = _section_settings(raw, "filters", Filters(), path)
    derive_fields = _section_settings(raw, "derive_fields", DeriveFields(), path)
    term_states = _section_settings(raw, "term_states", TermStates(), path)
    build = _section_settings(raw, "build", BuildOptions(), path)

    constants = _constant_specs(raw.get("constants"), "constants", path)
    markers = _markers(raw, path, taxonomy)
    _check_constants_not_given_twice(constants, markers, path)
    if derive_fields.emit_absences and term_states.assay_type != "targeted_assay":
        raise AnswersError(
            f"{path}: derive_fields.emit_absences needs term_states.assay_type: "
            f"targeted_assay, not {term_states.assay_type!r}. A zero read count in metabarcoding "
            "is not evidence of absence"
        )
    if derive_fields.emit_absences and LOD_TERM not in constants:
        raise AnswersError(
            f"{path}: derive_fields.emit_absences needs the assay's limit of detection "
            f"recorded as constants.{LOD_TERM}, with its provenance"
        )
    if filters.sample_type_col and not filters.sample_metadata:
        raise AnswersError(
            f"{path}: filters.sample_type_col names a column of the sample metadata file, "
            "so it needs filters.sample_metadata, the file it is a column of"
        )
    if filters.sample_metadata and not filters.sample_type_col:
        raise AnswersError(
            f"{path}: filters.sample_metadata is read only for its type column, "
            "so it needs filters.sample_type_col, the column that gives each sample's type"
        )
    return Answers(
        dataset_id=raw["dataset_id"],
        created=str(raw["created"]),
        out_dir=Path(out_dir),
        metadata=_metadata(raw, path),
        markers=markers,
        controls=_controls(raw, path),
        constants=constants,
        units=_units(raw, path),
        taxonomy=taxonomy,
        filters=filters,
        derive_fields=derive_fields,
        term_states=term_states,
        adjudications=parse_adjudications(raw.get("adjudications"), str(path)),
        build=build,
        unconfirmed=unconfirmed_answers(raw),
    )
