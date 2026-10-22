from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from edna2dwc.common import table as table_module
from edna2dwc.common.table import ROW, Table, connect, read_tsv
from edna2dwc.common.tsv import read_header, write_tsv
from edna2dwc.dwca import writer
from edna2dwc.terms.term_table import load_term_table
from edna2dwc.validation import validate
from tests import elements, manifests
from tests.tables import table_of

TERM_TABLE = {
    "occurrenceID": {"uri": "http://rs.tdwg.org/dwc/terms/occurrenceID"},
    "scientificName": {"uri": "http://rs.tdwg.org/dwc/terms/scientificName"},
    "basisOfRecord": {"uri": "http://rs.tdwg.org/dwc/terms/basisOfRecord"},
    "kingdom": {
        "uri": "http://rs.tdwg.org/dwc/terms/kingdom",
        "priority_tier": "required",
    },
    "eventDate": {
        "uri": "http://rs.tdwg.org/dwc/terms/eventDate",
        "format": "iso8601_date",
        "pairs": [{"with": "eventID", "severity": "warning", "scope": "occurrence_core_only"}],
    },
    "eventID": {
        "uri": "http://rs.tdwg.org/dwc/terms/eventID",
        "pairs": [{"with": "eventDate", "severity": "warning", "scope": "occurrence_core_only"}],
    },
    "decimalLatitude": {
        "uri": "http://rs.tdwg.org/dwc/terms/decimalLatitude",
        "format": "decimal_degrees",
        "pairs": [{"with": "decimalLongitude", "severity": "error"}],
    },
    "decimalLongitude": {
        "uri": "http://rs.tdwg.org/dwc/terms/decimalLongitude",
        "format": "decimal_degrees",
        "pairs": [{"with": "decimalLatitude", "severity": "error"}],
    },
    "DNA_sequence": {"uri": "http://rs.gbif.org/terms/dna_sequence", "class": "DNADerivedData"},
    "measurementType": {"uri": "http://rs.tdwg.org/dwc/terms/measurementType"},
    "sampleSizeValue": {
        "uri": "http://rs.tdwg.org/dwc/terms/sampleSizeValue",
        "pairs": [{"with": "sampleSizeUnit", "severity": "error"}],
    },
    "sampleSizeUnit": {
        "uri": "http://rs.tdwg.org/dwc/terms/sampleSizeUnit",
        "pairs": [{"with": "sampleSizeValue", "severity": "error"}],
    },
    "measurementValue": {
        "uri": "http://rs.tdwg.org/dwc/terms/measurementValue",
        "pairs": [{"with": "measurementUnit", "severity": "warning"}],
    },
}


VALID_ROW = {
    "occurrenceID": "ds1_s1_f1",
    "scientificName": "Mytilus californianus",
    "basisOfRecord": "MaterialSample",
    "kingdom": "Animalia",
    "eventDate": "2021-06-01",
    "eventID": "ds1_s1",
    "decimalLatitude": "36.5",
    "decimalLongitude": "-122.0",
}


def _build_valid_archive(tmp_path: Path, *rows: dict, term_table=TERM_TABLE, **options) -> Path:
    rows = rows or (VALID_ROW,)
    core_path = tmp_path / "occurrence.tsv"
    write_tsv(list(rows), core_path, columns=list(rows[0]))
    out_dir = tmp_path / "archive"
    writer.write_archive(
        core_path=core_path,
        extensions={},
        manifest=manifests.required_manifest(),
        dataset_id="ds",
        generated_at="2024-06-01T00:00:00Z",
        term_table=term_table,
        out_dir=out_dir,
        **options,
    )
    return out_dir


def _findings(log) -> list[tuple[str, int, str]]:
    return [(f.code, f.count, f.message) for f in log.findings]


def test_validate_archive_is_clean_on_a_well_formed_archive(tmp_path):
    archive_dir = _build_valid_archive(tmp_path)
    log = validate.validate_archive(archive_dir, TERM_TABLE)
    assert log.findings == []


