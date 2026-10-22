import json
from pathlib import Path
import time
from xml.etree import ElementTree as ET
import zipfile

import duckdb
import pytest

from edna2dwc.common.table import ROW, read_tsv
from edna2dwc.common.tsv import read_rows, write_tsv
from edna2dwc.conversion import artifacts
from edna2dwc.dwca import writer
from edna2dwc.terms.dynamic_properties import DynamicProperties
from tests import elements, manifests
from tests.tables import table_of

NS = {"dwc": "http://rs.tdwg.org/dwc/text/"}
DWC = "http://rs.tdwg.org/dwc/terms/"

TERM_TABLE = {
    "occurrenceID": {"uri": f"{DWC}occurrenceID"},
    "scientificName": {"uri": f"{DWC}scientificName"},
    "basisOfRecord": {"uri": f"{DWC}basisOfRecord"},
    "kingdom": {"uri": f"{DWC}kingdom"},
    "decimalLatitude": {"uri": f"{DWC}decimalLatitude"},
    "decimalLongitude": {"uri": f"{DWC}decimalLongitude"},
    "eventDate": {"uri": f"{DWC}eventDate"},
    "occurrenceStatus": {"uri": f"{DWC}occurrenceStatus"},
    "organismQuantity": {"uri": f"{DWC}organismQuantity"},
    "DNA_sequence": {"uri": "http://rs.gbif.org/terms/dna_sequence", "class": "DNADerivedData"},
    "target_gene": {"uri": "https://w3id.org/gensc/terms/MIXS:0000044", "class": "DNADerivedData"},
    "pcr_primer_lod": {
        "class": "DNADerivedData",
        "uri": "http://rs.gbif.org/terms/miqe/pcr_primer_lod",
    },
    "dynamicProperties": {"uri": f"{DWC}dynamicProperties"},
    "measurementType": {"uri": f"{DWC}measurementType"},
    "measurementValue": {"uri": f"{DWC}measurementValue"},
    "measurementUnit": {"uri": f"{DWC}measurementUnit"},
    "measurementTypeID": {"uri": "http://rs.iobis.org/obis/terms/measurementTypeID"},
    "measurementUnitID": {"uri": "http://rs.iobis.org/obis/terms/measurementUnitID"},
    "measurementValueID": {"uri": "http://rs.iobis.org/obis/terms/measurementValueID"},
}

MUSSEL = {
    "occurrenceID": "ds1_s1_f1",
    "scientificName": "Mytilus californianus",
    "basisOfRecord": "MaterialSample",
    "kingdom": "Animalia",
}
DNA_ROW = {"occurrenceID": "ds1_s1_f1", "DNA_sequence": "ACGT", "target_gene": "18S"}
SEQUENCED_MUSSEL = MUSSEL | {"DNA_sequence": "ACGT", "target_gene": "18S"}


def _occurrence(i, **values):
    return {
        "occurrenceID": f"ds1_s1_f{i}",
        "scientificName": "A",
        "basisOfRecord": "MaterialSample",
        **values,
    }


def _write(tmp_path: Path, rows=(MUSSEL,), *, extensions=None, **options) -> Path:
    core_path = tmp_path / "occurrence.tsv"
    write_tsv(list(rows), core_path, columns=list(rows[0]))
    extension_paths = {}
    for key, extension_rows in (extensions or {}).items():
        extension_paths[key] = tmp_path / f"{key}_extension.tsv"
        write_tsv(extension_rows, extension_paths[key], columns=list(extension_rows[0]))
    out_dir = tmp_path / "archive"
    writer.write_archive(
        core_path=core_path,
        extensions=extension_paths,
        manifest=manifests.required_manifest(),
        dataset_id="urn:uuid:test-dataset",
        generated_at="2024-06-01T00:00:00Z",
        term_table=TERM_TABLE,
        out_dir=out_dir,
        **options,
    )
    return out_dir


