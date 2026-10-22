from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
import re

from edna2dwc.common.findings import Finding, FindingsLog, new_finding
from edna2dwc.common.table import (
    ROW,
    Table,
    column,
    from_rows,
    internal,
    is_json_object,
    literal,
    literals,
    lookup,
    matching,
)
from edna2dwc.conversion.intermediate import RESERVED_COLUMNS
from edna2dwc.terms.dynamic_properties import DynamicProperties, value_column

DYNAMIC_PROPERTIES_COLUMN = "dynamicProperties"
EMOF_TARGET = "extendedmeasurementorfact"
NUMERIC_SELECTION_THRESHOLD = 0.95
KEY = internal("key")
TEXT = internal("text")
POSITION = internal("position")
INDEX = internal("index")
OCCURRENCE = internal("occurrenceID")

_NO_VALUE = literals(["na", "n/a", "nan", "null"])
_VALUE_WITH_UNIT = literal(r"^\s*(?P<number>-?\d+(?:\.\d+)?)\s*(?P<unit>[A-Za-z%°µμ/]*)\s*$")
_HEADER_UNIT_SPLIT_RE = re.compile(
    r"^(?P<base>.+?)\s*(?:_(?P<us1>[A-Za-z%/]+)|\((?P<us2>[^)]+)\))\s*$"
)


@dataclass(frozen=True)
class MeasurementAlias:
    patterns: tuple[str, ...]
    measurement_type: str
    measurement_type_id: str = ""


@dataclass(frozen=True)
class Unit:
    name: str
    spellings: tuple[str, ...]
    unit_id: str = ""


_P01 = "http://vocab.nerc.ac.uk/collection/P01/current/{}/"
_P06 = "http://vocab.nerc.ac.uk/collection/P06/current/{}/"

ALIAS_TABLE: tuple[MeasurementAlias, ...] = (
    MeasurementAlias(("temp", "temperature"), "temperature", _P01.format("TEMPPR01")),
    MeasurementAlias(("sal", "salinity"), "salinity", _P01.format("PSALPR01")),
    MeasurementAlias(
        ("do", "dissolved_oxygen", "oxygen"), "dissolved oxygen", _P01.format("DOXYZZXX")
    ),
    MeasurementAlias(("ph",), "pH", _P01.format("PHXXZZXX")),
    MeasurementAlias(("pressure",), "pressure"),
    MeasurementAlias(("oxygen_saturation", "o2sat"), "oxygen saturation"),
    MeasurementAlias(("chl", "chlorophyll"), "chlorophyll-a"),
    MeasurementAlias(("phaeo", "phaeopigment"), "phaeopigments"),
    MeasurementAlias(("turbidity", "ntu"), "turbidity"),
    MeasurementAlias(("nitrate", "no3"), "nitrate"),
    MeasurementAlias(("nitrite", "no2"), "nitrite"),
    MeasurementAlias(("ammonium", "nh4"), "ammonium"),
    MeasurementAlias(("phosphate", "po4"), "phosphate"),
    MeasurementAlias(("silicate", "sio4"), "silicate"),
    MeasurementAlias(("total_nitrogen", "tn"), "total nitrogen"),
    MeasurementAlias(("total_phosphorus", "tp"), "total phosphorus"),
    MeasurementAlias(("dic",), "dissolved inorganic carbon"),
    MeasurementAlias(("doc",), "dissolved organic carbon"),
    MeasurementAlias(("alkalinity", "talk"), "alkalinity"),
    MeasurementAlias(("pco2",), "pCO2"),
    MeasurementAlias(("filtered_volume", "vol_filtered"), "filtered volume"),
    MeasurementAlias(("filter_pore_size", "pore_size"), "filter pore size"),
    MeasurementAlias(("flow_rate",), "flow rate"),
    MeasurementAlias(("tow_distance",), "tow distance"),
    MeasurementAlias(("tow_duration",), "tow duration"),
    MeasurementAlias(("sampling_depth",), "sampling depth"),
    MeasurementAlias(("secchi", "secchi_depth"), "secchi depth"),
    MeasurementAlias(("wind_speed",), "wind speed"),
    MeasurementAlias(("sea_state",), "sea state"),
)