def test_validate_archive_reports_short_rows_once_with_a_count(tmp_path):
    archive_dir = _build_valid_archive(tmp_path)
    core_path = archive_dir / "occurrence.txt"
    lines = core_path.read_text(encoding="utf-8").splitlines()
    lines += [f"ds1_s1_f{n}\tMytilus californianus" for n in range(2, 5)]
    core_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    log = validate.validate_archive(archive_dir, TERM_TABLE)

    assert _findings(log) == [
        (
            "ARCHIVE_INVALID",
            3,
            (
                "occurrence.txt: 3 row(s) have a field count that does not match the header, "
                "such as row(s) 3, 4, 5"
            ),
        )
    ]


@pytest.mark.parametrize("kingdom", [{}, {"kingdom": ""}], ids=["absent", "blank on every row"])
def test_validate_archive_priority_terms_flags_an_unfilled_required_term(tmp_path, kingdom):
    archive_dir = _build_valid_archive(
        tmp_path,
        {
            "occurrenceID": "ds1_s1_f1",
            "scientificName": "Mytilus californianus",
            "basisOfRecord": "MaterialSample",
            **kingdom,
        },
    )
    log = validate.validate_archive(archive_dir, TERM_TABLE, priority_terms=True)
    assert [(f.code, f.message) for f in log.findings] == [
        ("TERM_MISSING_PRIORITY", "'kingdom' is filled on 0 of 1 rows")
    ]


def test_validate_archive_strict_flags_a_non_darwin_core_column(tmp_path):
    archive_dir = _build_valid_archive(tmp_path)
    occ_path = archive_dir / "occurrence.txt"
    lines = occ_path.read_text(encoding="utf-8").splitlines()
    new_column_index = len(lines[0].split("\t"))
    lines[0] = lines[0] + "\tverbatim_station_notes"
    lines[1] = lines[1] + "\tmuddy"
    occ_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    meta_path = archive_dir / "meta.xml"
    root = ET.fromstring(meta_path.read_text(encoding="utf-8"))
    core = elements.child(root, "{http://rs.tdwg.org/dwc/text/}core")
    ET.SubElement(
        core,
        "{http://rs.tdwg.org/dwc/text/}field",
        {"index": str(new_column_index), "term": "verbatim_station_notes"},
    )
    meta_path.write_bytes(ET.tostring(root, encoding="utf-8"))

    log = validate.validate_archive(archive_dir, TERM_TABLE, strict=True)
    assert [(f.code, f.message) for f in log.findings] == [
        ("TERM_NOT_DARWIN_CORE", "'verbatim_station_notes' is not a term in dwc_terms.json")
    ]


def test_validate_archive_detects_meta_index_mismatch(tmp_path):
    archive_dir = _build_valid_archive(tmp_path)
    meta_path = archive_dir / "meta.xml"
    text = meta_path.read_text(encoding="utf-8")
    text = text.replace(
        'index="2" term="http://rs.tdwg.org/dwc/terms/basisOfRecord"',
        'index="99" term="http://rs.tdwg.org/dwc/terms/basisOfRecord"',
    )
    meta_path.write_text(text, encoding="utf-8")
    log = validate.validate_archive(archive_dir, TERM_TABLE)
    assert [(f.code, f.message) for f in log.findings] == [
        (
            "META_INDEX_MISMATCH",
            "occurrence.txt: <field index=99> declares 'basisOfRecord', but the header has None there",
        )
    ]


def test_validate_archive_raises_on_a_negative_core_id_index(tmp_path):
    archive_dir = _build_valid_archive(tmp_path)
    meta_path = archive_dir / "meta.xml"
    text = meta_path.read_text(encoding="utf-8").replace('index="0"/>', 'index="-1"/>', 1)
    meta_path.write_text(text, encoding="utf-8")
    with pytest.raises(validate.ArchiveInvalidError, match="index"):
        validate.validate_archive(archive_dir, TERM_TABLE)