def _eml(out_dir: Path) -> ET.Element:
    return ET.fromstring((out_dir / "eml.xml").read_text(encoding="utf-8"))


def _method_paragraphs(out_dir: Path) -> list[str]:
    return [
        p.text or "" for p in _eml(out_dir).findall("dataset/methods/methodStep/description/para")
    ]


def _meta_table(out_dir: Path, tag: str) -> ET.Element:
    table = ET.fromstring((out_dir / "meta.xml").read_text(encoding="utf-8")).find(
        f"dwc:{tag}", NS
    )
    assert table is not None
    return table


def _key_index(table: ET.Element, tag: str) -> str | None:
    key = table.find(f"dwc:{tag}", NS)
    assert key is not None
    return key.get("index")


def _fields(table: ET.Element) -> list[tuple[str | None, str | None]]:
    return [(f.get("index"), f.get("term")) for f in table.findall("dwc:field", NS)]


def test_write_archive_writes_the_core_rows_meta_and_eml_and_zips_them(tmp_path):
    out_dir = _write(tmp_path)
    assert (out_dir / "occurrence.txt").read_text(encoding="utf-8").splitlines() == [
        "occurrenceID\tscientificName\tbasisOfRecord\tkingdom",
        "ds1_s1_f1\tMytilus californianus\tMaterialSample\tAnimalia",
    ]
    with zipfile.ZipFile(out_dir / artifacts.ZIP_NAME) as zf:
        assert zf.namelist() == ["occurrence.txt", "meta.xml", "eml.xml"]


def test_write_archive_moves_dna_columns_into_their_own_extension(tmp_path):
    out_dir = _write(tmp_path, [SEQUENCED_MUSSEL])
    assert list(read_rows(out_dir / "occurrence.txt", delimiter="\t")) == [MUSSEL]
    assert list(read_rows(out_dir / "dnaderiveddata.txt", delimiter="\t")) == [DNA_ROW]
    with zipfile.ZipFile(out_dir / artifacts.ZIP_NAME) as zf:
        assert "dnaderiveddata.txt" in zf.namelist()


def test_no_dna_extension_leaves_the_dna_columns_in_the_core(tmp_path):
    out_dir = _write(tmp_path, [SEQUENCED_MUSSEL], no_dna_extension=True)
    assert not (out_dir / "dnaderiveddata.txt").exists()
    assert list(read_rows(out_dir / "occurrence.txt", delimiter="\t")) == [SEQUENCED_MUSSEL]


def test_a_dna_column_blank_in_every_row_still_gets_a_declared_header_only_extension(tmp_path):
    out_dir = _write(tmp_path, [MUSSEL | {"DNA_sequence": "", "target_gene": ""}])
    extension = out_dir / "dnaderiveddata.txt"
    assert extension.read_text(encoding="utf-8") == "occurrenceID\tDNA_sequence\ttarget_gene\n"
    assert [term for _, term in _fields(_meta_table(out_dir, "extension"))] == [
        f"{DWC}occurrenceID",
        "http://rs.gbif.org/terms/dna_sequence",
        "https://w3id.org/gensc/terms/MIXS:0000044",
    ]


def test_meta_xml_declares_the_core_and_extension_by_full_term_uris(tmp_path):
    out_dir = _write(tmp_path, [SEQUENCED_MUSSEL])
    core = _meta_table(out_dir, "core")
    extension = _meta_table(out_dir, "extension")

    assert core.get("rowType") == f"{DWC}Occurrence"
    assert core.get("fieldsEnclosedBy") == ""
    assert _key_index(core, "id") == "0"
    assert _fields(core) == [
        ("0", f"{DWC}occurrenceID"),
        ("1", f"{DWC}scientificName"),
        ("2", f"{DWC}basisOfRecord"),
        ("3", f"{DWC}kingdom"),
    ]
    assert extension.get("rowType") == "http://rs.gbif.org/terms/1.0/DNADerivedData"
    assert _key_index(extension, "coreid") == "0"
    assert _fields(extension) == [
        ("0", f"{DWC}occurrenceID"),
        ("1", "http://rs.gbif.org/terms/dna_sequence"),
        ("2", "https://w3id.org/gensc/terms/MIXS:0000044"),
    ]