UNITS: tuple[Unit, ...] = (
    Unit("degrees Celsius", ("c", "degc", "deg c", "°c", "celsius"), _P06.format("UPAA")),
    Unit("degrees Fahrenheit", ("f", "degf", "deg f", "°f", "fahrenheit")),
    Unit("PSU", ("psu",), _P06.format("UUUU")),
    Unit("ppt", ("ppt",)),
    Unit("mg/L", ("mg/l", "mgl"), _P06.format("UMGL")),
    Unit("ug/L", ("ug/l", "µg/l", "ugl")),
    Unit("umol", ("umol", "µmol")),
    Unit("umol/L", ("umol/l", "µmol/l")),
    Unit("umol/kg", ("umol/kg", "µmol/kg")),
    Unit("uatm", ("uatm", "µatm")),
    Unit("dbar", ("dbar",)),
    Unit("%", ("%", "pct", "percent")),
    Unit("NTU", ("ntu",)),
    Unit("m", ("m", "meters", "metres")),
    Unit("cm", ("cm",)),
    Unit("mm", ("mm",)),
    Unit("km", ("km",)),
    Unit("ft", ("ft", "feet")),
    Unit("fathoms", ("fathom", "fathoms", "fm")),
    Unit("mL", ("ml",)),
    Unit("L", ("l",)),
    Unit("s", ("s", "sec", "seconds")),
    Unit("min", ("minutes",)),
    Unit("h", ("h", "hr", "hours")),
    Unit("m/s", ("m/s", "mps")),
)
_SINGLE_LETTER_SYMBOLS = frozenset("CFmLlsh")


def _normalize_for_matching(name: str) -> str:
    return name.strip().lower().replace(" ", "_")


def _alias_named(name: str) -> MeasurementAlias | None:
    normalized = _normalize_for_matching(name)
    return next((alias for alias in ALIAS_TABLE if normalized in alias.patterns), None)


def alias_for(header: str) -> MeasurementAlias | None:
    base, _ = split_header_unit(header)
    return _alias_named(header) or (_alias_named(base) if header_unit(header) else None)


def split_header_unit(header: str) -> tuple[str, str | None]:
    match = _HEADER_UNIT_SPLIT_RE.match(header)
    if not match:
        return header, None
    return match.group("base"), match.group("us1") or match.group("us2")


def _spelling(token: str) -> str:
    return " ".join(token.split()).lower()


def unit_for(token: str) -> Unit | None:
    return next((unit for unit in UNITS if _spelling(token) in unit.spellings), None)


def value_unit(token: str) -> Unit | None:
    if len(token) == 1 and token not in _SINGLE_LETTER_SYMBOLS:
        return None
    return unit_for(token)


def _number_with_known_unit() -> str:
    words = sorted(
        {s for unit in UNITS for s in unit.spellings if len(s) > 1 and " " not in s},
        key=len,
        reverse=True,
    )
    letters = "|".join(sorted(_SINGLE_LETTER_SYMBOLS))
    known = f"{letters}|(?i:{'|'.join(map(re.escape, words))})"
    return literal(rf"^\s*-?\d+(?:\.\d+)?\s*(?:{known})?\s*$")


_NUMBER_WITH_KNOWN_UNIT = _number_with_known_unit()


def given_unit(name: str) -> Unit:
    named = next((unit for unit in UNITS if _spelling(name) == unit.name.lower()), None)
    return unit_for(name) or named or Unit(name, ())


def header_unit(header: str) -> Unit | None:
    _, token = split_header_unit(header)
    return unit_for(token) if token else None


def _present(value: str) -> str:
    return f"({value} <> '' AND lower(trim({value})) NOT IN {_NO_VALUE})"


def _counts(value: str) -> str:
    return (
        f"count(*) FILTER (WHERE {_present(value)}), "
        f"count(*) FILTER (WHERE {_present(value)} AND regexp_matches({value}, {_NUMBER_WITH_KNOWN_UNIT}))"
    )