def test_validate_archive_raises_on_a_negative_extension_coreid_index(tmp_path):
    archive_dir = _build_valid_archive(tmp_path)
    ext_path = archive_dir / "dnaderiveddata.txt"
    ext_path.write_text("occurrenceID\tDNA_sequence\nds1_s1_f1\tACGT\n", encoding="utf-8")
    meta_path = archive_dir / "meta.xml"
    root = ET.fromstring(meta_path.read_text(encoding="utf-8"))
    ns = "{http://rs.tdwg.org/dwc/text/}"
    ext_el = ET.SubElement(
        root, f"{ns}extension", {"rowType": "http://rs.gbif.org/terms/1.0/DNADerivedData"}
    )
    files_el = ET.SubElement(ext_el, f"{ns}files")
    ET.SubElement(files_el, f"{ns}location").text = "dnaderiveddata.txt"
    ET.SubElement(ext_el, f"{ns}coreid", {"index": "-1"})
    ET.SubElement(
        ext_el, f"{ns}field", {"index": "1", "term": "http://rs.gbif.org/terms/dna_sequence"}
    )
    meta_path.write_bytes(ET.tostring(root, encoding="utf-8"))

    with pytest.raises(validate.ArchiveInvalidError, match="index"):
        validate.validate_archive(archive_dir, TERM_TABLE)


def _add_dna_extension(archive_dir: Path, id_column: str, rows: str, *, id_term: bool) -> None:
    (archive_dir / "dnaderiveddata.txt").write_text(
        f"{id_column}\tDNA_sequence\n{rows}", encoding="utf-8"
    )
    meta_path = archive_dir / "meta.xml"
    root = ET.fromstring(meta_path.read_text(encoding="utf-8"))
    ns = "{http://rs.tdwg.org/dwc/text/}"
    ext_el = ET.SubElement(
        root, f"{ns}extension", {"rowType": "http://rs.gbif.org/terms/1.0/DNADerivedData"}
    )
    files_el = ET.SubElement(ext_el, f"{ns}files")
    ET.SubElement(files_el, f"{ns}location").text = "dnaderiveddata.txt"
    ET.SubElement(ext_el, f"{ns}coreid", {"index": "0"})
    if id_term:
        ET.SubElement(
            ext_el,
            f"{ns}field",
            {"index": "0", "term": "http://rs.tdwg.org/dwc/terms/occurrenceID"},
        )
    ET.SubElement(
        ext_el, f"{ns}field", {"index": "1", "term": "http://rs.gbif.org/terms/dna_sequence"}
    )
    meta_path.write_bytes(ET.tostring(root, encoding="utf-8"))


def test_validate_archive_reports_orphaned_extension_rows_once_with_a_count(tmp_path):
    archive_dir = _build_valid_archive(tmp_path)
    orphans = "".join(f"orphan{n}\tACGT\n" for n in range(4))
    _add_dna_extension(archive_dir, "occurrenceID", orphans, id_term=True)

    log = validate.validate_archive(archive_dir, TERM_TABLE)

    assert _findings(log) == [
        (
            "ARCHIVE_INVALID",
            4,
            (
                "dnaderiveddata.txt: 4 row(s) have an occurrenceID with no matching core row, such "
                "as 'orphan0', 'orphan1', 'orphan2', 'orphan3'"
            ),
        )
    ]


def test_validate_archive_resolves_a_non_occurrence_id_coreid_column_name(tmp_path):
    archive_dir = _build_valid_archive(tmp_path)
    _add_dna_extension(archive_dir, "id", "ds1_s1_f1\tACGT\n", id_term=False)

    log = validate.validate_archive(archive_dir, TERM_TABLE)
    assert log.findings == []