def test_mixs_uri_style_legacy_rewrites_gensc_uris(tmp_path):
    out_dir = _write(tmp_path, extensions={"dnaderiveddata": [DNA_ROW]}, mixs_uri_style="legacy")
    assert _fields(_meta_table(out_dir, "extension"))[2] == (
        "2",
        "https://w3id.org/mixs/0000044",
    )


def test_write_archive_leaves_the_placeholder_taxon_out_of_eml_taxonomic_coverage(tmp_path):
    rows = [
        _occurrence(i, kingdom=kingdom)
        for i, kingdom in enumerate(["Biota incertae sedis", "Animalia", "Plantae", "Chromista"])
    ]
    classifications = _eml(_write(tmp_path, rows)).findall(
        "dataset/coverage/taxonomicCoverage/taxonomicClassification"
    )
    assert [elements.child_text(c, "taxonRankValue") for c in classifications] == [
        "Animalia",
        "Plantae",
        "Chromista",
    ]


def test_write_archive_omits_taxonomic_coverage_when_every_record_is_unassigned(tmp_path):
    out_dir = _write(tmp_path, [_occurrence(1, kingdom="Biota incertae sedis")])
    assert _eml(out_dir).find(".//taxonomicCoverage") is None


@pytest.mark.parametrize(
    ("event_dates", "begin", "end"),
    [
        (["2021-06-01/2021-06-05", "2021-03-01"], "2021-03-01", "2021-06-05"),
        (["2021-06", "2021-06-01T08:00:00Z", "2021-06-20"], "2021-06-01", "2021-06-20"),
    ],
)
def test_write_archive_temporal_coverage_spans_the_full_days_of_its_event_dates(
    tmp_path, event_dates, begin, end
):
    rows = [_occurrence(i, eventDate=date) for i, date in enumerate(event_dates)]
    range_of_dates = elements.child(
        _eml(_write(tmp_path, rows)), "dataset/coverage/temporalCoverage/rangeOfDates"
    )
    assert elements.child_text(range_of_dates, "beginDate/calendarDate") == begin
    assert elements.child_text(range_of_dates, "endDate/calendarDate") == end


@pytest.mark.parametrize(
    ("rows", "extensions", "options", "message"),
    [
        (
            [{"occurrenceID": "x", "kingdom": "Animalia"}],
            {},
            {},
            "core table is missing build-blocking required term(s): scientificName, basisOfRecord",
        ),
        (
            [MUSSEL],
            {"occurrence": [DNA_ROW]},
            {},
            (
                "'occurrence' and 'occurrence' both resolve to rowType "
                "'http://rs.tdwg.org/dwc/terms/Occurrence', and an archive can declare each "
                "rowType at most once"
            ),
        ),
        (
            [MUSSEL],
            {"dnaderiveddata": [{**DNA_ROW, "dynamicProperties": "{}"}]},
            {},
            (
                "'dnaderiveddata' extension has a dynamicProperties column. dynamicProperties "
                "folding is permitted only on the occurrence/event core, never on an extension"
            ),
        ),
        (
            [_occurrence(1, verbatim_notes="z", another_fake_column="w")],
            {},
            {},
            (
                "build refuses non-Darwin-Core column(s): 'verbatim_notes' is not a term in "
                "dwc_terms.json, 'another_fake_column' is not a term in dwc_terms.json"
            ),
        ),
        (
            [_occurrence(1, dynamicProperties=json.dumps({"temp_C": "12.5"}))],
            {"extendedmeasurementorfact": [{"occurrenceID": "ds1_s1_f1", "measurementType": "x"}]},
            {},
            (
                "eMoF is on by default and selected real measurement columns, but --extension "
                "extendedmeasurementorfact=... was also given. Pass --no-emof to supply your own "
                "eMoF table instead"
            ),
        ),
        (
            [SEQUENCED_MUSSEL],
            {"dnaderiveddata": [DNA_ROW]},
            {},
            (
                "the DNADerivedData extension is on by default and selected sequence columns, "
                "but --extension dnaderiveddata=... was also given. Pass --no-dna-extension to "
                "supply your own DNADerivedData table instead"
            ),
        ),
        (
            [MUSSEL],
            {},
            {"mixs_uri_style": "bogus"},
            "mixs_uri_style must be 'gensc' or 'legacy', got 'bogus'",
        ),
    ],
)
def test_write_archive_refuses_a_table_it_cannot_publish_and_writes_nothing(
    tmp_path, rows, extensions, options, message
):
    with pytest.raises(writer.ArchiveBuildError) as error:
        _write(tmp_path, rows, extensions=extensions, **options)
    assert str(error.value) == message
    assert not (tmp_path / "archive" / "occurrence.txt").exists()
    assert not (tmp_path / "archive" / "meta.xml").exists()