def _looks_measured(key: str, non_empty: int, numeric: int) -> bool:
    if key in RESERVED_COLUMNS:
        return False
    mostly_numeric = non_empty and numeric / non_empty >= NUMERIC_SELECTION_THRESHOLD
    return alias_for(key) is not None or bool(mostly_numeric)


def _measured(counts: list[tuple[str, int, int]]) -> dict[str, MeasurementAlias | None]:
    return {key: alias_for(key) for key, *found in counts if _looks_measured(key, *found)}


def measurement_columns(table: Table, columns: list[str]) -> dict[str, MeasurementAlias | None]:
    if not columns:
        return {}
    found = table.one(
        f"SELECT {', '.join(_counts(table.text(name)) for name in columns)} FROM {table.name}"
    )
    return _measured([(name, *found[2 * i : 2 * i + 2]) for i, name in enumerate(columns)])


@dataclass(frozen=True)
class DynamicEntries:
    table: Table
    malformed: FindingsLog

    def _key_counts(self) -> list[tuple[str, int, int]]:
        return self.table.rows(
            f"SELECT {KEY}, {_counts(TEXT)} FROM {self.table.name} GROUP BY {KEY} "
            f"ORDER BY min({ROW}), arg_min({POSITION}, {ROW})"
        )

    def keys_that_look_measured(self) -> list[str]:
        return list(_measured(self._key_counts()))

    def measurement_keys(self, measured: Collection[str]) -> dict[str, MeasurementAlias | None]:
        return {key: alias_for(key) for key, *_ in self._key_counts() if key in measured}


def dynamic_entries(table: Table, dynamic: DynamicProperties) -> DynamicEntries:
    blob = dynamic.blob
    malformed = FindingsLog()
    for raw, rows in table.rows(
        f"SELECT {blob}, count(*) FROM {table.name} "
        f"WHERE {blob} <> '' AND NOT {is_json_object(blob)} GROUP BY 1 ORDER BY min({ROW})"
    ):
        malformed.add(
            "DYNAMIC_PROPERTIES_MALFORMED",
            f"dynamicProperties value {raw!r} is not a JSON object with one value per key; ignored",
            count=rows,
        )
    occurrence = f"{table.text('occurrenceID')} AS {OCCURRENCE}"
    properties = f"""json_transform({blob}, '"MAP(VARCHAR, JSON)"')"""
    from_blob = (
        f"SELECT {ROW}, {OCCURRENCE}, entry.key AS {KEY}, "
        f"coalesce(entry.value ->> '$', '') AS {TEXT}, {POSITION} "
        f"FROM (SELECT {ROW}, {OCCURRENCE}, overridden, unnest(map_entries(properties)) AS entry, "
        f"unnest(range(-cardinality(properties)::BIGINT, 0)) AS {POSITION} "
        f"FROM (SELECT {ROW}, {occurrence}, {properties} AS properties, "
        f"{dynamic.keys_set_on_the_row()} AS overridden "
        f"FROM {table.name} WHERE {is_json_object(blob)})) "
        "WHERE NOT list_contains(overridden, entry.key)"
    )
    selects = [from_blob]
    if dynamic.columns:
        names = ", ".join(map(literal, dynamic.columns))
        values = ", ".join(value_column(i) for i in range(len(dynamic.columns)))
        selects.append(
            f"SELECT * FROM (SELECT {ROW}, {occurrence}, unnest([{names}]) AS {KEY}, "
            f"unnest([{values}]) AS {TEXT}, "
            f"unnest(range({len(dynamic.columns)})) AS {POSITION} FROM {table.name}) "
            f"WHERE {TEXT} <> ''"
        )
    entries = table.view("dynamic_entries", " UNION ALL ".join(selects))
    return DynamicEntries(entries, malformed)


EMOF_HEADER = (
    "occurrenceID",
    "measurementType",
    "measurementValue",
    "measurementUnit",
    "measurementTypeID",
    "measurementUnitID",
    "measurementValueID",
)
_DESCRIBED = ("measurementType", "measurementUnit", "measurementTypeID", "measurementUnitID")
UNITLESS = internal("unitless")
NUMBER_ONLY = internal("number_only")
OVERRIDDEN = internal("overridden")
STATED = internal("stated")