@pytest.mark.parametrize(
    ("rows", "finding"),
    [
        (
            [{**VALID_ROW, "occurrenceID": "dup"}, {**VALID_ROW, "occurrenceID": "dup"}],
            ("ARCHIVE_INVALID", 1, "occurrence.txt: duplicate occurrenceID value 'dup'"),
        ),
        (
            [{**VALID_ROW, "decimalLatitude": "91.0"}],
            (
                "TERM_FORMAT_INVALID",
                1,
                (
                    "occurrence.txt: 1 row(s) have a decimalLatitude that is not a number of decimal "
                    "degrees within range, such as '91.0', first in row(s) 2"
                ),
            ),
        ),
        (
            [{**VALID_ROW, "eventDate": "03/04/2021"}],
            (
                "TERM_FORMAT_INVALID",
                1,
                (
                    "occurrence.txt: 1 row(s) have a eventDate that is not an ISO 8601 date such as "
                    "2021-06-01, or an interval of two, such as '03/04/2021', first in row(s) 2"
                ),
            ),
        ),
        (
            [{**VALID_ROW, "decimalLongitude": ""}],
            (
                "TERM_PAIR_INCOMPLETE",
                1,
                (
                    "occurrence.txt: 1 row(s) have 'decimalLatitude' populated but 'decimalLongitude' "
                    "is not, such as row(s) 2"
                ),
            ),
        ),
    ],
    ids=["duplicate_id", "latitude_out_of_range", "ambiguous_date", "incomplete_pair"],
)
def test_validate_archive_reports_a_value_the_archive_cannot_publish(tmp_path, rows, finding):
    log = validate.validate_archive(_build_valid_archive(tmp_path, *rows), TERM_TABLE)
    assert _findings(log) == [finding]


@pytest.mark.parametrize(
    ("no_dna_extension", "findings"),
    [
        (False, []),
        (
            True,
            [
                (
                    "DNA_TERMS_IN_CORE",
                    1,
                    (
                        "occurrence.txt has DNADerivedData-classed column(s) that belong in "
                        "dnaderiveddata.txt: DNA_sequence"
                    ),
                )
            ],
        ),
    ],
)
def test_validate_archive_reports_dna_columns_left_in_the_core(
    tmp_path, no_dna_extension, findings
):
    archive_dir = _build_valid_archive(
        tmp_path, {**VALID_ROW, "DNA_sequence": "ACGT"}, no_dna_extension=no_dna_extension
    )
    assert _findings(validate.validate_archive(archive_dir, TERM_TABLE)) == findings


def test_a_priority_term_still_counts_as_present_from_the_extension(tmp_path):
    term_table = TERM_TABLE | {
        "DNA_sequence": TERM_TABLE["DNA_sequence"] | {"priority_tier": "strongly_recommended"}
    }
    archive_dir = _build_valid_archive(
        tmp_path, {**VALID_ROW, "DNA_sequence": "ACGT"}, term_table=term_table
    )
    assert validate.validate_archive(archive_dir, term_table, priority_terms=True).findings == []


@pytest.mark.parametrize(
    ("file_location", "is_occurrence_core", "codes"),
    [("occurrence.txt", True, ["TERM_PAIR_INCOMPLETE"]), ("dnaderiveddata.txt", False, [])],
)
def test_check_pairs_and_expects_applies_a_scoped_pair_only_on_the_occurrence_core(
    file_location, is_occurrence_core, codes
):
    rows = [{"eventDate": "2021-06-01", "eventID": ""}]
    log = validate.check_pairs_and_expects(
        file_location,
        ["eventDate", "eventID"],
        table_of(rows),
        TERM_TABLE,
        is_occurrence_core=is_occurrence_core,
    )
    assert [f.code for f in log.findings] == codes


def test_check_pairs_and_expects_fires_when_the_partner_column_is_absent_entirely():
    header = ["sampleSizeValue"]
    rows = [{"sampleSizeValue": "1000"}, {"sampleSizeValue": "2000"}]
    log = validate.check_pairs_and_expects("occurrence.txt", header, table_of(rows), TERM_TABLE)
    assert [f.code for f in log.findings] == ["TERM_PAIR_INCOMPLETE"]
    assert "sampleSizeUnit" in log.findings[0].message


def test_an_incomplete_pair_is_reported_once_per_file_with_a_count_and_example_rows():
    rows = [{"sampleSizeValue": str(n)} for n in range(30)]
    log = validate.check_pairs_and_expects(
        "occurrence.txt", ["sampleSizeValue"], table_of(rows), TERM_TABLE
    )
    (finding,) = log.findings
    assert finding.count == 30
    assert "occurrence.txt" in finding.message
    assert "2" in finding.message