@pytest.mark.parametrize(
    ("columns", "expected_codes"),
    [
        (
            ["occurrenceID", "bogus_one", "scientificName", "bogus_two"],
            ["TERM_NOT_DARWIN_CORE", "TERM_NOT_DARWIN_CORE"],
        ),
        (["occurrenceID", "scientificName"], []),
    ],
)
def test_check_columns_are_darwin_core_flags_each_unknown_column(columns, expected_codes):
    log = writer.check_columns_are_darwin_core(columns, TERM_TABLE)
    assert [f.code for f in log.findings] == expected_codes


def test_write_archive_zip_is_deflated_not_stored(tmp_path):
    out_dir = _write(tmp_path, [_occurrence(i, scientificName="Mytilus " * 5) for i in range(500)])
    with zipfile.ZipFile(out_dir / artifacts.ZIP_NAME) as zf:
        info = zf.getinfo("occurrence.txt")
    assert info.compress_type == zipfile.ZIP_DEFLATED
    assert info.compress_size < info.file_size


def test_write_archive_promotes_a_measurement_to_emof_by_default(tmp_path):
    out_dir = _write(tmp_path, [_occurrence(1, dynamicProperties=json.dumps({"temp_C": "12.5"}))])
    emof_rows = list(read_rows(out_dir / "extendedmeasurementorfact.txt", delimiter="\t"))
    assert emof_rows[0]["measurementType"] == "temperature"
    core_rows = list(read_rows(out_dir / "occurrence.txt", delimiter="\t"))
    assert "dynamicProperties" not in core_rows[0]


def _package(tmp_path: Path, values: list[str], **options) -> tuple[list[dict], list[str]]:
    path = tmp_path / "occurrence.tsv"
    columns = ["occurrenceID", "scientificName", "basisOfRecord", "dynamicProperties"]
    rows = [
        dict(zip(columns, (f"o{n}", "Mytilus", "MaterialSample", v))) for n, v in enumerate(values)
    ]
    write_tsv(rows, path, columns=columns)
    packaged = writer.write_archive(
        core_path=path,
        extensions={},
        manifest=manifests.required_manifest(),
        dataset_id="ds",
        generated_at="2024-06-01T00:00:00Z",
        term_table=TERM_TABLE,
        out_dir=tmp_path / "archive",
        **options,
    )
    occurrences = list(read_rows(tmp_path / "archive" / "occurrence.txt", delimiter="\t"))
    return occurrences, [f.code for f in packaged.findings.findings]


@pytest.mark.parametrize(
    "raw", ['{"temp_C": 12.50, "path": "a\\/b"}', "not json", "[1]", '{"dup": 1, "dup": 2}']
)
def test_write_archive_no_emof_leaves_dynamic_properties_untouched(tmp_path, raw):
    occurrences, codes = _package(tmp_path, [raw], no_emof=True)
    assert occurrences[0]["dynamicProperties"] == raw
    assert codes == []
    assert not (tmp_path / "archive" / "extendedmeasurementorfact.txt").exists()


