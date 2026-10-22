from pathlib import Path
from xml.etree import ElementTree as ET

import pytest


TERM_TABLE = {
    "occurrenceID": {"uri": "http://rs.tdwg.org/dwc/terms/occurrenceID"},
    "scientificName": {"uri": "http://rs.tdwg.org/dwc/terms/scientificName"},
    "basisOfRecord": {"uri": "http://rs.tdwg.org/dwc/terms/basisOfRecord"},
    "kingdom": {
        "uri": "http://rs.tdwg.org/dwc/terms/kingdom",
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
}


    core_path = tmp_path / "occurrence.tsv"
    out_dir = tmp_path / "archive"
        core_path=core_path,
        extensions={},
        dataset_id="ds",
        generated_at="2024-06-01T00:00:00Z",
        out_dir=out_dir,
    )
    return out_dir


def test_validate_archive_is_clean_on_a_well_formed_archive(tmp_path):
    archive_dir = _build_valid_archive(tmp_path)
    log = validate.validate_archive(archive_dir, TERM_TABLE)
    assert log.findings == []


    archive_dir = _build_valid_archive(
        tmp_path,
    )


def test_validate_archive_strict_flags_a_non_darwin_core_column(tmp_path):
    archive_dir = _build_valid_archive(tmp_path)
    occ_path = archive_dir / "occurrence.txt"
    lines = occ_path.read_text(encoding="utf-8").splitlines()
    lines[0] = lines[0] + "\tverbatim_station_notes"
    lines[1] = lines[1] + "\tmuddy"
    occ_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    meta_path = archive_dir / "meta.xml"
    root = ET.fromstring(meta_path.read_text(encoding="utf-8"))
        core,
        "{http://rs.tdwg.org/dwc/text/}field",
    )
    meta_path.write_bytes(ET.tostring(root, encoding="utf-8"))

    log = validate.validate_archive(archive_dir, TERM_TABLE, strict=True)


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
    ET.SubElement(
        ext_el, f"{ns}field", {"index": "1", "term": "http://rs.gbif.org/terms/dna_sequence"}
    )
    meta_path.write_bytes(ET.tostring(root, encoding="utf-8"))

def test_validate_archive_resolves_a_non_occurrence_id_coreid_column_name(tmp_path):
    archive_dir = _build_valid_archive(tmp_path)

    log = validate.validate_archive(archive_dir, TERM_TABLE)
    assert log.findings == []


    archive_dir = _build_valid_archive(
    )


    archive_dir = _build_valid_archive(
    )


    rows = [{"eventDate": "2021-06-01", "eventID": ""}]
    log = validate.check_pairs_and_expects(
    )


    archive_dir = _build_valid_archive(tmp_path)
    with pytest.raises(validate.ArchiveInvalidError, match="eml.xml"):
        validate.validate_archive(archive_dir, TERM_TABLE)


def test_count_format_checks_counts_checked_and_failed():
    header = ["eventDate", "decimalLatitude"]
    rows = [
        {"eventDate": "2021-06-01", "decimalLatitude": "36.5"},
        {"eventDate": "03/04/2021", "decimalLatitude": "91.0"},
        {"eventDate": "", "decimalLatitude": ""},
    ]
    assert checked == 4
    assert failed == 2


def test_load_adjudications_reads_status_per_issue_class(tmp_path):
    path = tmp_path / "adjudications.yaml"
    path.write_text(
        """
adjudications:
  RECORD_REFERENCES_TAXON_MATCH_NONE:
    status: accepted
  ON_LAND:
    status: rejected
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


def test_validate_archive_row_accounting_flags_a_mismatch_when_given(tmp_path):
    archive_dir = _build_valid_archive(tmp_path)
    log = validate.validate_archive(
        archive_dir, TERM_TABLE, intermediate_row_count=5, excluded_row_count=0
    )


    assert log.findings == []




    )
    assert log.findings == []