@pytest.mark.parametrize(
    ("column", "value", "severity"),
    [("decimalLatitude", "36.5", "error"), ("measurementValue", "7.9", "warning")],
)
def test_an_absent_partner_column_keeps_the_severity_the_rule_declares(column, value, severity):
    log = validate.check_pairs_and_expects(
        "occurrence.txt", [column], table_of([{column: value}]), TERM_TABLE
    )
    assert [(f.code, f.severity) for f in log.findings] == [("TERM_PAIR_INCOMPLETE", severity)]


def test_an_expects_rule_fires_when_its_consequent_column_is_absent_entirely():
    term_table = {
        "DNA_sequence": {
            "uri": "http://rs.gbif.org/terms/dna_sequence",
            "expects": [{"then": "target_gene", "severity": "error"}],
        }
    }
    log = validate.check_pairs_and_expects(
        "dnaderiveddata.txt", ["DNA_sequence"], table_of([{"DNA_sequence": "ACGT"}]), term_table
    )
    (finding,) = log.findings
    assert finding.code == "TERM_PAIR_INCOMPLETE"
    assert "target_gene" in finding.message


@pytest.mark.parametrize(
    "row",
    [{"sampleSizeValue": ""}, {"decimalLatitude": "36.5", "decimalLongitude": "-122.0"}],
    ids=["blank_antecedent", "complete_pair"],
)
def test_a_table_satisfying_every_pair_reports_nothing(row):
    log = validate.check_pairs_and_expects(
        "occurrence.txt", list(row), table_of([row]), TERM_TABLE
    )
    assert log.findings == []


@pytest.mark.parametrize("eml_text", [None, "<not valid xml"], ids=["missing", "malformed"])
def test_validate_archive_raises_on_an_eml_xml_it_cannot_read(tmp_path, eml_text):
    archive_dir = _build_valid_archive(tmp_path)
    eml_path = archive_dir / "eml.xml"
    if eml_text is None:
        eml_path.unlink()
    else:
        eml_path.write_text(eml_text, encoding="utf-8")
    with pytest.raises(validate.ArchiveInvalidError, match="eml.xml"):
        validate.validate_archive(archive_dir, TERM_TABLE)


def test_invalid_values_of_a_term_are_reported_once_with_a_count_and_examples():
    rows = [
        *[{"decimalLatitude": "91.0"}] * 20,
        *[{"decimalLatitude": "95"}] * 10,
        {"decimalLatitude": "36.5"},
    ]
    log = validate.check_formats("occurrence.txt", ["decimalLatitude"], table_of(rows), TERM_TABLE)
    (finding,) = log.findings
    assert finding.code == "TERM_FORMAT_INVALID"
    assert finding.count == 30
    assert "'91.0'" in finding.message
    assert "'95'" in finding.message


def test_an_invalid_value_is_described_in_plain_words_with_the_allowed_values():
    header = ["basisOfRecord", "ampliconSize"]
    rows = [{"basisOfRecord": "Material sample", "ampliconSize": "313 bp"}]
    term_table = load_term_table()
    log = validate.check_formats("occurrence.txt", header, table_of(rows), term_table)
    messages = {f.message.split(" that ")[0].split()[-1]: f.message for f in log.findings}
    assert "one of" in messages["basisOfRecord"]
    assert "MaterialSample" in messages["basisOfRecord"]
    assert "a number of zero or more" in messages["ampliconSize"]
    assert "nonneg_number" not in messages["ampliconSize"]


@pytest.mark.parametrize(
    ("file_location", "rows"),
    [
        (
            "extendedmeasurementorfact.txt",
            [
                {"measurementType": "depth", "measurementValue": "0-100"},
                {"measurementType": "size fraction upper", "measurementValue": ">0.8"},
                {"measurementType": "light", "measurementValue": "UV-light"},
            ],
        ),
        (
            "occurrence.txt",
            [
                {
                    "identificationReferences": "https://doi.org/10.1111/2041-210X.13214 | "
                    "https://doi.org/10.1002/edn3.303"
                },
                {"identificationReferences": "Curd et al. (2019) Anacapa Toolkit"},
            ],
        ),
    ],
    ids=["text_measurement_value", "identification_references"],
)
def test_a_free_text_value_passes_the_format_checks(file_location, rows):
    term_table = load_term_table()
    log = validate.check_formats(file_location, list(rows[0]), table_of(rows), term_table)
    assert log.findings == []