def _shape(text: str) -> list[str]:
    return [
        f"regexp_matches({text}, {_VALUE_WITH_UNIT})::VARCHAR",
        f"regexp_extract({text}, {_VALUE_WITH_UNIT}, 2)",
    ]


def build_emof(
    entries: Table,
    selected: dict[str, MeasurementAlias | None],
    *,
    units: dict[str, tuple[str, str]] | None = None,
) -> tuple[Table, FindingsLog]:
    units = units or {}
    order = from_rows(
        entries.con,
        "emof_keys",
        {KEY: "VARCHAR", INDEX: "INTEGER"},
        [(key, index) for index, key in enumerate(selected)],
    )
    entry = f"{entries.name}.{KEY}", f"{entries.name}.{TEXT}"
    measured = f"{_present(entry[1])} AND {entry[0]} IN {literals(list(selected))}"

    def measure(key: str, matched: str, token: str) -> tuple:
        given = given_unit(units[key][0]) if key in units else None
        return _emof_values(key, token if matched == "true" else None, selected[key], given)

    values = lookup(
        entries.view("emof_entries", f"SELECT * FROM {entries.name} WHERE {measured}"),
        "emof_values",
        [KEY, *_shape(TEXT)],
        {
            **{internal(name): "VARCHAR" for name in _DESCRIBED},
            UNITLESS: "BOOLEAN",
            NUMBER_ONLY: "BOOLEAN",
            OVERRIDDEN: "VARCHAR",
            STATED: "VARCHAR",
        },
        measure,
    )
    joined = (
        f"FROM {entries.name} JOIN {order.name} ON {entry[0]} = {order.name}.{KEY} "
        f"JOIN {values.name} ON {matching(values, [entry[0], *_shape(entry[1])])} "
        f"WHERE {measured}"
    )
    described = ", ".join(
        f"{values.name}.{internal(name)} AS {column(name)}" for name in _DESCRIBED
    )
    value = (
        f"CASE WHEN {values.name}.{NUMBER_ONLY} "
        f"THEN regexp_extract({entry[1]}, {_VALUE_WITH_UNIT}, 1) ELSE {entry[1]} END"
    )
    rows = entries.view(
        "emof_rows",
        f"SELECT {entries.name}.{ROW}, {order.name}.{INDEX}, "
        f"{entries.name}.{OCCURRENCE} AS {column('occurrenceID')}, {described}, "
        f"{value} AS {column('measurementValue')}, "
        f"'' AS {column('measurementValueID')} {joined}",
    )
    found = []
    overridden, stated = f"{values.name}.{OVERRIDDEN}", f"{values.name}.{STATED}"
    for key, index, first, rows_found, first_unitless, unitless, replaced, mixed in entries.rows(
        f"SELECT {entry[0]}, any_value({order.name}.{INDEX}), min({entries.name}.{ROW}), "
        f"count(*), min({entries.name}.{ROW}) FILTER (WHERE {values.name}.{UNITLESS}), "
        f"count(*) FILTER (WHERE {values.name}.{UNITLESS}), "
        f"string_agg(DISTINCT {overridden}, ', ' ORDER BY {overridden}) "
        f"FILTER (WHERE {overridden} <> ''), "
        f"string_agg(DISTINCT {stated}, ', ' ORDER BY {stated}) "
        f"FILTER (WHERE {stated} <> '') {joined} GROUP BY 1"
    ):
        if selected[key] is None:
            found.append(((first, index, 0), _unvocabularied(key, rows_found)))
        if unitless:
            found.append(((first_unitless, index, 1), _unitless(key, unitless)))
        if replaced:
            found.append(((first, index, 2), _overridden(key, replaced, units[key])))
        if finding := _mixed_units(key, mixed.split(", ") if mixed else [], units.get(key)):
            found.append(((first, index, 3), finding))
    return rows, FindingsLog([finding for _, finding in sorted(found, key=lambda item: item[0])])


