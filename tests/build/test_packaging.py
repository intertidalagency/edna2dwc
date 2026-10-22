from __future__ import annotations

import json
from pathlib import Path
import shutil
import zipfile

import pytest
import yaml

from edna2dwc.build import packaging, questions, sheets
from edna2dwc.build.result import BuildResult
from edna2dwc.common.result import CommandResult
from edna2dwc.common.tsv import read_rows, write_tsv
from edna2dwc.conversion import artifacts
from edna2dwc.dwca import writer
from edna2dwc.review import audit
from edna2dwc.taxonomy import resolve_taxonomy
from edna2dwc.terms.map_terms import read_mapping_tsv
from edna2dwc.validation import gbif_validator
from tests.make_golden_archives import GOLDEN_DIR

CASE = GOLDEN_DIR / "two_markers"


@pytest.fixture(autouse=True)
def conversion_dir(tmp_path, monkeypatch) -> None:
    for name in ("occurrence_long.tsv", "answers.yaml", "resolved_taxonomy.tsv"):
        shutil.copy(CASE / name, tmp_path / name)
    monkeypatch.chdir(tmp_path)


def _edit_answers(**changes) -> None:
    raw = yaml.safe_load(artifacts.ANSWERS.read_text())
    raw.update(changes)
    artifacts.ANSWERS.write_text(yaml.safe_dump(raw))


def _codes() -> list[str]:
    return [f["code"] for f in json.loads(artifacts.FINDINGS.read_text())]


def _findings() -> list[dict]:
    return json.loads(artifacts.FINDINGS.read_text())


def _occurrences() -> list[dict[str, str]]:
    return list(read_rows(Path("archive/occurrence.txt"), delimiter="\t"))


def _confirm(sheet: sheets.Sheet, body: str) -> None:
    sheet.confirmed.parent.mkdir(exist_ok=True)
    sheet.confirmed.write_text(body)


def _accept(sheet: sheets.Sheet) -> None:
    lines = sheet.proposal.read_text().splitlines()
    _confirm(sheet, next(line for line in lines if not line.startswith("#")) + "\n")


def _proposed_rows(sheet: sheets.Sheet) -> list[dict[str, str]]:
    return list(read_rows(sheet.proposal, delimiter="\t"))


def _confirm_rows(sheet: sheets.Sheet, rows: list[dict[str, str]]) -> None:
    write_tsv(rows, sheet.confirmed)


def _answer_control(sample_id: str, value: str) -> None:
    raw = yaml.safe_load(artifacts.ANSWERS.read_text())
    raw["controls"][sample_id] = {
        "value": value,
        "provenance": "the lab's sample sheet",
        "confirmed": "the lab manager",
    }
    artifacts.ANSWERS.write_text(yaml.safe_dump(raw))


def _accept_every_proposal() -> None:
    _answer_control("ExtractionBlank1", "control")
    for sheet in (sheets.TERM_MAPPING, sheets.TAXA, sheets.DERIVED_VALUES):
        _accept(sheet)


def test_unanswered_questions_halt_before_any_archive():
    _edit_answers(markers={}, controls={}, metadata={})
    result = packaging.build(Path())
    assert result.status == "needs_decision"
    keys = [missing.key for missing in result.missing_answers]
    assert keys[:2] == ["metadata.title", "metadata.creators"]
    assert keys[-3:] == ["markers.Leray-COI", "markers.MiFish-U", "controls.NC05"]
    assert not Path("archive").exists()
    assert "CONTROL_AMBIGUOUS" in _codes()


def test_a_missing_lock_is_reported_with_the_missing_answers():
    _edit_answers(controls={})
    artifacts.RESOLVED_TAXONOMY.unlink()
    result = packaging.build(Path())
    assert result.status == "needs_decision"
    assert [m.key for m in result.missing_answers] == ["controls.NC05"]
    assert "resolve-taxonomy" in result.detail


def test_a_build_reads_and_writes_only_the_conversion_directory_it_is_given(tmp_path, monkeypatch):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    result = packaging.build(tmp_path)
    assert result.status == "needs_review"
    assert (tmp_path / "archive" / artifacts.ZIP_NAME).exists()
    assert (tmp_path / sheets.TAXA.proposal).exists()
    assert list(elsewhere.iterdir()) == []


def test_findings_json_records_the_finding_a_build_halted_on():
    result = packaging.build(Path())
    (halt,) = [f for f in _findings() if f["code"] == "PROPOSAL_OPEN"]
    assert halt["message"] == result.detail
    _edit_answers(markers={})
    packaging.build(Path())
    assert "DECISION_REQUIRED" in _codes()


def test_the_report_lists_the_halt_as_an_open_question_and_not_as_an_error_to_resolve():
    packaging.build(Path())
    report = json.loads(Path("archive/CONVERSION_REPORT.json").read_text(encoding="utf-8"))
    assert "PROPOSAL_OPEN" in [group["code"] for group in report["open_questions"]]
    assert not [item for item in report["action_items"] if item.startswith("Resolve")]