def test_count_format_checks_counts_checked_and_failed():
    header = ["eventDate", "decimalLatitude"]
    rows = [
        {"eventDate": "2021-06-01", "decimalLatitude": "36.5"},
        {"eventDate": "03/04/2021", "decimalLatitude": "91.0"},
        {"eventDate": "", "decimalLatitude": ""},
    ]
    checked, failed = validate.count_format_checks(header, table_of(rows), TERM_TABLE)
    assert checked == 4
    assert failed == 2


def test_load_adjudications_reads_status_per_issue_class(tmp_path):
    path = tmp_path / "adjudications.yaml"
    path.write_text(
        """
adjudications:
  RECORD_REFERENCES_TAXON_MATCH_NONE:
    provenance: "Biota incertae sedis terminal fallback"
    status: accepted
    confirmed: "PI: keep them"
  ON_LAND:
    provenance: "coastline simplification"
    status: rejected
    confirmed: "PI: move them"
  TAXON_MASS_COLLAPSE:
    provenance: "the agent judged it fine"
    status: accepted
""",
        encoding="utf-8",
    )
    assert validate.load_adjudications(path) == {
        "RECORD_REFERENCES_TAXON_MATCH_NONE": "accepted",
        "ON_LAND": "rejected",
    }


def test_load_adjudications_empty_file_returns_empty_dict(tmp_path):
    path = tmp_path / "adjudications.yaml"
    path.write_text("", encoding="utf-8")
    assert validate.load_adjudications(path) == {}


def test_check_row_accounting_reconciles_when_totals_match():
    log = validate.check_row_accounting(
        intermediate_row_count=100, archive_row_count=90, excluded_row_count=10
    )
    assert log.findings == []


def test_check_row_accounting_flags_a_silently_lost_row():
    log = validate.check_row_accounting(
        intermediate_row_count=100, archive_row_count=90, excluded_row_count=5
    )
    assert [(f.code, f.message) for f in log.findings] == [
        (
            "ROW_ACCOUNTING_MISMATCH",
            "intermediate rows (100) != archive rows (90) + documented exclusions (5)",
        )
    ]


def test_validate_archive_row_accounting_flags_a_mismatch_when_given(tmp_path):
    archive_dir = _build_valid_archive(tmp_path)
    log = validate.validate_archive(
        archive_dir, TERM_TABLE, intermediate_row_count=5, excluded_row_count=0
    )
    assert [(f.code, f.message) for f in log.findings] == [
        (
            "ROW_ACCOUNTING_MISMATCH",
            "intermediate rows (5) != archive rows (1) + documented exclusions (0)",
        )
    ]


def _fill(**terms: tuple[int, int]) -> dict[str, tuple[int, int]]:
    return {"occurrenceID": (1, 1), "scientificName": (1, 1), **terms}


def test_check_priority_required_terms_satisfied_by_a_filled_extension_column():
    log = validate.check_priority_required_terms(_fill(kingdom=(1, 1)), TERM_TABLE)
    assert log.findings == []


def test_check_priority_required_terms_flags_a_genuinely_absent_term():
    log = validate.check_priority_required_terms(_fill(), TERM_TABLE)
    assert [(f.code, f.message) for f in log.findings] == [
        ("TERM_MISSING_PRIORITY", "'kingdom' is filled on 0 of 0 rows")
    ]


def test_check_priority_required_terms_flags_a_term_blank_on_every_row():
    log = validate.check_priority_required_terms(_fill(kingdom=(0, 4)), TERM_TABLE)
    (finding,) = [f for f in log.findings if "kingdom" in f.message]
    assert "0 of 4 rows" in finding.message