def test_write_archive_reports_and_leaves_out_a_value_that_repeats_a_key(tmp_path):
    occurrences, codes = _package(
        tmp_path, ['{"dup": 1, "dup": 2}', '{"temp_C": "12.5", "a": "x"}']
    )
    assert "DYNAMIC_PROPERTIES_MALFORMED" in codes
    assert [row["dynamicProperties"] for row in occurrences] == ["", '{"a":"x"}']
    assert (tmp_path / "archive" / "extendedmeasurementorfact.txt").exists()


def test_write_archive_leaves_out_dynamic_properties_when_it_ends_up_blank_on_every_row(tmp_path):
    occurrences, codes = _package(tmp_path, ['{"temp_C": "12.5"}', "not json"])
    assert codes == ["DYNAMIC_PROPERTIES_MALFORMED"]
    assert all("dynamicProperties" not in row for row in occurrences)


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="time.tzset is POSIX-only")
@pytest.mark.parametrize(
    "tz", ["UTC", "America/Los_Angeles", "Asia/Kolkata", "Pacific/Kiritimati"]
)
def test_write_archive_zip_timestamp_is_independent_of_local_timezone(tmp_path, tz, monkeypatch):
    monkeypatch.setenv("TZ", tz)
    time.tzset()
    try:
        out_dir = _write(tmp_path)
        with zipfile.ZipFile(out_dir / artifacts.ZIP_NAME) as zf:
            assert zf.getinfo("occurrence.txt").date_time == writer._FIXED_ZIP_DATE_TIME
    finally:
        monkeypatch.delenv("TZ", raising=False)
        time.tzset()


def test_write_archive_leaves_the_mtime_of_the_files_it_zips(tmp_path):
    before = time.time() - 60
    out_dir = _write(tmp_path)
    assert (out_dir / "occurrence.txt").stat().st_mtime > before


def test_check_no_duplicate_row_types_rejects_an_unrecognized_key():
    with pytest.raises(writer.ArchiveBuildError, match="somethingelse"):
        writer.check_no_duplicate_row_types(["occurrence", "somethingelse"])


def test_resolve_table_specs_reads_the_core_and_each_extension():
    core_path, extensions = writer.resolve_table_specs(
        "occurrence=occ.tsv", ("dnaderiveddata=dna.tsv",)
    )
    assert core_path == Path("occ.tsv")
    assert extensions == {"dnaderiveddata": Path("dna.tsv")}


@pytest.mark.parametrize(
    ("core_spec", "extension_specs", "message"),
    [
        ("occ.tsv", (), "--core 'occ.tsv' must be in TYPE=PATH form"),
        ("event=event.tsv", (), "--core only supports 'occurrence' today, got 'event'"),
        (
            "occurrence=occ.tsv",
            ("dnaderiveddata=a.tsv", "dnaderiveddata=b.tsv"),
            "--extension 'dnaderiveddata' was given more than once",
        ),
    ],
)
def test_resolve_table_specs_refuses_a_spec_it_cannot_read(core_spec, extension_specs, message):
    with pytest.raises(writer.ArchiveBuildError) as error:
        writer.resolve_table_specs(core_spec, extension_specs)
    assert str(error.value) == message


def test_scan_eml_summary_skips_a_padded_kingdom_and_a_kingdom_a_short_row_never_had(tmp_path):
    core_path = tmp_path / "occurrence.tsv"
    core_path.write_text(
        "occurrenceID\teventDate\tkingdom\n"
        "o1\t2024-06-01\t   \n"
        "o2\t2024-06-01\n"
        "o3\t2024-06-01\t Animalia \n",
        encoding="utf-8",
    )
    kingdoms = writer._scan_eml_summary(read_tsv(duckdb.connect(), core_path, "core")).kingdoms
    assert kingdoms == ["Animalia"]