def test_a_build_never_calls_the_gbif_validator(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("build called GBIF's validation API")

    monkeypatch.setattr(gbif_validator, "run_gbif_validation", refuse)
    assert packaging.build(Path()).status == "needs_review"


def test_a_missing_marker_answer_asks_for_provenance_and_a_confirmation():
    _edit_answers(markers={})
    (marker, *_) = [
        m for m in packaging.build(Path()).missing_answers if m.key.startswith("markers")
    ]
    assert "provenance: <" in marker.example
    assert "confirmed: <" in marker.example


def test_a_table_without_a_marker_column_asks_for_one_entry():
    Path("occurrence_long.tsv").write_text(
        "sampleID\tfeatureID\tcount\ttaxonomy\ns1\tf1\t3\td__Bacteria\n"
    )
    _edit_answers(markers={}, controls={})
    assert [m.key for m in packaging.build(Path()).missing_answers] == ["markers"]


def test_a_first_build_writes_the_archive_and_waits_on_its_proposals():
    result = packaging.build(Path())
    assert result.status == "needs_review"
    assert Path("archive/dwca.zip").exists()
    assert [review.sheet.name for review in result.open_sheets] == [
        "control_roster",
        "term_mapping",
        "taxa",
    ]
    assert all(sheet.proposal.exists() for sheet in sheets.SHEETS)


def test_accepting_every_proposal_finishes_the_build():
    packaging.build(Path())
    _accept_every_proposal()
    result = packaging.build(Path())
    assert result.status == "ok"
    assert result.open_sheets == []
    assert _codes().count("CONFIRMED_SHEET_APPLIED") == 3


def test_a_confirmed_sheet_holding_only_its_header_accepts_every_fresh_row():
    packaging.build(Path(), automatic=True)
    proposed = _occurrences()
    _accept_every_proposal()
    assert packaging.build(Path()).status == "ok"
    assert _occurrences() == proposed


def test_a_build_from_the_bundle_reads_its_confirmed_sheets(monkeypatch):
    packaging.build(Path())
    _accept_every_proposal()
    packaging.build(Path())
    shutil.copytree("archive/reproduce", "replayed")
    shutil.copy(artifacts.INTERMEDIATE, "replayed")
    monkeypatch.chdir("replayed")
    result = packaging.build(Path())
    assert result.status == "ok"
    assert _codes().count("CONFIRMED_SHEET_APPLIED") == 3


def test_a_confirmed_mapping_row_onto_a_resolved_taxon_term_stops_the_build():
    packaging.build(Path())
    _confirm(
        sheets.TERM_MAPPING,
        "source_column\ttarget\tbasis\tprovenance\tconfirmed\nlocality\tscientificName\texact\tPI\tPI\n",
    )
    result = packaging.build(Path())
    assert result.status == "error"
    assert "confirmed/taxa.tsv" in result.detail


def test_a_table_with_blank_sample_ids_is_refused_once_with_the_count():
    rows = list(read_rows(artifacts.INTERMEDIATE, delimiter="\t"))
    for row in rows:
        row["sampleID"] = ""
    write_tsv(rows, artifacts.INTERMEDIATE, columns=list(rows[0]))
    result = packaging.build(Path())
    assert (result.status, result.refused) == ("error", True)
    assert f"{len(rows)} row(s) have no sampleID" in result.detail
    assert "reader script" in result.detail
    assert "SAMPLE_ID_NOT_VERBATIM" not in result.detail


def test_a_confirmed_row_keeping_a_source_taxon_concept_id_stops_the_build_and_names_ncbi_taxid():
    rows = list(read_rows(artifacts.INTERMEDIATE, delimiter="\t"))
    for row in rows:
        row["taxonConceptID"] = "NCBI:txid8030"
    write_tsv(rows, artifacts.INTERMEDIATE, columns=list(rows[0]))
    _confirm(
        sheets.TERM_MAPPING,
        "source_column\ttarget\tbasis\tprovenance\tconfirmed\n"
        "taxonConceptID\ttaxonConceptID\texact\tPI\tPI\n",
    )
    result = packaging.build(Path())
    assert (result.status, result.refused) == ("error", True)
    assert "ncbi_taxid" in result.detail


def test_columns_the_confirmed_mapping_settles_leave_no_mapping_finding_about_them():
    rows = list(read_rows(artifacts.INTERMEDIATE, delimiter="\t"))
    for row in rows:
        row.update(Station_ID="Station_01", Location="English Bay")
    write_tsv(rows, artifacts.INTERMEDIATE, columns=list(rows[0]))
    mapping_codes = {"TERM_AMBIGUOUS", "TERM_TARGET_COLLISION"}

    def about_station() -> list[str]:
        return [f["code"] for f in _findings() if f["code"] in mapping_codes]

    packaging.build(Path())
    assert set(about_station()) == mapping_codes
    _confirm(
        sheets.TERM_MAPPING,
        "source_column\ttarget\tbasis\tprovenance\tconfirmed\n"
        "Location\tlocality\talias\tplace names\tPI: yes\n"
        "Station_ID\tlocationID\talias\tsite codes\tPI: yes\n",
    )
    packaging.build(Path())
    assert about_station() == []


def _add_column_matching_locality() -> None:
    rows = list(read_rows(artifacts.INTERMEDIATE, delimiter="\t"))
    for row in rows:
        row["Locality"] = "Puget Sound"
    write_tsv(rows, artifacts.INTERMEDIATE, columns=list(rows[0]))


def _review_of(result: BuildResult, sheet: sheets.Sheet) -> sheets.SheetReview:
    return next(review for review in result.sheets if review.sheet is sheet)


def _changed_row(sheet: sheets.Sheet) -> dict[str, str]:
    if sheet is sheets.TERM_MAPPING:
        return {"source_column": "Locality", "target": "waterBody", "basis": "ambiguous"}
    rows = _proposed_rows(sheet)
    if sheet is sheets.TAXA:
        (pisaster,) = [row for row in rows if row["scientificName"] == "Pisaster"]
        return pisaster | {
            "scientificName": "Pisaster ochraceus",
            "scientificNameID": "urn:lsid:marinespecies.org:taxname:240755",
            "taxonRank": "Species",
            "scientificNameAuthorship": "",
        }
    return rows[0] | {"count": "999"}


def _change_a_row(sheet: sheets.Sheet, provenance: str, confirmed: str = "") -> None:
    if sheet is sheets.TERM_MAPPING:
        _add_column_matching_locality()
    packaging.build(Path())
    _accept_every_proposal()
    _confirm_rows(
        sheet, [_changed_row(sheet) | {"provenance": provenance, "confirmed": confirmed}]
    )


REVIEWED_SHEETS = pytest.mark.parametrize(
    ("sheet", "column", "published"),
    [
        pytest.param(sheets.TERM_MAPPING, "waterBody", "Puget Sound", id="term_mapping"),
        pytest.param(sheets.TAXA, "scientificName", "Pisaster ochraceus", id="taxa"),
        pytest.param(sheets.DERIVED_VALUES, "organismQuantity", "999", id="derived_values"),
    ],
)


@REVIEWED_SHEETS
def test_a_row_nobody_confirmed_is_applied_and_holds_the_build_for_review(
    sheet, column, published
):
    _change_a_row(sheet, "from the field notes")
    result = packaging.build(Path())
    assert result.status == "needs_review"
    assert _review_of(result, sheet).rows.unconfirmed == 1
    assert result.unconfirmed_count == 1
    assert published in {row[column] for row in _occurrences()}


@REVIEWED_SHEETS
def test_automatic_accepts_a_row_nobody_confirmed_and_logs_it(sheet, column, published):
    _change_a_row(sheet, "from the field notes")
    assert packaging.build(Path(), automatic=True).status == "ok"
    assert "UNCONFIRMED_ACCEPTED" in _codes()


@REVIEWED_SHEETS
def test_a_row_a_person_confirmed_is_counted_as_confirmed(sheet, column, published):
    _change_a_row(sheet, "from the field notes", "PI: yes")
    result = packaging.build(Path())
    assert result.status == "ok"
    review = _review_of(result, sheet)
    assert (review.rows.changed, review.rows.unconfirmed) == (1, 0)


@REVIEWED_SHEETS
def test_a_row_a_machine_confirmed_refuses_the_sheet(sheet, column, published):
    _change_a_row(sheet, "from the field notes", " Agent. ")
    result = packaging.build(Path())
    assert (result.status, result.refused) == ("error", True)
    assert "names no person who replied" in result.detail


@REVIEWED_SHEETS
def test_a_row_changed_without_provenance_refuses_the_sheet(sheet, column, published):
    _change_a_row(sheet, "")
    result = packaging.build(Path())
    assert (result.status, result.refused) == ("error", True)
    assert sheet.confirmed.as_posix() in result.detail
    assert "nothing in the provenance column" in result.detail


def test_an_ambiguous_column_with_no_confirmed_row_waits_in_dynamic_properties():
    _add_column_matching_locality()
    result = packaging.build(Path())
    assert result.status == "needs_review"
    assert all(sheet.proposal.exists() for sheet in sheets.SHEETS)
    (mapping,) = [r for r in result.open_sheets if r.sheet is sheets.TERM_MAPPING]
    assert "1 ambiguous mapping(s)" in mapping.reason
    assert all("Locality" in json.loads(row["dynamicProperties"]) for row in _occurrences())


def test_a_confirmed_mapping_without_a_provenance_column_refuses_the_sheet():
    _add_column_matching_locality()
    packaging.build(Path())
    _confirm(sheets.TERM_MAPPING, "source_column\ttarget\tbasis\nLocality\twaterBody\tambiguous\n")
    result = packaging.build(Path())
    assert (result.status, result.refused) == ("error", True)
    assert "Locality" in result.detail
    assert "nothing in the provenance column" in result.detail


def test_a_refused_sheet_is_reported_with_the_missing_answers():
    packaging.build(Path())
    rows = _proposed_rows(sheets.TAXA)
    rows[0].update(scientificName="Aaptos", provenance="")
    _confirm_rows(sheets.TAXA, rows[:1])
    _edit_answers(controls={})
    result = packaging.build(Path())
    assert result.status == "needs_decision"
    assert [m.key for m in result.missing_answers] == ["controls.NC05"]
    assert "confirmed/taxa.tsv" in result.detail


def test_a_confirmed_mapping_row_left_as_proposed_needs_no_provenance():
    _add_column_matching_locality()
    packaging.build(Path())
    rows = [
        row
        for row in _proposed_rows(sheets.TERM_MAPPING)
        if not row["source_column"].startswith("#")
    ]
    for row in rows:
        if row["source_column"] == "Locality":
            row.update(target="waterBody", provenance="PI")
    _confirm_rows(sheets.TERM_MAPPING, rows)
    result = packaging.build(Path())
    assert not result.refused
    assert {row["waterBody"] for row in _occurrences()} == {"Puget Sound"}


def test_a_published_name_the_taxonomy_lock_does_not_give_its_id_stops_the_build():
    packaging.build(Path())
    rows = _proposed_rows(sheets.DERIVED_VALUES)
    rows[0].update(scientificName="Gnathostomata", provenance="a test")
    _confirm_rows(sheets.DERIVED_VALUES, rows[:1])
    result = packaging.build(Path())
    assert result.status == "error"
    assert "Gnathostomata" in result.detail


def test_an_audit_with_findings_is_reported_and_never_holds_the_build():
    packaging.build(Path())
    _accept_every_proposal()
    audit.record_audit(artifacts.AUDIT_RECORD, ["invented a depth"])
    result = packaging.build(Path())
    assert result.status == "ok"
    report = Path("archive/CONVERSION_REPORT.md").read_text(encoding="utf-8")
    assert "invented a depth" in report


def _let_an_agent_choose_the_publication_date() -> None:
    raw = yaml.safe_load(artifacts.ANSWERS.read_text())
    raw["metadata"]["pub_date"] = {"value": "2026", "provenance": "the year it was built"}
    artifacts.ANSWERS.write_text(yaml.safe_dump(raw))


def test_a_value_nobody_confirmed_holds_the_build_in_review():
    packaging.build(Path())
    _accept_every_proposal()
    _let_an_agent_choose_the_publication_date()
    result = packaging.build(Path())
    assert result.status == "needs_review"
    assert "metadata.pub_date" in result.detail
    assert result.unconfirmed == ["metadata.pub_date"]


def test_automatic_uses_every_unconfirmed_proposal_and_says_so():
    result = packaging.build(Path(), automatic=True)
    assert result.status == "ok"
    assert _codes().count("PROPOSAL_ACCEPTED") == 3


def _zip_members() -> set[str]:
    with zipfile.ZipFile("archive/dwca.zip") as archive:
        return set(archive.namelist())


def test_the_zip_holds_only_the_darwin_core_archive_and_the_reproduction_sits_beside_it():
    packaging.build(Path(), automatic=True)
    assert _zip_members() == {
        "occurrence.txt",
        "meta.xml",
        "eml.xml",
        "dnaderiveddata.txt",
        "extendedmeasurementorfact.txt",
    }
    assert Path("archive/reproduce/answers.yaml").is_file()
    assert Path("archive/CONVERSION_REPORT.md").is_file()


def test_a_rebuild_without_an_extension_leaves_no_copy_of_it_behind():
    packaging.build(Path(), automatic=True)
    assert "extendedmeasurementorfact.txt" in _zip_members()
    _edit_answers(build={"no_emof": True})
    packaging.build(Path(), automatic=True)
    assert "extendedmeasurementorfact.txt" not in _zip_members()
    assert not Path("archive/extendedmeasurementorfact.txt").exists()


def test_a_deleted_confirmed_sheet_leaves_the_bundle():
    packaging.build(Path())
    _accept(sheets.TERM_MAPPING)
    packaging.build(Path())
    sheets.TERM_MAPPING.confirmed.unlink()
    packaging.build(Path())
    assert not Path("archive/reproduce/confirmed/term_mapping.tsv").exists()


def _assert_refused(fact: str) -> None:
    result = packaging.build(Path(), automatic=True)
    assert (result.status, result.refused) == ("error", True)
    assert fact in result.detail


def _make_look_built(directory: Path) -> None:
    (directory / artifacts.BUNDLE_DIR).mkdir(parents=True)
    (directory / artifacts.BUNDLE_DIR / artifacts.CONFIG).write_text("steps: []\n")
    (directory / "dwca.zip").write_bytes(b"")


def test_a_build_never_empties_an_out_dir_holding_a_raw_input():
    Path("raw").mkdir()
    Path("raw/plates.xlsx").write_bytes(b"source")
    _make_look_built(Path("raw"))
    artifacts.CONFIG.write_text("steps: []\nraw_inputs: [raw/plates.xlsx]\n")
    _edit_answers(out_dir="raw")
    _assert_refused("plates.xlsx")
    assert Path("raw/plates.xlsx").read_bytes() == b"source"


def test_a_build_never_empties_an_out_dir_holding_the_sample_metadata():
    _make_look_built(Path("archive"))
    Path("archive/samples.tsv").write_text("sampleID\tsample_type\n")
    raw = yaml.safe_load(artifacts.ANSWERS.read_text())
    raw["filters"].update(sample_metadata="archive/samples.tsv", sample_type_col="sample_type")
    artifacts.ANSWERS.write_text(yaml.safe_dump(raw))
    _assert_refused("samples.tsv")
    assert Path("archive/samples.tsv").exists()


def test_a_build_never_empties_an_out_dir_holding_files_it_did_not_write():
    Path("notes").mkdir()
    Path("notes/plan.txt").write_text("mine")
    _edit_answers(out_dir="notes")
    _assert_refused("notes")
    assert Path("notes/plan.txt").read_text() == "mine"


def test_a_build_replaces_everything_in_the_archive_an_earlier_build_wrote():
    packaging.build(Path(), automatic=True)
    Path("archive/EVALUATION.md").write_text("of the earlier archive")
    packaging.build(Path(), automatic=True)
    assert Path("archive/dwca.zip").exists()
    assert not Path("archive/EVALUATION.md").exists()


def test_a_build_in_a_copy_never_touches_the_archive_of_the_original(tmp_path, monkeypatch):
    packaging.build(Path(), automatic=True)
    original = (tmp_path / "archive" / "dwca.zip").read_bytes()
    copy = tmp_path / "copy"
    shutil.copytree(tmp_path, copy, ignore=shutil.ignore_patterns("copy", "archive"))
    monkeypatch.chdir(copy)
    _edit_answers(out_dir=str(tmp_path / "archive"))
    _assert_refused("out_dir")
    assert (tmp_path / "archive" / "dwca.zip").read_bytes() == original


def test_a_build_that_stops_partway_through_writing_leaves_no_archive_behind(monkeypatch):
    def write_part_then_fail(**kwargs):
        kwargs["out_dir"].mkdir()
        (kwargs["out_dir"] / "occurrence.txt").write_text("half\n")
        raise writer.ArchiveBuildError("disk full")

    with monkeypatch.context() as patched:
        patched.setattr(writer, "write_archive_from_table", write_part_then_fail)
        assert packaging.build(Path(), automatic=True).status == "error"
    assert not Path("archive").exists()
    assert packaging.build(Path(), automatic=True).status == "ok"


def test_a_missing_raw_input_ends_the_build_naming_the_file_and_where_it_belongs():
    artifacts.CONFIG.write_text("steps: []\nraw_inputs: [input/absent.xlsx]\n")
    result = packaging.build(Path(), automatic=True)
    assert result.status == "error"
    assert str(Path("input", "absent.xlsx")) in result.detail
    assert str(Path.cwd() / "input" / "absent.xlsx") in result.detail
    assert not Path("archive").exists()


def test_a_raw_input_outside_the_conversion_ends_the_build_in_error(tmp_path_factory):
    outside = tmp_path_factory.mktemp("raw_inputs") / "asv.csv"
    outside.write_text("featureID\n")
    artifacts.CONFIG.write_text(f"steps: []\nraw_inputs: [{outside}]\n")
    result = packaging.build(Path(), automatic=True)
    assert result.status == "error"
    assert str(outside) in result.detail


def test_answers_build_cannot_read_withdraw_the_earlier_archive():
    packaging.build(Path(), automatic=True)
    _edit_answers(environment={})
    result = packaging.build(Path(), automatic=True)
    assert (result.status, result.refused) == ("error", True)
    assert "environment" in result.detail
    assert not Path("archive/dwca.zip").exists()


def test_a_missing_intermediate_table_removes_the_earlier_archive():
    packaging.build(Path(), automatic=True)
    artifacts.INTERMEDIATE.unlink()
    result = packaging.build(Path(), automatic=True)
    assert (result.status, result.refused) == ("error", True)
    assert not Path("archive").exists()


def test_a_malformed_confirmed_mapping_ends_the_build_in_error_without_an_archive():
    packaging.build(Path(), automatic=True)
    _confirm(sheets.TERM_MAPPING, "source_column\ttarget\tbasis\tprovenance\nfoo\tbar\n")
    result = packaging.build(Path(), automatic=True)
    assert result.status == "error"
    assert "confirmed/term_mapping.tsv" in result.detail
    assert not Path("archive").exists()


def test_a_build_reports_its_unmapped_columns_once():
    packaging.build(Path(), automatic=True)
    assert _codes().count("TERM_UNMAPPED") == 1


def test_a_value_nobody_confirmed_is_published_and_accepted_by_an_automatic_build():
    raw = yaml.safe_load(artifacts.ANSWERS.read_text())
    del raw["metadata"]["title"]["confirmed"]
    artifacts.ANSWERS.write_text(yaml.safe_dump(raw))
    result = packaging.build(Path(), automatic=True)
    assert result.status == "ok"
    assert result.unconfirmed == ["metadata.title"]
    (used,) = [f for f in _findings() if f["code"] == "UNCONFIRMED_ACCEPTED"]
    assert "metadata.title" in used["message"]
    assert raw["metadata"]["title"]["value"] in Path("archive/eml.xml").read_text()


def test_a_publication_date_and_license_left_blank_hold_even_an_automatic_build():
    raw = yaml.safe_load(artifacts.ANSWERS.read_text())
    for name in ("pub_date", "license"):
        raw["metadata"][name] = {"value": "", "provenance": "waiting on the provider"}
    artifacts.ANSWERS.write_text(yaml.safe_dump(raw))
    result = packaging.build(Path(), automatic=True)
    assert result.status == "needs_review"
    assert result.blank_metadata == ["license", "pub_date"]
    assert "metadata.license: blank" in result.detail
    eml = Path("archive/eml.xml").read_text()
    assert "<pubDate>" not in eml
    assert "<intellectualRights>" not in eml


def test_a_title_and_creators_left_blank_with_provenance_are_left_out_and_still_build():
    raw = yaml.safe_load(artifacts.ANSWERS.read_text())
    for name in ("title", "creators"):
        raw["metadata"][name] = {"value": "", "provenance": "the PI is choosing one"}
    artifacts.ANSWERS.write_text(yaml.safe_dump(raw))
    result = packaging.build(Path(), automatic=True)
    assert result.status == "needs_review"
    assert result.missing_eml_elements == ["creator", "title"]
    eml = Path("archive/eml.xml").read_text()
    assert "<title" not in eml
    assert "<creator>" not in eml


def test_a_marker_constant_reaches_only_that_markers_rows():
    raw = yaml.safe_load(artifacts.ANSWERS.read_text())
    for marker, protocol in (("Leray-COI", "COI protocol"), ("MiFish-U", "12S protocol")):
        raw["markers"][marker]["constants"] = {
            "sop": {"value": protocol, "provenance": "methods.pdf"}
        }
    artifacts.ANSWERS.write_text(yaml.safe_dump(raw))
    packaging.build(Path(), automatic=True)
    rows = read_rows(Path("archive/dnaderiveddata.txt"), delimiter="\t")
    by_marker = {(row["target_gene"], row["sop"]) for row in rows}
    assert by_marker == {("COI", "COI protocol"), ("12S rRNA", "12S protocol")}
    assert "(constant MiFish-U)\tsop\tconstant\tmethods.pdf" in (artifacts.MAPPING.read_text())


def test_a_constant_that_would_replace_values_from_the_data_stops_the_build():
    _edit_answers(constants={"sampleSizeValue": {"value": "4", "provenance": "PI"}})
    result = packaging.build(Path(), automatic=True)
    assert result.status == "error"
    assert "sampleSizeValue" in result.detail


def test_excusing_a_term_every_archive_needs_ends_the_build_in_error():
    _edit_answers(term_states={"impossible": {"occurrenceID": "user:PI, never recorded"}})
    result = packaging.build(Path(), automatic=True)
    assert result.status == "error"
    assert "occurrenceID" in result.detail


def test_human_rows_with_no_answer_on_excluding_them_are_asked_about():
    raw = yaml.safe_load(artifacts.ANSWERS.read_text())
    del raw["filters"]["exclude_human"]
    artifacts.ANSWERS.write_text(yaml.safe_dump(raw))
    result = packaging.build(Path(), automatic=True)
    assert result.status == "needs_decision"
    assert [m.key for m in result.missing_answers] == ["filters.exclude_human"]
    assert not Path("archive").exists()


def _ask_about_human_rows() -> questions.MissingAnswer:
    raw = yaml.safe_load(artifacts.ANSWERS.read_text())
    del raw["filters"]["exclude_human"]
    artifacts.ANSWERS.write_text(yaml.safe_dump(raw))
    result = packaging.build(Path())
    return next(m for m in result.missing_answers if m.key == "filters.exclude_human")


def test_a_count_that_is_not_a_number_stops_the_build_as_assemble_reports_it():
    _set_column("count", "NA")
    result = packaging.build(Path(), automatic=True)
    assert (result.status, result.refused) == ("error", True)
    assert "count that is not a finite number" in result.detail


def test_the_human_question_calls_counts_reads_only_when_they_are():
    _edit_answers(
        constants={"organismQuantityType": {"value": "relative abundance", "provenance": "PI"}}
    )
    assert "reads" not in _ask_about_human_rows().question


def test_every_decision_is_asked_in_one_halt():
    raw = yaml.safe_load(artifacts.ANSWERS.read_text())
    del raw["filters"]["exclude_human"]
    raw["markers"] = {}
    artifacts.ANSWERS.write_text(yaml.safe_dump(raw))
    keys = [m.key for m in packaging.build(Path()).missing_answers]
    assert keys == ["markers.Leray-COI", "markers.MiFish-U", "filters.exclude_human"]


def test_a_missing_person_is_asked_for_as_a_list_of_people():
    _edit_answers(metadata={})
    (creators,) = [
        m for m in packaging.build(Path()).missing_answers if m.key == "metadata.creators"
    ]
    assert "surname" in creators.example


def test_a_proposal_is_rewritten_from_scratch_on_every_build():
    packaging.build(Path())
    sheets.CONTROL_ROSTER.proposal.write_text("edited by hand\n")
    packaging.build(Path())
    assert "edited by hand" not in sheets.CONTROL_ROSTER.proposal.read_text()


def test_the_columns_synthesize_ids_consumes_are_not_offered_for_review():
    packaging.build(Path())
    proposed = {
        row.source_column for row in read_mapping_tsv(sheets.TERM_MAPPING.proposal.read_text())
    }
    assert {"sampleID", "featureID", "count"}.isdisjoint(proposed)


def test_build_writes_nothing_between_its_steps():
    before = set(Path().iterdir())
    packaging.build(Path(), automatic=True)
    written = {path.name for path in set(Path().iterdir()) - before}
    assert written == {
        "archive",
        "proposed",
        "findings.json",
        "term_mapping.tsv",
        "term_states.tsv",
        "excluded_rows_report.tsv",
        "conversion.yaml",
        "REVIEW.md",
        "REVIEW.html",
    }


def test_build_never_writes_the_files_a_person_owns():
    owned = {path: path.read_bytes() for path in (artifacts.ANSWERS, artifacts.INTERMEDIATE)}
    packaging.build(Path())
    packaging.build(Path())
    assert {path: path.read_bytes() for path in owned} == owned


def test_an_answer_decides_which_samples_are_controls():
    _answer_control("PS03", "control")
    _answer_control("ExtractionBlank1", "sample")
    packaging.build(Path())
    published = {row["materialSampleID"] for row in _occurrences()}
    assert "PS03" not in published
    assert "ExtractionBlank1" in published


def test_a_control_excluded_by_its_sample_id_alone_waits_for_an_answer():
    result = packaging.build(Path())
    (roster,) = [r for r in result.open_sheets if r.sheet is sheets.CONTROL_ROSTER]
    assert "ExtractionBlank1" in roster.reason
    _answer_control("ExtractionBlank1", "control")
    result = packaging.build(Path())
    assert sheets.CONTROL_ROSTER not in [r.sheet for r in result.open_sheets]


def test_an_excluded_control_is_disclosed_once_in_the_methods_not_on_every_row():
    _answer_control("PS03", "control")
    packaging.build(Path())
    assert not any(row.get("informationWithheld") for row in _occurrences())
    methods = Path("archive/eml.xml").read_text().split("<methods>")[1]
    assert "control/blank sample(s) excluded" in methods


def _set_column(name: str, value: str) -> None:
    rows = list(read_rows(artifacts.INTERMEDIATE, delimiter="\t"))
    for row in rows:
        row[name] = value
    write_tsv(rows, artifacts.INTERMEDIATE, columns=list(rows[0]))


def test_a_source_column_named_for_a_term_resolve_taxonomy_writes_stops_the_build():
    _set_column("taxonRank", "Wrongrank")
    result = packaging.build(Path(), automatic=True)
    assert (result.status, result.refused) == ("error", True)
    assert all(word in result.detail for word in ("taxonRank", "source_taxon_id"))


def test_every_row_keeps_its_source_taxonomy_as_its_verbatim_identification():
    packaging.build(Path(), automatic=True)
    source = {
        f"{row['sampleID']}:{row['featureID']}": row["taxonomy"]
        for row in read_rows(artifacts.INTERMEDIATE, delimiter="\t")
    }
    published = {
        row["occurrenceID"].split(":", 1)[1]: row["verbatimIdentification"]
        for row in _occurrences()
    }
    assert published == {key: source[key] for key in published}


def test_a_taxon_id_added_after_resolving_stops_the_build_until_resolved_again():
    _set_column("ncbi_taxid", "8030")
    result = packaging.build(Path(), automatic=True)
    assert result.status == "error"
    assert "resolve-taxonomy" in result.detail


def test_a_build_reports_the_findings_resolving_left_in_the_lock():
    lock = list(read_rows(artifacts.RESOLVED_TAXONOMY, delimiter="\t"))
    for row in lock:
        row["findings"] = "TAXON_FUZZY" if row["scientificName"] == "Pisaster" else ""
    write_tsv(lock, artifacts.RESOLVED_TAXONOMY)
    result = packaging.build(Path(), automatic=True)
    assert "TAXON_FUZZY" in _codes()
    taxa = next(review for review in result.sheets if review.sheet == sheets.TAXA)
    assert "TAXON_FUZZY" in taxa.reason


def test_taxonomy_settings_changed_since_resolving_stop_the_build_until_resolved_again():
    _edit_answers(taxonomy={"require_confident": True})
    result = packaging.build(Path(), automatic=True)
    assert result.status == "error"
    assert "resolve-taxonomy" in result.detail
    assert "require_confident: true" in result.detail


def test_a_marker_given_its_own_taxonomy_settings_needs_its_lineages_resolved_again():
    raw = yaml.safe_load(artifacts.ANSWERS.read_text())
    raw["markers"]["MiFish-U"]["taxonomy"] = {"registers": ["worms"]}
    artifacts.ANSWERS.write_text(yaml.safe_dump(raw))
    result = packaging.build(Path(), automatic=True)
    assert result.status == "error"
    assert "resolve-taxonomy" in result.detail


def test_kingdom_exclusions_follow_each_marker_target():
    _edit_answers(
        filters={
            "exclude_human": {"value": True, "provenance": "a test"},
            "exclude_kingdoms": ["Animalia"],
        },
        markers={
            "Leray-COI": {"target": "bacteria", "provenance": "a test of scope"},
            "MiFish-U": {"target": "vertebrates", "provenance": "MiFish-U primers"},
        },
    )
    packaging.build(Path())
    markers = {json.loads(row["dynamicProperties"])["marker"] for row in _occurrences()}
    assert markers == {"MiFish-U"}


def test_a_lock_missing_a_lineage_stops_the_build_and_says_how_to_resolve():
    rows = list(read_rows(artifacts.RESOLVED_TAXONOMY, delimiter="\t"))
    write_tsv(rows[1:], artifacts.RESOLVED_TAXONOMY)
    result = packaging.build(Path())
    assert result.status == "error"
    assert "`edna2dwc resolve-taxonomy`" in result.detail


def test_an_absent_lock_stops_the_build_without_asking_a_register(monkeypatch):
    artifacts.RESOLVED_TAXONOMY.unlink()

    def refuse(**_) -> CommandResult:
        raise AssertionError("build asked a register")

    monkeypatch.setattr(resolve_taxonomy, "step", refuse)
    result = packaging.build(Path())
    assert result.status == "error"
    assert "`edna2dwc resolve-taxonomy`" in result.detail
    assert not Path("archive").exists()


def test_the_bundle_carries_what_a_replay_needs():
    packaging.build(Path())
    _accept(sheets.TERM_MAPPING)
    packaging.build(Path())
    bundled = {
        path.relative_to("archive/reproduce").as_posix()
        for path in Path("archive/reproduce").rglob("*")
        if path.is_file()
    }
    assert bundled == {
        "answers.yaml",
        "conversion.yaml",
        "resolved_taxonomy.tsv",
        "confirmed/term_mapping.tsv",
        "justfile",
    }


def _rename_column(old: str, new: str) -> None:
    rows = list(read_rows(artifacts.INTERMEDIATE, delimiter="\t"))
    renamed = [{(new if key == old else key): value for key, value in row.items()} for row in rows]
    write_tsv(renamed, artifacts.INTERMEDIATE, columns=list(renamed[0]))


def test_a_sequence_column_under_another_name_gives_every_row_a_taxon_id():
    _rename_column("sequence", "asv_sequence")
    packaging.build(Path(), automatic=True)
    assert all(row["taxonID"].startswith("ASV:") for row in _occurrences())
    assert "TAXON_ID_BLANK" not in _codes()


def _blank_the_marker_of(sample_id: str, *, keeping_only: str = "") -> None:
    rows = list(read_rows(artifacts.INTERMEDIATE, delimiter="\t"))
    kept = [row for row in rows if keeping_only in ("", row["marker"])]
    for row in kept:
        if row["sampleID"] == sample_id:
            row["marker"] = ""
    write_tsv(kept, artifacts.INTERMEDIATE, columns=list(rows[0]))


def test_rows_with_a_blank_marker_beside_marked_rows_take_no_marker_constant():
    _blank_the_marker_of("PS01", keeping_only="MiFish-U")
    raw = yaml.safe_load(artifacts.ANSWERS.read_text())
    raw["markers"] = {"MiFish-U": raw["markers"]["MiFish-U"]}
    raw["markers"]["MiFish-U"]["constants"] = {
        "sop": {"value": "12S protocol", "provenance": "methods.pdf"}
    }
    artifacts.ANSWERS.write_text(yaml.safe_dump(raw))
    packaging.build(Path(), automatic=True)
    marked = [
        row
        for row in _occurrences()
        if json.loads(row["dynamicProperties"] or "{}").get("marker") == "MiFish-U"
    ]
    dna_rows = read_rows(Path("archive/dnaderiveddata.txt"), delimiter="\t")
    assert len([row for row in dna_rows if row["sop"]]) == len(marked)
    assert "MARKER_INCOMPLETE" in _codes()


def test_rows_with_a_blank_marker_do_not_ask_for_a_marker_answer():
    _blank_the_marker_of("PS01")
    result = packaging.build(Path(), automatic=True)
    assert result.status == "needs_review"
    assert "MARKER_INCOMPLETE" in result.detail


def _set_fractional_counts(marker: str) -> None:
    rows = list(read_rows(artifacts.INTERMEDIATE, delimiter="\t"))
    for row in rows:
        if row["marker"] == marker:
            row["count"] = "0.25"
    write_tsv(rows, artifacts.INTERMEDIATE, columns=list(rows[0]))


def _units_by_marker() -> set[tuple[str, str, str]]:
    return {
        (
            json.loads(row["dynamicProperties"])["marker"],
            row["organismQuantityType"],
            row.get("sampleSizeUnit", ""),
        )
        for row in _occurrences()
    }


def _add_constant(term: str, value: str) -> None:
    raw = yaml.safe_load(artifacts.ANSWERS.read_text())
    raw["constants"][term] = {"value": value, "provenance": "the methods"}
    artifacts.ANSWERS.write_text(yaml.safe_dump(raw))


def _move_samples_onto_land() -> None:
    artifacts.INTERMEDIATE.write_text(
        artifacts.INTERMEDIATE.read_text().replace("47.6000\t-122.4500", "47.6550\t-122.3050")
    )


def test_a_country_code_constant_the_coordinates_contradict_is_reported():
    _move_samples_onto_land()
    _add_constant("countryCode", "CA")
    packaging.build(Path(), automatic=True)
    assert "CONSTANT_OVERWROTE_MAPPED_VALUE" not in _codes()
    assert "COUNTRY_CODE_CONTRADICTS_COORDINATES" in _codes()


def test_a_datum_constant_names_the_footprint_reference_system():
    _add_constant("geodeticDatum", "EPSG:4326")
    packaging.build(Path(), automatic=True)
    assert {row["footprintSRS"] for row in _occurrences() if row["footprintWKT"]} == {"EPSG:4326"}


def test_counts_are_published_as_reads_by_default():
    packaging.build(Path(), automatic=True)
    assert {(quantity, size) for _, quantity, size in _units_by_marker()} == {
        ("DNA sequence reads", "DNA sequence reads")
    }


def test_counts_that_are_not_reads_label_the_counts_and_sum_no_sample_size():
    _edit_answers(
        constants={"organismQuantityType": {"value": "relative abundance", "provenance": "PI"}}
    )
    result = packaging.build(Path(), automatic=True)
    assert result.status == "ok"
    assert {(quantity, size) for _, quantity, size in _units_by_marker()} == {
        ("relative abundance", "")
    }
    assert not any(row.get("sampleSizeValue") for row in _occurrences())


def test_counts_that_are_not_whole_numbers_ask_what_they_measure():
    _set_fractional_counts("MiFish-U")
    result = packaging.build(Path(), automatic=True)
    assert result.status == "needs_decision"
    assert [m.key for m in result.missing_answers] == [
        "markers.MiFish-U.constants.organismQuantityType"
    ]
    assert not Path("archive").exists()


def test_a_marker_quantity_type_answers_that_markers_fractional_counts():
    _set_fractional_counts("MiFish-U")
    raw = yaml.safe_load(artifacts.ANSWERS.read_text())
    raw["markers"]["MiFish-U"]["constants"] = {
        "organismQuantityType": {"value": "relative abundance", "provenance": "PI"}
    }
    artifacts.ANSWERS.write_text(yaml.safe_dump(raw))
    packaging.build(Path(), automatic=True)
    assert {(marker, quantity) for marker, quantity, _ in _units_by_marker()} == {
        ("MiFish-U", "relative abundance"),
        ("Leray-COI", "DNA sequence reads"),
    }


def test_a_unit_from_answers_reaches_the_measurement_its_header_leaves_unitless():
    _rename_column("salinity_psu", "salinity")
    _edit_answers(units={"salinity": {"value": "PSU", "provenance": "methods.pdf"}})
    packaging.build(Path(), automatic=True)
    measurements = read_rows(Path("archive/extendedmeasurementorfact.txt"), delimiter="\t")
    units = {
        row["measurementUnit"] for row in measurements if row["measurementType"] == "salinity"
    }
    assert units == {"PSU"}


def test_a_unit_from_answers_overrides_the_one_its_header_names():
    _edit_answers(units={"salinity_psu": {"value": "ppt", "provenance": "PI"}})
    packaging.build(Path(), automatic=True)
    measurements = read_rows(Path("archive/extendedmeasurementorfact.txt"), delimiter="\t")
    units = {
        row["measurementUnit"] for row in measurements if row["measurementType"] == "salinity"
    }
    assert units == {"ppt"}
    (proposed,) = [
        row
        for row in _proposed_rows(sheets.TERM_MAPPING)
        if row["source_column"] == "salinity_psu"
    ]
    assert proposed["measurement"] == "measurementType=salinity; measurementUnit=ppt (from units:)"
    assert _codes().count("MEASUREMENT_UNIT_OVERRIDDEN") == 1


def test_the_proposal_names_each_column_that_becomes_measurement_rows():
    packaging.build(Path())
    rows = {row["source_column"]: row for row in _proposed_rows(sheets.TERM_MAPPING)}
    assert (rows["salinity_psu"]["target"], rows["salinity_psu"]["basis"]) == (
        "extendedmeasurementorfact",
        "measurement",
    )
    assert rows["salinity_psu"]["measurement"] == (
        "measurementType=salinity; measurementUnit=PSU (from the header)"
    )


def _rename_markers(names: dict[str, str]) -> None:
    rows = list(read_rows(artifacts.INTERMEDIATE, delimiter="\t"))
    for row in rows:
        row["marker"] = names.get(row["marker"], row["marker"])
    write_tsv(rows, artifacts.INTERMEDIATE, columns=list(rows[0]))
    raw = yaml.safe_load(artifacts.ANSWERS.read_text())
    raw["markers"] = {names.get(name, name): entry for name, entry in raw["markers"].items()}
    artifacts.ANSWERS.write_text(yaml.safe_dump(raw))


def test_a_marker_named_for_its_rrna_gene_stays_a_marker_and_not_a_measurement():
    _rename_markers({"MiFish-U": "12S", "Leray-COI": "18S"})
    packaging.build(Path(), automatic=True)
    rows = {row["source_column"]: row for row in _proposed_rows(sheets.TERM_MAPPING)}
    assert rows["marker"]["target"] != "extendedmeasurementorfact"
    measurements = read_rows(Path("archive/extendedmeasurementorfact.txt"), delimiter="\t")
    assert "marker" not in {row["measurementType"] for row in measurements}
    assert {json.loads(row["dynamicProperties"])["marker"] for row in _occurrences()} == {
        "12S",
        "18S",
    }


def test_a_gene_column_of_rrna_names_is_not_proposed_as_measurements():
    rows = list(read_rows(artifacts.INTERMEDIATE, delimiter="\t"))
    for row in rows:
        row["gene"] = "18S" if row["marker"] == "Leray-COI" else "12S"
    write_tsv(rows, artifacts.INTERMEDIATE, columns=list(rows[0]))
    packaging.build(Path())
    rows = {row["source_column"]: row for row in _proposed_rows(sheets.TERM_MAPPING)}
    assert (rows["gene"]["target"], rows["gene"]["basis"]) == ("", "unmapped")


def test_a_confirmed_dynamic_properties_row_keeps_a_column_out_of_the_measurements():
    _confirm_rows(
        sheets.TERM_MAPPING,
        [
            {
                "source_column": "salinity_psu",
                "target": "dynamicProperties",
                "basis": "measurement",
                "provenance": "PI",
            }
        ],
    )
    packaging.build(Path(), automatic=True)
    measurements = read_rows(Path("archive/extendedmeasurementorfact.txt"), delimiter="\t")
    assert "salinity" not in {row["measurementType"] for row in measurements}
    assert all("salinity_psu" in json.loads(row["dynamicProperties"]) for row in _occurrences())


def test_an_ambiguous_numeric_column_waits_in_dynamic_properties_and_publishes_no_measurement():
    rows = list(read_rows(artifacts.INTERMEDIATE, delimiter="\t"))
    for row in rows:
        row["latitude"] = row["decimalLatitude"]
    write_tsv(rows, artifacts.INTERMEDIATE, columns=list(rows[0]))
    packaging.build(Path(), automatic=True)
    proposed = {row["source_column"]: row for row in _proposed_rows(sheets.TERM_MAPPING)}
    assert proposed["latitude"]["basis"] == "ambiguous"
    measurements = read_rows(Path("archive/extendedmeasurementorfact.txt"), delimiter="\t")
    assert "latitude" not in {row["measurementType"] for row in measurements}
    assert all("latitude" in json.loads(row["dynamicProperties"]) for row in _occurrences())


WINDSOR = ("42.30", "-83.03")


def _place_every_sample_in_windsor(country_column: str, country_code: str) -> None:
    rows = list(read_rows(artifacts.INTERMEDIATE, delimiter="\t"))
    for row in rows:
        row["decimalLatitude"], row["decimalLongitude"] = WINDSOR
        row[country_column] = country_code
    write_tsv(rows, artifacts.INTERMEDIATE, columns=list(rows[0]))


@pytest.mark.parametrize("country_column", ["countryCode", "country_code"])
def test_a_source_country_code_the_coordinates_contradict_is_kept_and_reported(country_column):
    _place_every_sample_in_windsor(country_column, "US")
    packaging.build(Path(), automatic=True)
    assert {row["countryCode"] for row in _occurrences()} == {"US"}
    assert "COUNTRY_CODE_CONTRADICTS_COORDINATES" in _codes()


def test_a_blank_source_country_code_is_derived_from_the_coordinates():
    _place_every_sample_in_windsor("country_code", "")
    packaging.build(Path(), automatic=True)
    assert {row["countryCode"] for row in _occurrences()} == {"CA"}
    assert "COUNTRY_CODE_CONTRADICTS_COORDINATES" not in _codes()


def test_capitalized_coordinate_columns_derive_a_country_code_and_footprint():
    _rename_column("decimalLatitude", "Latitude")
    _rename_column("decimalLongitude", "Longitude")
    packaging.build(Path(), automatic=True)
    assert {row["countryCode"] for row in _occurrences()} == {"US"}
    assert all(row["footprintWKT"].startswith("POINT (-122.") for row in _occurrences())


def test_country_and_footprint_follow_a_confirmed_coordinate_swap():
    rows = list(read_rows(artifacts.INTERMEDIATE, delimiter="\t"))
    for row in rows:
        row["decimalLatitude"], row["decimalLongitude"] = reversed(WINDSOR)
    write_tsv(rows, artifacts.INTERMEDIATE, columns=list(rows[0]))
    _rename_column("decimalLatitude", "Latitude")
    _rename_column("decimalLongitude", "Longitude")
    _confirm_rows(
        sheets.TERM_MAPPING,
        [
            {
                "source_column": "Latitude",
                "target": "decimalLongitude",
                "basis": "unmapped",
                "provenance": "PI",
            },
            {
                "source_column": "Longitude",
                "target": "decimalLatitude",
                "basis": "unmapped",
                "provenance": "PI",
            },
        ],
    )
    packaging.build(Path(), automatic=True)
    published = {
        (row["decimalLatitude"], row["countryCode"], row["footprintWKT"]) for row in _occurrences()
    }
    assert published == {("42.30", "CA", "POINT (-83.03 42.3)")}


def _zero_the_counts_of(sample_id: str) -> int:
    rows = list(read_rows(artifacts.INTERMEDIATE, delimiter="\t"))
    zeroed = [row for row in rows if row["sampleID"] == sample_id]
    for row in zeroed:
        row["count"] = "0"
    write_tsv(rows, artifacts.INTERMEDIATE, columns=list(rows[0]))
    return len(zeroed)


def test_zero_counts_stop_the_build_unless_absences_are_published():
    _zero_the_counts_of("PS01")
    result = packaging.build(Path(), automatic=True)
    assert result.status == "error"
    assert "ZERO_COUNTS_KEPT" in result.detail
    assert "emit_absences" in result.detail
    assert "--keep-zeros" in result.detail


def test_zero_counts_only_in_an_excluded_control_do_not_stop_the_build():
    _answer_control("PS03", "control")
    _zero_the_counts_of("PS03")
    packaging.build(Path(), automatic=True)
    assert "ZERO_COUNTS_KEPT" not in _codes()


def test_zero_counts_are_published_as_absent_under_a_targeted_assay():
    zeroed = _zero_the_counts_of("PS01")
    _edit_answers(
        term_states={"assay_type": "targeted_assay"}, derive_fields={"emit_absences": True}
    )
    _add_constant("pcr_primer_lod", "3 copies/reaction")
    packaging.build(Path(), automatic=True)
    assert "ROW_ACCOUNTING_MISMATCH" not in _codes()
    absent = [row for row in _occurrences() if row["occurrenceStatus"] == "absent"]
    assert len(absent) == zeroed


def test_records_on_land_wait_for_an_adjudication_rather_than_stop_the_build():
    _place_every_sample_in_windsor("countryCode", "CA")
    result = packaging.build(Path(), automatic=True)
    assert result.status == "needs_review"
    assert "ON_LAND" in result.detail
    assert Path("archive/dwca.zip").exists()
    _edit_answers(
        adjudications={
            "ON_LAND": {
                "status": "accepted",
                "provenance": "shoreline sites",
                "confirmed": "PI: yes",
            }
        }
    )
    assert packaging.build(Path(), automatic=True).status == "ok"


def test_records_on_land_an_agent_accepted_still_wait_for_a_person_under_automatic():
    _place_every_sample_in_windsor("countryCode", "CA")
    accepted = {"status": "accepted", "provenance": "the sites are on the shore"}
    _edit_answers(adjudications={"ON_LAND": accepted})
    result = packaging.build(Path(), automatic=True)
    assert result.status == "needs_review"
    assert "ON_LAND" in result.detail
    assert result.unconfirmed == ["adjudications.ON_LAND"]


def test_a_judged_finding_an_agent_accepted_still_waits_for_a_person_under_automatic():
    _make_event_dates_unconvertible()
    accepted = {"status": "accepted", "provenance": "dates kept in verbatimEventDate"}
    _edit_answers(adjudications={"TERM_FORMAT_UNCONVERTIBLE": accepted})
    result = packaging.build(Path(), automatic=True)
    assert result.status == "needs_review"
    assert "TERM_FORMAT_UNCONVERTIBLE" in result.detail


def _exclude_taxa(marker: str, names: list[str]) -> None:
    raw = yaml.safe_load(artifacts.ANSWERS.read_text())
    raw["markers"][marker]["exclude_taxa"] = {
        "value": names,
        "provenance": "methods.pdf p3",
    }
    artifacts.ANSWERS.write_text(yaml.safe_dump(raw))


def test_a_taxon_exclusion_removes_its_rows_from_that_marker_only():
    _exclude_taxa("Leray-COI", ["Mollusca"])
    packaging.build(Path())
    names = {row["scientificName"] for row in _occurrences()}
    assert not any(name.startswith("Mytilus") for name in names)
    assert any(name.startswith("Calanus") for name in names)
    excluded = list(read_rows(artifacts.EXCLUDED_ROWS_REPORT, delimiter="\t"))
    taxon_rows = [row for row in excluded if row["exclusion_reason"] == "taxon:Mollusca"]
    assert taxon_rows and {row["marker"] for row in taxon_rows} == {"Leray-COI"}
    assert any(
        f["code"] == "CONTAMINANT_EXCLUDED" and "Mollusca" in f["message"] for f in _findings()
    )


def test_a_taxon_exclusion_matches_a_name_only_the_source_lineage_gives():
    _exclude_taxa("Leray-COI", ["Eukaryota"])
    packaging.build(Path())
    markers = {json.loads(row["dynamicProperties"])["marker"] for row in _occurrences()}
    assert markers == {"MiFish-U"}


def _filters(**columns) -> dict:
    raw = yaml.safe_load(artifacts.ANSWERS.read_text())
    return {**raw["filters"], **columns}


@pytest.mark.parametrize(
    ("section", "key"),
    [
        ("filters", "occurrence_type_col"),
        ("derive_fields", "timestamp_col_a"),
        ("derive_fields", "timestamp_col_b"),
    ],
)
def test_a_column_answers_yaml_names_that_the_table_lacks_stops_the_build(section, key):
    if section == "filters":
        _edit_answers(filters=_filters(**{key: "sample_typ"}))
    else:
        _edit_answers(derive_fields={key: "sample_typ"})

    result = packaging.build(Path(), automatic=True)

    assert result.status == "error"
    assert f"{section}.{key}" in result.detail
    assert "'sample_typ'" in result.detail


@pytest.mark.parametrize(
    ("metadata", "type_column", "named"),
    [
        (
            {"sampleID": "ExtractionBlank1", "type": "blank"},
            "typ",
            ["filters.sample_type_col", "'typ'"],
        ),
        (
            {"sample": "ExtractionBlank1", "type": "blank"},
            "type",
            ["filters.sample_metadata", "sampleID"],
        ),
    ],
)
def test_sample_metadata_that_lacks_a_column_the_answers_need_stops_the_build(
    metadata, type_column, named
):
    write_tsv([metadata], Path("samples.tsv"))
    _edit_answers(filters=_filters(sample_metadata="samples.tsv", sample_type_col=type_column))

    result = packaging.build(Path(), automatic=True)

    assert result.status == "error"
    assert all(word in result.detail for word in named)


def _map_columns(values_by_target: dict[str, tuple[str, str]]) -> None:
    for source_column, value in values_by_target.values():
        _set_column(source_column, value)
    _confirm_rows(
        sheets.TERM_MAPPING,
        [
            {
                "source_column": source_column,
                "target": target,
                "basis": "unmapped",
                "provenance": "PI",
            }
            for target, (source_column, _value) in values_by_target.items()
        ],
    )


@pytest.mark.parametrize("size_column", ["library_size", "total_reads"])
def test_a_mapped_sample_size_is_kept_with_its_mapped_unit(size_column):
    _map_columns(
        {"sampleSizeValue": (size_column, "777"), "sampleSizeUnit": ("size_unit", "reads")}
    )
    packaging.build(Path(), automatic=True)
    published = {(row["sampleSizeValue"], row["sampleSizeUnit"]) for row in _occurrences()}
    assert published == {("777", "reads")}
    assert "SAMPLE_SIZE_SUPPLIED" in _codes()


@pytest.mark.parametrize("size_column", ["library_size", "total_reads"])
def test_a_mapped_sample_size_without_a_unit_stops_the_build(size_column):
    _map_columns({"sampleSizeValue": (size_column, "777")})
    result = packaging.build(Path(), automatic=True)
    assert result.status == "error"
    assert "TERM_PAIR_INCOMPLETE" in _codes()


TRANSECT = "LINESTRING (-122.45 47.6, -122.44 47.61)"


def test_a_footprint_in_a_mapped_column_is_kept():
    _map_columns({"footprintWKT": ("a_wkt", TRANSECT), "footprintSRS": ("a_srs", "EPSG:4269")})
    packaging.build(Path(), automatic=True)
    published = {(row["footprintWKT"], row["footprintSRS"]) for row in _occurrences()}
    assert published == {(TRANSECT, "EPSG:4269")}


def _make_event_dates_unconvertible() -> None:
    rows = list(read_rows(artifacts.INTERMEDIATE, delimiter="\t"))
    for row in rows:
        row["eventDate"] = "1/20/2015"
    write_tsv(rows, artifacts.INTERMEDIATE, columns=list(rows[0]))


def test_a_finding_that_blanks_published_values_waits_for_an_adjudication_even_under_automatic():
    _make_event_dates_unconvertible()
    result = packaging.build(Path(), automatic=True)
    assert result.status == "needs_review"
    assert "TERM_FORMAT_UNCONVERTIBLE" in result.detail
    assert Path("archive/dwca.zip").exists()
    assert {row["eventDate"] for row in _occurrences()} == {""}
    _edit_answers(
        adjudications={
            "TERM_FORMAT_UNCONVERTIBLE": {
                "status": "accepted",
                "provenance": "the dates are kept in verbatimEventDate",
                "confirmed": "PI: fine",
            }
        }
    )
    accepted = packaging.build(Path(), automatic=True)
    assert accepted.status == "ok"
    assert "STRUCTURAL_COST_DISCLOSED" in _codes()


def test_a_finding_recorded_by_assemble_that_blanks_metadata_waits_for_an_adjudication():
    stat = artifacts.INTERMEDIATE.stat()
    artifacts.ASSEMBLY.write_text(
        json.dumps(
            {
                "intermediate": {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns},
                "findings": [
                    {
                        "code": "JOIN_METADATA_MISSING",
                        "severity": "warning",
                        "message": "3 sampleID(s) have no row in samples.csv",
                        "count": 3,
                    }
                ],
            }
        )
    )
    result = packaging.build(Path(), automatic=True)
    assert result.status == "needs_review"
    assert "JOIN_METADATA_MISSING" in result.detail


def test_a_control_answer_naming_no_sample_stops_the_build():
    _answer_control("SE-22", "control")
    result = packaging.build(Path())
    assert result.status == "error"
    assert "SE-22" in result.detail
    assert not Path("archive").exists()


def test_a_confirmed_mapping_row_naming_no_column_stops_the_build():
    packaging.build(Path())
    _confirm(
        sheets.TERM_MAPPING,
        "source_column\ttarget\tbasis\tprovenance\tconfirmed\nStation\tlocationID\talias\tPI\tPI\n",
    )
    result = packaging.build(Path())
    assert result.status == "error"
    assert "Station" in result.detail


def test_a_derived_values_row_matching_no_row_stops_the_build():
    packaging.build(Path())
    rows = _proposed_rows(sheets.DERIVED_VALUES)
    rows[0].update(sampleID="nobody", count="999", provenance="a test", confirmed="PI")
    _confirm_rows(sheets.DERIVED_VALUES, rows[:1])
    result = packaging.build(Path())
    assert result.status == "error"
    assert "nobody" in result.detail


def test_a_derived_values_row_naming_a_source_column_stops_the_build_and_names_the_term():
    _rename_column("decimalLatitude", "lat")
    packaging.build(Path())
    rows = _proposed_rows(sheets.DERIVED_VALUES)
    rows[0].update(lat="47.7", provenance="field sheet", confirmed="PI")
    _confirm_rows(sheets.DERIVED_VALUES, rows[:1])
    result = packaging.build(Path())
    assert (result.status, result.refused) == ("error", True)
    assert "'lat'" in result.detail
    assert "decimalLatitude" in result.detail


@pytest.mark.parametrize(
    ("target", "source_column", "value"),
    [("footprintWKT", "a_wkt", "a transect"), ("countryCode", "a_country", "Atlantis")],
)
def test_a_source_value_that_cannot_be_converted_is_left_blank_not_derived(
    target, source_column, value
):
    _map_columns({target: (source_column, value)})
    packaging.build(Path(), automatic=True)
    assert {row.get(target, "") for row in _occurrences()} == {""}
    assert "TERM_FORMAT_UNCONVERTIBLE" in _codes()


def test_a_sample_size_that_cannot_be_converted_is_not_replaced_by_the_read_total():
    _map_columns(
        {"sampleSizeValue": ("library_size", "about 900"), "sampleSizeUnit": ("u", "reads")}
    )
    result = packaging.build(Path(), automatic=True)
    assert result.status == "error"
    assert "'sampleSizeUnit' populated but 'sampleSizeValue' is not" in result.detail


def test_automatic_names_what_it_accepted_in_the_build_output(run_cli):
    result = run_cli(["build", "--automatic"])
    assert "Accepted by --automatic" in result.text
    assert "proposed/taxa.tsv" in result.text


def test_a_confirmed_sheet_row_no_person_confirmed_refuses_the_sheet():
    packaging.build(Path())
    _accept_every_proposal()
    rows = _proposed_rows(sheets.DERIVED_VALUES)
    rows[0].update(count="999", provenance="field sheet", confirmed="automatic")
    _confirm_rows(sheets.DERIVED_VALUES, rows[:1])
    result = packaging.build(Path())
    assert (result.status, result.refused) == ("error", True)
    assert "confirmed/derived_values.tsv" in result.detail
    assert "build --automatic" in result.detail


def test_a_confirmed_mapping_row_no_person_confirmed_refuses_the_sheet():
    packaging.build(Path())
    _confirm(
        sheets.TERM_MAPPING,
        "source_column\ttarget\tbasis\tprovenance\tconfirmed\nlocality\tlocality\texact\tPI\tagent\n",
    )
    result = packaging.build(Path())
    assert (result.status, result.refused) == ("error", True)
    assert "confirmed/term_mapping.tsv" in result.detail


def test_audit_findings_from_an_earlier_build_are_marked_stale_in_the_report():
    packaging.build(Path(), automatic=True)
    audit.record_audit(artifacts.AUDIT_RECORD, ["invented a depth"], archive_dir=Path("archive"))
    packaging.build(Path(), automatic=True)
    report = Path("archive/CONVERSION_REPORT.md").read_text(encoding="utf-8")
    assert "invented a depth" in report
    assert "earlier build" not in report
    _edit_answers(constants={"samplingProtocol": {"value": "2 L", "provenance": "a test"}})
    packaging.build(Path(), automatic=True)
    report = Path("archive/CONVERSION_REPORT.md").read_text(encoding="utf-8")
    assert "earlier build" in report
    assert "invented a depth" in report


def test_the_taxa_proposal_names_each_lineages_source_beside_its_key():
    packaging.build(Path(), automatic=True)
    rows = _proposed_rows(sheets.TAXA)
    assert list(rows[0])[:3] == ["lineage_key", "source_name", "source_lineage"]
    by_name = {row["source_name"]: row for row in rows}
    assert "Arthropoda" in by_name["Calanus pacificus"]["source_lineage"]


def test_human_rows_a_person_chose_to_publish_are_counted():
    _edit_answers(
        filters={"exclude_human": {"value": False, "provenance": "a test", "confirmed": ""}}
    )
    packaging.build(Path(), automatic=True)
    (finding,) = [f for f in _findings() if f["code"] == "HUMAN_PUBLISHED"]
    assert finding["count"] >= 1
    assert "no person confirmed" in finding["message"]


def test_human_rows_published_on_an_unconfirmed_answer_wait_for_an_adjudication():
    _edit_answers(
        filters={"exclude_human": {"value": False, "provenance": "a test", "confirmed": ""}}
    )
    result = packaging.build(Path(), automatic=True)
    assert result.status == "needs_review"
    assert "HUMAN_PUBLISHED" in result.detail


def test_human_rows_published_on_a_confirmed_answer_wait_for_nothing():
    _edit_answers(
        filters={
            "exclude_human": {"value": False, "provenance": "a test", "confirmed": "PI: keep them"}
        }
    )
    result = packaging.build(Path(), automatic=True)
    assert result.status == "ok"
    assert "HUMAN_PUBLISHED" in _codes()
    assert "ADJUDICATION_NEEDED" not in _codes()


def test_conflicting_timestamps_wait_for_an_adjudication_rather_than_stop_the_build():
    rows = list(read_rows(artifacts.INTERMEDIATE, delimiter="\t"))
    for row in rows:
        row["date_lab_log"] = "2025-06-09"
    write_tsv(rows, artifacts.INTERMEDIATE, columns=list(rows[0]))
    _edit_answers(
        derive_fields={"timestamp_col_a": "eventDate", "timestamp_col_b": "date_lab_log"}
    )
    result = packaging.build(Path(), automatic=True)
    assert result.status == "needs_review"
    assert "TIMESTAMP_CONFLICT" in result.detail
    assert Path("archive/dwca.zip").exists()


def _drop_event_ids() -> None:
    rows = list(read_rows(artifacts.INTERMEDIATE, delimiter="\t"))
    for row in rows:
        del row["eventID"]
    write_tsv(rows, artifacts.INTERMEDIATE, columns=list(rows[0]))


def test_a_missing_event_id_is_left_blank_and_reported():
    _drop_event_ids()
    packaging.build(Path(), automatic=True)
    assert all(row.get("eventID", "") == "" for row in _occurrences())
    states = {row["term"]: row for row in read_rows(artifacts.TERM_STATES, delimiter="\t")}
    assert states["eventID"]["state"] == "Ask"
    assert "no eventID column" in states["eventID"]["evidence"]


def test_a_suspect_coordinate_sign_waits_for_an_adjudication_even_under_automatic():
    rows = list(read_rows(artifacts.INTERMEDIATE, delimiter="\t"))
    for row in rows:
        row["decimalLatitude"], row["decimalLongitude"] = ("-30.0", "-40.0")
    rows[0]["decimalLatitude"] = "30.0"
    write_tsv(rows, artifacts.INTERMEDIATE, columns=list(rows[0]))
    result = packaging.build(Path(), automatic=True)
    assert result.status == "needs_review"
    assert "COORDINATE_SIGN_SUSPECT" in result.detail
    _edit_answers(
        adjudications={
            "COORDINATE_SIGN_SUSPECT": {
                "status": "accepted",
                "provenance": "field log",
                "confirmed": "PI: station 1 is north of the equator",
            }
        }
    )
    assert packaging.build(Path(), automatic=True).status == "ok"


def _give_the_first_row_dynamic_properties(value: str) -> None:
    rows = list(read_rows(artifacts.INTERMEDIATE, delimiter="\t"))
    for n, row in enumerate(rows):
        row["dynamicProperties"] = value if n == 0 else ""
    write_tsv(rows, artifacts.INTERMEDIATE, columns=list(rows[0]))


@pytest.mark.parametrize("no_emof", [False, True], ids=["with eMoF", "without eMoF"])
@pytest.mark.parametrize("value", ["not json", '{"dup": 1, "dup": 2}'])
def test_a_malformed_dynamic_properties_value_is_reported_once_and_left_out(value, no_emof):
    _give_the_first_row_dynamic_properties(value)
    _edit_answers(build={"no_emof": no_emof})
    assert packaging.build(Path(), automatic=True).status == "needs_review"
    assert _codes().count("DYNAMIC_PROPERTIES_MALFORMED") == 1
    assert "dup" not in json.loads(_occurrences()[0]["dynamicProperties"])


def test_a_dynamic_properties_constant_stands_in_for_the_source_value_and_columns_join_it():
    _add_constant("dynamicProperties", '{"cruise": "PS25"}')
    packaging.build(Path(), automatic=True)
    first = json.loads(_occurrences()[0]["dynamicProperties"])
    assert (first["cruise"], first["marker"]) == ("PS25", "MiFish-U")
    assert Path("archive/extendedmeasurementorfact.txt").exists()


def test_the_waiting_line_counts_answers_and_sheet_rows_once():
    rows = sheets.RowsChanged(100, 100, [f"S{n}/f1" for n in range(sheets.LISTED_ROWS)])
    review = sheets.SheetReview(sheets.DERIVED_VALUES, "", confirmed=True, rows=rows)
    result = BuildResult("", "", unconfirmed=["metadata.title", "markers.x"], sheets=[review])
    detail = packaging._waiting_detail(result)
    assert detail.startswith("102 answer(s) no person has confirmed: metadata.title, markers.x, ")
    assert detail.endswith("S9/f1 and 90 more")


def test_a_confirmed_sheet_written_with_commas_is_refused_for_its_header():
    packaging.build(Path())
    _accept_every_proposal()
    sheets.DERIVED_VALUES.confirmed.write_text(
        "sampleID,featureID,count,provenance,confirmed\nS1,f1,12,field sheet,PI\n"
    )
    result = packaging.build(Path())
    assert (result.status, result.refused) == ("error", True)
    assert "names column(s) 'sampleID,featureID,count,provenance,confirmed'" in result.detail