def _emof_values(
    header: str, token: str | None, alias: MeasurementAlias | None, given: Unit | None
) -> tuple:
    unit, number_only, _ = _unit_of(header, token, given)
    stated, source = _stated_unit(header, token)
    on_value = value_unit(token) if token else None
    return (
        alias.measurement_type if alias else header,
        unit.name if unit else "",
        alias.measurement_type_id if alias else "",
        unit.unit_id if unit else "",
        unit is None,
        number_only,
        f"{stated.name} (from {source})" if stated and given not in (None, stated) else "",
        on_value.name if on_value else "",
    )


def _unvocabularied(header: str, rows: int) -> Finding:
    return new_finding(
        "EMOF_TYPE_UNVOCABULARIED",
        f"{header!r} emitted as an eMoF row with a free-text measurementType; no vocabulary URI",
        count=rows,
    )


def _unitless(header: str, rows: int) -> Finding:
    return new_finding(
        "TERM_PAIR_INCOMPLETE",
        f"{header!r}: measurementValue populated with no measurementUnit. Name the unit "
        "in the column header, as in temp_C or depth (m), or give it in answers.yaml as "
        f"units.{header}: {{value: <unit>, provenance: <the document and where in it>}}",
        severity="warning",
        count=rows,
    )


def _overridden(header: str, replaced: str, answer: tuple[str, str]) -> Finding:
    unit, provenance = answer
    return new_finding(
        "MEASUREMENT_UNIT_OVERRIDDEN",
        f"{header!r}: units.{header} in answers.yaml publishes {given_unit(unit).name} "
        f"({provenance}) in place of {replaced}",
    )


def _mixed_units(header: str, stated: list[str], answer: tuple[str, str] | None) -> Finding | None:
    named = header_unit(header)
    if answer is not None:
        stated = sorted({*stated, named.name} if named else stated)
        return _mixed_under_answer(header, stated, answer) if len(stated) > 1 else None
    if named is None:
        return None
    others = [name for name in stated if name != named.name]
    return _mixed_under_header(header, named.name, others) if others else None


def _mixed_under_answer(header: str, stated: list[str], answer: tuple[str, str]) -> Finding:
    return new_finding(
        "MEASUREMENT_UNITS_MIXED",
        f"{header!r}: its header and values state {', '.join(stated)}, but units.{header} in answers.yaml "
        f"publishes every value as {given_unit(answer[0]).name}. Convert the values to one unit "
        f"in a reader script, or remove units.{header} so each value keeps the unit it states",
    )


def _mixed_under_header(header: str, named: str, others: list[str]) -> Finding:
    return new_finding(
        "MEASUREMENT_UNITS_MIXED",
        f"{header!r}: the header names {named}, but the values state {', '.join(others)}, so "
        f"those values are published as written. Convert the values to {named} in a reader "
        f"script, or, when the header names the wrong unit, give the right one as "
        f"units.{header} in answers.yaml",
    )


def _stated_unit(header: str, token: str | None) -> tuple[Unit | None, str]:
    unit = header_unit(header)
    if unit is not None:
        return unit, "the header"
    if token:
        return value_unit(token), "the values"
    return None, ""


def _unit_of(header: str, token: str | None, given: Unit | None) -> tuple[Unit | None, bool, str]:
    unit, source = _stated_unit(header, token)
    on_value = value_unit(token) if token else None
    number_only = token == "" or (on_value is not None and (given is not None or on_value == unit))
    if given is not None:
        return given, number_only, "units:"
    return unit, number_only, source


def describe_measurements(
    table: Table, selected: dict[str, MeasurementAlias | None], units: dict[str, tuple[str, str]]
) -> dict[str, str]:
    described = {}
    for key, alias in selected.items():
        text = table.text(key)
        given = given_unit(units[key][0]) if key in units else None
        found = []
        for matched, token in table.rows(
            f"SELECT {', '.join(_shape(text))} FROM {table.name} WHERE {_present(text)} "
            f"GROUP BY ALL ORDER BY min({ROW})"
        ):
            unit, _, source = _unit_of(key, token if matched == "true" else None, given)
            found.append(f"{unit.name} (from {source})" if unit else "none")
        measurement_type = alias.measurement_type if alias else key
        described[key] = (
            f"measurementType={measurement_type}; "
            f"measurementUnit={', '.join(dict.fromkeys(found)) or 'none'}"
        )
    return described