def test_write_archive_states_the_presence_only_convention_from_its_own_rows(tmp_path):
    out_dir = _write(tmp_path, [_occurrence(1, occurrenceStatus="present")])
    assert "Presence-only: zero-count records are not published as absences." in (
        _method_paragraphs(out_dir)
    )


def test_write_archive_publishes_absences_with_the_lod_they_rest_on(tmp_path):
    rows = [
        _occurrence(
            i, occurrenceStatus=status, organismQuantity=count, pcr_primer_lod="5 copies/reaction"
        )
        for i, (status, count) in enumerate([("present", "12"), ("absent", "0")])
    ]
    out_dir = _write(tmp_path, rows)
    statuses = [
        r["occurrenceStatus"] for r in read_rows(out_dir / "occurrence.txt", delimiter="\t")
    ]
    assert statuses == ["present", "absent"]
    dna_rows = list(read_rows(out_dir / "dnaderiveddata.txt", delimiter="\t"))
    assert {r["pcr_primer_lod"] for r in dna_rows} == {"5 copies/reaction"}
    assert any(
        "occurrenceStatus=absent" in p and "5 copies/reaction" in p
        for p in _method_paragraphs(out_dir)
    )


def test_write_archive_derives_geographic_coverage_from_the_coordinates_and_reports_it(
    tmp_path,
):
    rows = [
        _occurrence(i, decimalLatitude=lat, decimalLongitude=lon)
        for i, (lat, lon) in enumerate((("47.6", "-122.45"), ("47.76", "-122.44"), ("", "")))
    ]
    out_dir = tmp_path / "archive"
    core = table_of(rows)
    findings = writer.write_archive_from_table(
        core=core,
        core_header=list(rows[0]),
        dynamic=DynamicProperties.published_in(core),
        measured=(),
        extensions={},
        manifest=manifests.required_manifest(),
        dataset_id="urn:uuid:test-dataset",
        generated_at="2024-06-01T00:00:00Z",
        term_table=TERM_TABLE,
        out_dir=out_dir,
    ).findings
    box = {c.tag: c.text for c in elements.child(_eml(out_dir), ".//boundingCoordinates")}
    assert box == {
        "westBoundingCoordinate": "-122.45",
        "eastBoundingCoordinate": "-122.44",
        "northBoundingCoordinate": "47.76",
        "southBoundingCoordinate": "47.6",
    }
    assert [f.code for f in findings.findings] == ["GEOGRAPHIC_COVERAGE_DERIVED"]


def test_write_archive_returns_each_table_as_written_with_its_line_numbers(tmp_path):
    rows = [
        {
            "occurrenceID": f"ds1_s{i}_f1",
            "scientificName": name,
            "basisOfRecord": "MaterialSample",
        }
        for i, name in enumerate(("Mytilus\ncalifornianus", "Aaptos"))
    ]
    source = table_of(rows)
    written = writer.write_archive_from_table(
        core=source,
        core_header=list(rows[0]),
        dynamic=DynamicProperties.published_in(source),
        measured=(),
        extensions={},
        manifest=manifests.required_manifest(),
        dataset_id="ds1",
        generated_at="2024-06-01T00:00:00Z",
        term_table=TERM_TABLE,
        out_dir=tmp_path / "archive",
    )
    core = written.tables["occurrence.txt"]
    lines = (tmp_path / "archive" / "occurrence.txt").read_text(encoding="utf-8").splitlines()
    name = core.text("scientificName")
    assert core.rows(f"SELECT {ROW} + 2, {name} FROM {core.name} ORDER BY {ROW}") == [
        (2, "Mytilus californianus"),
        (3, "Aaptos"),
    ]
    assert lines[1].split("\t")[1] == "Mytilus californianus"
    assert [f.code for f in written.findings.findings] == []