def test_check_priority_required_terms_does_not_flag_a_not_applicable_term():
    log = validate.check_priority_required_terms(
        _fill(), TERM_TABLE, not_applicable_terms={"kingdom"}
    )
    assert log.findings == []


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("ON_LAND: accepted\n", "adjudications:"),
        ("adjudications:\n  ON_LAND: accepted\n", "status"),
        ("adjudications:\n  ON_LAND:\n    status: ok\n    provenance: PI\n", "'ok'"),
    ],
)
def test_an_adjudications_file_of_the_wrong_shape_is_an_error(tmp_path, text, problem):
    path = tmp_path / "adjudications.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(validate.AdjudicationsError, match=problem):
        validate.load_adjudications(path)


def test_check_priority_required_terms_reports_a_strongly_recommended_term_as_a_warning():
    term_table = {**TERM_TABLE, "institutionCode": {"priority_tier": "strongly_recommended"}}
    log = validate.check_priority_required_terms(_fill(kingdom=(1, 1)), term_table)
    (finding,) = [f for f in log.findings if "institutionCode" in f.message]
    assert finding.code == "TERM_MISSING_RECOMMENDED"
    assert finding.severity == "warning"


def test_example_rows_of_millions_of_failing_rows_fit_in_a_small_memory_limit(monkeypatch):
    monkeypatch.setenv(table_module.MEMORY_LIMIT_ENV, "32MB")
    with connect() as con:
        con.execute(
            f'CREATE TABLE core AS SELECT i AS {ROW}, i::VARCHAR AS "sample^Size^Value" '
            "FROM range(4000000) AS r(i)"
        )
        log = validate.check_pairs_and_expects(
            "occurrence.txt", ["sampleSizeValue"], Table(con, "core"), TERM_TABLE
        )
    (finding,) = log.findings
    assert finding.count == 4000000
    assert "such as row(s) 2, 3, 4, 5, 6" in finding.message


def _rows_of(archive_dir: Path, name: str, con) -> Table:
    path = archive_dir / name
    return read_tsv(con, path, "given", list(read_header(path, delimiter="\t")))


def test_validate_archive_checks_the_tables_it_is_given_instead_of_reading_the_files(tmp_path):
    archive_dir = _build_valid_archive(tmp_path)
    with connect() as con:
        given = _rows_of(archive_dir, "occurrence.txt", con)
        (archive_dir / "occurrence.txt").write_text(
            "occurrenceID\tscientificName\tbasisOfRecord\tkingdom\teventDate\teventID\t"
            "decimalLatitude\tdecimalLongitude\nds1_s1_f1\tA\tMaterialSample\tAnimalia\t"
            "not a date\tds1_s1\t36.5\t-122.0\n",
            encoding="utf-8",
        )
        log = validate.validate_archive(
            archive_dir, TERM_TABLE, connection=con, tables={"occurrence.txt": given}
        )
    assert log.findings == []


def test_validate_step_takes_the_row_counts_in_place_of_the_files(tmp_path):
    archive_dir = _build_valid_archive(tmp_path)
    result = validate.step(
        archive_dir=archive_dir,
        term_table=TERM_TABLE,
        intermediate_row_count=3,
        excluded_row_count=1,
    )
    assert [f["code"] for f in result.findings] == ["ROW_ACCOUNTING_MISMATCH"]


def test_a_short_row_is_still_found_in_a_table_validation_was_given(tmp_path):
    archive_dir = _build_valid_archive(tmp_path)
    occ_path = archive_dir / "occurrence.txt"
    with connect() as con:
        given = _rows_of(archive_dir, "occurrence.txt", con)
        lines = occ_path.read_text(encoding="utf-8").splitlines()
        lines[1] = "\t".join(lines[1].split("\t")[:-1])
        occ_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        log = validate.validate_archive(
            archive_dir, TERM_TABLE, connection=con, tables={"occurrence.txt": given}
        )
    assert [f.code for f in log.findings] == ["ARCHIVE_INVALID"]
    assert "row(s) 2" in log.findings[0].message
