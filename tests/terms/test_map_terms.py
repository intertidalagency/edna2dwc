from __future__ import annotations

from dataclasses import dataclass
import json

import pytest

from edna2dwc.common.findings import FindingsLog
from edna2dwc.terms import map_terms
from edna2dwc.terms.map_terms import (
    ALIAS_TABLE,
    ApplyMappingResult,
    MappingProposal,
    apply,
    apply_defaults,
    propose_mapping,
    propose_measurements,
    read_mapping_tsv,
    review_findings,
    review_order,
    write_mapping_tsv,
)
from edna2dwc.terms.term_table import load_term_table
from tests.tables import dicts, table_of

PACKAGED_TERMS = load_term_table()

TERMS_TABLE = {
    "scientificName": {},
    "DNA_sequence": {},
    "materialSampleID": {},
    "eventID": {},
    "locationID": {},
    "decimalLatitude": {},
    "decimalLongitude": {},
    "_notes": {"ignored": True},
}


@pytest.mark.parametrize(
    ("header", "target", "basis"),
    [
        ("scientificName", "scientificName", "exact"),
        ("ScientificName", "scientificName", "case_insensitive"),
        ("sample_id", "materialSampleID", "alias"),
        ("site", "locationID", "alias"),
        ("station", "locationID", "alias"),
        ("station_id", "locationID", "alias"),
        ("sitename", "locationID", "alias"),
        ("sequence", "DNA_sequence", "alias"),
        ("rep_seq", "DNA_sequence", "alias"),
        ("representative_sequence", "DNA_sequence", "alias"),
        ("asv_sequence", "DNA_sequence", "alias"),
        ("otu_sequence", "DNA_sequence", "alias"),
        ("tag_sequence", "", "unmapped"),
        ("some_weird_environmental_covariate", "", "unmapped"),
        ("source_taxon_id", "", "internal"),
    ],
)
def test_a_header_is_proposed_onto_the_term_it_names(header, target, basis):
    (proposal,) = propose_mapping([header], TERMS_TABLE)[0]
    assert (proposal.target, proposal.basis) == (target, basis)


def test_a_taxonomy_column_the_join_replaces_is_internal_without_a_finding():
    proposals, collisions = propose_mapping(
        ["scientificname"], TERMS_TABLE, written_later=frozenset({"scientificName"})
    )
    assert (proposals[0].target, proposals[0].basis) == ("", "internal")
    assert collisions.findings == []


def test_a_fuzzy_alias_never_outscores_an_exact_match_on_a_different_target(monkeypatch):
    header = ["verbatim_sample_name", "materialSampleID"]
    aliases = dict(ALIAS_TABLE)
    aliases["materialSampleID"] = (*aliases["materialSampleID"], "verbatim_sample_name")

    monkeypatch.setattr(map_terms, "ALIAS_TABLE", aliases)
    proposals, collisions = propose_mapping(header, TERMS_TABLE)

    by_column = {p.source_column: p for p in proposals}
    assert by_column["materialSampleID"].target == "materialSampleID"
    assert by_column["materialSampleID"].basis == "exact"
    assert by_column["verbatim_sample_name"].target == ""
    assert by_column["verbatim_sample_name"].basis == "ambiguous"
    assert any(f.code == "TERM_TARGET_COLLISION" for f in collisions.findings)


def test_target_collision_two_real_columns_fight_over_one_target():
    header = ["lat", "latitude"]
    proposals, collisions = propose_mapping(header, TERMS_TABLE)
    targets = [p.target for p in proposals]
    assert targets.count("decimalLatitude") == 1
    assert any(f.code == "TERM_TARGET_COLLISION" for f in collisions.findings)


def test_mapping_tsv_round_trips():
    proposals, _ = propose_mapping(["scientificName", "sample_id"], TERMS_TABLE)
    text = write_mapping_tsv(proposals)
    round_tripped = read_mapping_tsv(text)
    assert round_tripped == review_order(proposals)


def test_write_mapping_tsv_holds_only_its_header_and_one_row_per_column():
    proposals, _ = propose_mapping(["scientificName", "weird_column"], TERMS_TABLE)
    header, *rows = write_mapping_tsv(proposals).rstrip("\n").split("\n")
    assert header == "source_column\ttarget\tbasis\tprovenance\tconfirmed\tmeasurement"
    assert [row.count("\t") for row in rows] == [header.count("\t")] * 2


def test_read_mapping_tsv_skips_comment_lines():
    proposals, _ = propose_mapping(["scientificName", "sample_id"], TERMS_TABLE)
    header, *rows = write_mapping_tsv(proposals).split("\n")
    text = "\n".join([header, "# a note a person left", *rows])
    round_tripped = read_mapping_tsv(text)
    assert len(round_tripped) == 2


def test_read_mapping_tsv_raises_a_clear_error_on_a_malformed_row():
    text = "source_column\ttarget\tbasis\nscientificName\tscientificName\n"
    with pytest.raises(ValueError, match="line 2"):
        read_mapping_tsv(text)


def test_mapping_tsv_sanitizes_embedded_tabs_and_newlines_in_a_column_name():
    proposals, _ = propose_mapping(["weird\tcolumn\nname"], TERMS_TABLE)
    text = write_mapping_tsv(proposals)
    round_tripped = read_mapping_tsv(text)
    assert round_tripped[0].source_column == "weird column name"


def test_the_proposal_maps_aliases_and_leaves_a_genuinely_unmapped_column_unmapped():
    proposals, _ = propose_mapping(
        ["occurrenceID", "biosample", "some_weird_environmental_covariate"],
        PACKAGED_TERMS,
    )
    assert MappingProposal("biosample", "materialSampleID", "alias") in proposals
    assert MappingProposal("some_weird_environmental_covariate", "", "unmapped") in proposals
    assert review_findings(proposals).findings == []


def test_an_ambiguous_column_is_reported_for_review():
    proposals = [MappingProposal("Locality", "", "ambiguous")]
    (finding,) = review_findings(proposals).findings
    assert finding.code == "TERM_AMBIGUOUS"
    assert "Locality" in finding.message


def test_review_order_puts_the_columns_to_review_first():
    proposals = [
        MappingProposal("b", "eventID", "exact"),
        MappingProposal("c", "", "unmapped"),
        MappingProposal("a", "", "ambiguous"),
    ]
    assert [p.source_column for p in review_order(proposals)] == ["a", "c", "b"]


def test_read_mapping_tsv_reads_columns_by_their_header():
    text = (
        "confirmed\tprovenance\tbasis\tsource_column\ttarget\n"
        "PI: yes\tthe header\tunmapped\tsalinity_psu\tdynamicProperties\n"
    )
    (row,) = read_mapping_tsv(text)
    assert row == MappingProposal(
        "salinity_psu", "dynamicProperties", "unmapped", "the header", "PI: yes"
    )


def test_read_mapping_tsv_reads_a_sheet_with_no_answer_columns_as_unprovenanced():
    (row,) = read_mapping_tsv("source_column\ttarget\tbasis\nsalinity_psu\tdepth\tunmapped\n")
    assert row == MappingProposal("salinity_psu", "depth", "unmapped", "", "")


def test_read_mapping_tsv_refuses_a_header_missing_a_column():
    with pytest.raises(ValueError, match="basis"):
        read_mapping_tsv("source_column\ttarget\nsalinity_psu\tdynamicProperties\n")


def test_a_measurement_row_shows_what_the_build_publishes():
    proposals = [MappingProposal("salinity_psu", "", "unmapped")]
    propose_measurements(proposals, {"salinity_psu": "measurementType=salinity"})
    text = write_mapping_tsv(proposals)
    assert (
        "salinity_psu\textendedmeasurementorfact\tmeasurement\t\t\tmeasurementType=salinity"
        in text
    )


@pytest.mark.parametrize(
    "header",
    [
        "source_column\ttarget\tbasis\tprovenance\tconfirmed",
        "source_column\ttarget\tbasis\tprovenance\tconfirmed\tmeasurement",
    ],
)
def test_a_confirmed_sheet_reads_with_or_without_the_measurement_column(header):
    fields = header.count("\t") + 1
    cells = ["salinity_psu", "dynamicProperties", "unmapped", "the header", "PI", "x"]
    (proposal,) = read_mapping_tsv(f"{header}\n{chr(9).join(cells[:fields])}\n")
    assert proposal == MappingProposal(
        "salinity_psu", "dynamicProperties", "unmapped", "the header", "PI"
    )


def test_a_settled_column_is_still_rerouted_but_raises_no_finding():
    proposals, collisions = propose_mapping(
        ["Station_ID", "Location"], TERMS_TABLE, settled=frozenset({"Location"})
    )
    by_column = {p.source_column: p for p in proposals}
    assert by_column["Location"].basis == "ambiguous"
    assert collisions.findings == []
    assert review_findings(proposals, frozenset({"Location"})).findings == []


@dataclass
class _Mapped:
    rows: list[dict[str, str]]
    findings: FindingsLog
    applied: ApplyMappingResult


@dataclass
class _Applied:
    rows: list[dict[str, str]]
    findings: FindingsLog
    proposals: list[MappingProposal]


def _mapped(rows, proposals, terms_table, **options) -> _Mapped:
    result = map_terms.apply_mapping(table_of(rows), proposals, terms_table, **options)
    return _Mapped(dicts(result.dynamic.folded(result.table)), result.findings, result)


FORMATTED_TERMS = {
    "eventDate": {"format": "iso8601_date"},
    "verbatimEventDate": {},
    "taxonRank": {"format": "controlled"},
    "materialSampleID": {},
    "decimalLatitude": {"format": "decimal_degrees"},
    "decimalLongitude": {"format": "decimal_degrees"},
    "waterBody": {},
}


def test_a_mapped_columns_rename_never_depends_on_a_blank_first_cell():
    rows = [
        {"sample_name": ""},
        {"sample_name": "MS002"},
    ]
    proposals = [MappingProposal("sample_name", "materialSampleID", "alias")]
    result = _mapped(rows, proposals, FORMATTED_TERMS)
    assert result.rows[0]["materialSampleID"] == ""
    assert "sample_name" not in result.rows[0]
    assert result.rows[1]["materialSampleID"] == "MS002"
    assert "sample_name" not in result.rows[1]


def test_controlled_vocabulary_actually_rejects_an_invalid_value():
    rows = [{"rank_col": "not_a_real_rank"}]
    proposals = [MappingProposal("rank_col", "taxonRank", "alias")]
    result = _mapped(rows, proposals, FORMATTED_TERMS)
    assert result.rows[0]["taxonRank"] == ""
    assert any(f.code == "TERM_FORMAT_UNCONVERTIBLE" for f in result.findings.findings)


@pytest.mark.parametrize(
    ("rank", "published"),
    [
        ("genus", "genus"),
        ("Kingdom", "kingdom"),
        ("Phylum (Division)", "phylum"),
        ("Subphylum (Subdivision)", "subphylum"),
    ],
)
def test_a_recognized_rank_is_published_as_its_darwin_core_rank(rank, published):
    proposals = [MappingProposal("rank", "taxonRank", "alias")]
    result = _mapped([{"rank": rank}], proposals, FORMATTED_TERMS)
    assert result.rows[0]["taxonRank"] == published


def test_constant_is_written_to_every_row_with_no_source_column():
    rows = [{"x": "1"}, {"x": "2"}]
    result = _mapped(
        rows,
        [],
        FORMATTED_TERMS,
        constants={"waterBody": ("Gulf of Mexico", "document:methods.pdf")},
    )
    assert all(r["waterBody"] == "Gulf of Mexico" for r in result.rows)


def test_dynamic_properties_key_collision_is_disclosed_not_silently_overwritten():
    rows = [{"dynamicProperties": '{"salinity": "33.2"}', "salinity": "34.0"}]
    result = _mapped(rows, [], FORMATTED_TERMS)
    assert any(f.code == "DYNAMIC_PROPERTIES_KEY_COLLISION" for f in result.findings.findings)


def test_no_collision_when_an_unmapped_column_has_a_new_key():
    rows = [{"dynamicProperties": '{"salinity": "33.2"}', "temperature": "16.0"}]
    result = _mapped(rows, [], FORMATTED_TERMS)
    assert not any(f.code == "DYNAMIC_PROPERTIES_KEY_COLLISION" for f in result.findings.findings)

    merged = json.loads(result.rows[0]["dynamicProperties"])
    assert merged == {"salinity": "33.2", "temperature": "16.0"}


def _not_darwin_core(result: _Mapped) -> str:
    (finding,) = [f for f in result.findings.findings if f.code == "TERM_NOT_DARWIN_CORE"]
    assert finding.severity == "error"
    return finding.message


def test_a_target_that_is_no_term_stops_the_build_and_names_the_closest_term():
    rows = [{"raw_name": "Lake Erie"}]
    proposals = [MappingProposal("raw_name", "waterBdoy", "reviewed")]
    result = _mapped(rows, proposals, FORMATTED_TERMS)
    assert "waterBdoy" not in result.rows[0]
    assert all(word in _not_darwin_core(result) for word in ("waterBdoy", "`waterBody`", "stops"))


def test_dynamic_properties_literal_target_still_passes_validation():
    rows = [{"raw_note": "site A"}]
    proposals = [MappingProposal("raw_note", "dynamicProperties", "reviewed")]
    result = _mapped(rows, proposals, FORMATTED_TERMS)
    assert not any(f.code == "TERM_NOT_DARWIN_CORE" for f in result.findings.findings)


def test_verbatim_event_date_set_when_a_real_conversion_happened():
    rows = [{"raw_date": "2021-9-5T3:55:0Z"}]
    proposals = [MappingProposal("raw_date", "eventDate", "alias")]
    result = _mapped(rows, proposals, FORMATTED_TERMS)
    assert result.rows[0]["eventDate"] == "2021-09-05T03:55:00Z"
    assert result.rows[0]["verbatimEventDate"] == "2021-9-5T3:55:0Z"


def test_an_unconvertible_date_is_kept_in_verbatim_event_date():
    rows = [{"raw_date": "06/05/2025"}]
    proposals = [MappingProposal("raw_date", "eventDate", "alias")]
    result = _mapped(rows, proposals, FORMATTED_TERMS)
    assert result.rows[0]["eventDate"] == ""
    assert result.rows[0]["verbatimEventDate"] == "06/05/2025"


def test_unconvertible_values_are_reported_once_per_term_with_a_count_and_examples():
    rows = [{"raw_date": f"0{n}/05/2025"} for n in range(1, 6)]
    proposals = [MappingProposal("raw_date", "eventDate", "alias")]
    result = _mapped(rows, proposals, FORMATTED_TERMS)
    [finding] = [f for f in result.findings.findings if f.code == "TERM_FORMAT_UNCONVERTIBLE"]
    assert finding.count == 5
    assert "01/05/2025" in finding.message


def test_verbatim_event_date_not_set_when_the_source_was_already_iso():
    rows = [{"raw_date": "2021-09-05"}]
    proposals = [MappingProposal("raw_date", "eventDate", "alias")]
    result = _mapped(rows, proposals, FORMATTED_TERMS)
    assert result.rows[0]["eventDate"] == "2021-09-05"
    assert "verbatimEventDate" not in result.rows[0]


def test_verbatim_event_date_from_derive_fields_conflict_is_never_overwritten():
    proposals = [
        MappingProposal("raw_date", "eventDate", "alias"),
        MappingProposal("verbatimEventDate", "verbatimEventDate", "exact"),
    ]
    conflict_text = "a='2021-09-05' vs b='2021-09-06'"
    for row in (
        {"raw_date": "2021-9-5", "verbatimEventDate": conflict_text},
        {"verbatimEventDate": conflict_text, "raw_date": "2021-9-5"},
    ):
        result = _mapped([row], proposals, FORMATTED_TERMS)
        assert result.rows[0]["verbatimEventDate"] == conflict_text


@pytest.mark.parametrize(
    ("minimum_column", "maximum_column"), [("z_min", "a_max"), ("a_min", "z_max")]
)
def test_a_blank_maximum_depth_takes_the_minimum_whatever_the_column_order(
    minimum_column, maximum_column
):
    rows = [{minimum_column: "5", maximum_column: ""}]
    proposals = [
        MappingProposal(minimum_column, "minimumDepthInMeters", "alias"),
        MappingProposal(maximum_column, "maximumDepthInMeters", "alias"),
    ]
    result = _mapped(rows, proposals, {"minimumDepthInMeters": {}, "maximumDepthInMeters": {}})
    assert result.rows[0]["maximumDepthInMeters"] == "5"


def test_apply_defaults_sets_basis_of_record_and_never_a_datum():
    rows = [{"decimalLatitude": "45.0", "decimalLongitude": "-70.0"}]
    out = dicts(apply_defaults(table_of(rows)))
    assert out[0]["basisOfRecord"] == "MaterialSample"
    assert "geodeticDatum" not in out[0]


def test_apply_defaults_never_overwrites_an_existing_basis_of_record():
    rows = [{"basisOfRecord": "HumanObservation"}]
    out = dicts(apply_defaults(table_of(rows)))
    assert out[0]["basisOfRecord"] == "HumanObservation"


@pytest.mark.parametrize("blob", ["{not valid json", "[1, 2, 3]"])
def test_dynamic_properties_that_are_not_a_json_object_are_disclosed_and_replaced(blob):
    rows = [{"dynamicProperties": blob, "salinity": "33.2"}]
    result = _mapped(rows, [], FORMATTED_TERMS)
    assert any(f.code == "DYNAMIC_PROPERTIES_MALFORMED" for f in result.findings.findings)
    assert json.loads(result.rows[0]["dynamicProperties"]) == {"salinity": "33.2"}


def test_decimal_degrees_bounds_go_by_exact_term_name_not_a_substring():
    terms_table = {**FORMATTED_TERMS, "translatedX": {"format": "decimal_degrees"}}
    rows = [{"raw_x": "-120.5"}]
    proposals = [MappingProposal("raw_x", "translatedX", "reviewed")]
    result = _mapped(rows, proposals, terms_table)
    assert result.rows[0]["translatedX"] == "-120.5"


@pytest.mark.parametrize(("constant", "disclosed"), [("MS999", True), ("MS001", False)])
def test_a_constant_overwriting_a_different_mapped_value_is_disclosed(constant, disclosed):
    rows = [{"sample_name": "MS001"}]
    proposals = [MappingProposal("sample_name", "materialSampleID", "alias")]
    result = _mapped(
        rows,
        proposals,
        FORMATTED_TERMS,
        constants={"materialSampleID": (constant, "document:methods.pdf")},
    )
    assert result.rows[0]["materialSampleID"] == constant
    codes = {f.code for f in result.findings.findings}
    assert ("CONSTANT_OVERWROTE_MAPPED_VALUE" in codes) is disclosed


def test_a_dynamic_properties_constant_that_would_replace_a_source_value_is_disclosed():
    rows = [{"dynamicProperties": '{"cruise": "PS01"}'}, {"dynamicProperties": ""}]
    result = _mapped(
        rows,
        [],
        FORMATTED_TERMS,
        constants={"dynamicProperties": ('{"cruise": "PS25"}', "document:methods.pdf")},
    )
    overwrote = [
        f for f in result.findings.findings if f.code == "CONSTANT_OVERWROTE_MAPPED_VALUE"
    ]
    assert [f.count for f in overwrote] == [1]


def test_a_constant_that_is_no_term_stops_the_build_and_names_the_closest_term():
    rows = [{"x": "1"}]
    result = _mapped(
        rows,
        [],
        FORMATTED_TERMS,
        constants={"waterBdoy": ("Gulf of Mexico", "document:methods.pdf")},
    )
    assert "waterBdoy" not in result.rows[0]
    assert "waterBdoy" not in (result.rows[0]["dynamicProperties"] or "")
    message = _not_darwin_core(result)
    assert message.startswith(
        "The constant 'waterBdoy' is no Darwin Core or extension term, so the build stops."
    )
    assert "`waterBody`" in message


def test_constants_that_are_no_term_are_reported_in_name_order():
    rows = [{"x": "1"}]
    constants = {
        name: ("Gulf of Mexico", "document:methods.pdf")
        for name in ("waterBdoy", "evnetDate", "lcoality")
    }
    result = _mapped(rows, [], FORMATTED_TERMS, constants=constants)
    messages = [f.message for f in result.findings.findings if f.code == "TERM_NOT_DARWIN_CORE"]
    assert [m.split("'")[1] for m in messages] == ["evnetDate", "lcoality", "waterBdoy"]


def test_a_marker_constant_that_is_no_term_stops_the_build_too():
    rows = [{"marker": "12S", "x": "1"}]
    result = _mapped(
        rows,
        [],
        FORMATTED_TERMS,
        marker_constants={"12S": {"waterBdoy": ("Gulf of Mexico", "document:methods.pdf")}},
    )
    assert "`waterBody`" in _not_darwin_core(result)


def test_a_column_with_no_mapping_tsv_row_at_all_is_flagged_separately_from_unmapped():
    rows = [{"lineage_key": "abc123"}]
    result = _mapped(rows, [], FORMATTED_TERMS)
    assert json.loads(result.rows[0]["dynamicProperties"]) == {"lineage_key": "abc123"}
    missing = [f for f in result.findings.findings if f.code == "MAPPING_ROW_MISSING"]
    assert len(missing) == 1
    assert "lineage_key" in missing[0].message


def test_a_column_left_as_a_proposal_is_not_flagged_as_mapping_row_missing():
    rows = [{"sample_name": "MS001"}]
    proposals = [MappingProposal("sample_name", "materialSampleID", "alias")]
    result = _mapped(rows, proposals, FORMATTED_TERMS)
    assert not any(f.code == "MAPPING_ROW_MISSING" for f in result.findings.findings)


def test_a_column_correctly_excluded_via_basis_internal_is_not_flagged_as_missing():
    rows = [{"lineage_key": "abc123"}]
    proposals = [MappingProposal("lineage_key", "", "internal")]
    result = _mapped(rows, proposals, FORMATTED_TERMS)
    assert "dynamicProperties" not in result.rows[0]
    assert not any(f.code == "MAPPING_ROW_MISSING" for f in result.findings.findings)


def test_number_with_unit_strips_surrounding_whitespace_before_validating():
    terms_table = {**FORMATTED_TERMS, "annealingTemp": {"format": "number_with_unit"}}
    rows = [{"raw_temp": " 60 "}]
    proposals = [MappingProposal("raw_temp", "annealingTemp", "reviewed")]
    result = _mapped(rows, proposals, terms_table)
    assert result.rows[0]["annealingTemp"] == "60"
    assert not any(f.code == "TERM_FORMAT_UNCONVERTIBLE" for f in result.findings.findings)


def test_several_columns_mapped_to_dynamic_properties_all_survive():
    rows = [{"temperature": "16.2", "salinity": "33.1", "Sample_Name": "1006.a"}]
    proposals = [
        MappingProposal("temperature", "dynamicProperties", "manual"),
        MappingProposal("salinity", "dynamicProperties", "manual"),
        MappingProposal("Sample_Name", "dynamicProperties", "manual"),
    ]
    result = _mapped(rows, proposals, FORMATTED_TERMS)
    assert json.loads(result.rows[0]["dynamicProperties"]) == {
        "temperature": "16.2",
        "salinity": "33.1",
        "Sample_Name": "1006.a",
    }


def test_an_explicit_dynamic_properties_mapping_merges_with_an_existing_blob():
    rows = [{"dynamicProperties": '{"depth": "3"}', "temperature": "16.2"}]
    proposals = [MappingProposal("temperature", "dynamicProperties", "manual")]
    result = _mapped(rows, proposals, FORMATTED_TERMS)
    assert json.loads(result.rows[0]["dynamicProperties"]) == {
        "depth": "3",
        "temperature": "16.2",
    }


def test_a_malformed_dynamic_properties_blob_is_disclosed_once_with_a_count():
    rows = [{"dynamicProperties": "16.2", "materialSampleID": f"s{n}"} for n in range(500)]
    result = _mapped(rows, [], FORMATTED_TERMS)
    malformed = [f for f in result.findings.findings if f.code == "DYNAMIC_PROPERTIES_MALFORMED"]
    assert len(malformed) == 1
    assert malformed[0].count == 500


def test_term_unmapped_says_each_unmapped_column_stays_in_dynamic_properties():
    rows = [{"temperature": "12.5", "site_notes": "muddy"}]
    proposals = [
        MappingProposal("temperature", "", "unmapped"),
        MappingProposal("site_notes", "", "unmapped"),
    ]
    result = _mapped(rows, proposals, FORMATTED_TERMS)
    (finding,) = [f for f in result.findings.findings if f.code == "TERM_UNMAPPED"]
    assert finding.message.startswith(
        "2 column(s) left unmapped: temperature, site_notes stay in dynamicProperties."
    )


WATER_BODY = {"waterBody": ("Gulf of Mexico", "document:methods.pdf")}


def _apply(rows, proposals=None, **constants):
    if proposals is None:
        proposals, _ = propose_mapping(list(rows[0]), PACKAGED_TERMS)
    applied = apply(
        table_of(rows),
        proposals,
        PACKAGED_TERMS,
        constants=constants.get("constants", {}),
        marker_constants=constants.get("marker_constants", {}),
    )
    return _Applied(
        dicts(applied.dynamic.folded(applied.table)), applied.findings, applied.proposals
    )


def test_apply_maps_a_proposed_alias_and_fills_the_default_basis_of_record():
    rows = _apply(
        [{"occurrenceID": "ds:S1:f1", "organismQuantity": "1", "biosample": "BS001"}]
    ).rows
    assert rows[0]["materialSampleID"] == "BS001"
    assert rows[0]["basisOfRecord"] == "MaterialSample"


def test_apply_reports_term_unmapped_exactly_once():
    result = _apply(
        [{"occurrenceID": "ds:S1:f1", "organismQuantity": "1", "some_weird_covariate": "12.3"}]
    )
    unmapped = [f for f in result.findings.findings if f.code == "TERM_UNMAPPED"]
    assert [f.count for f in unmapped] == [1]


def test_apply_records_a_constant_in_the_mapping_once_with_its_provenance():
    rows = [{"occurrenceID": "ds:S1:f1", "organismQuantity": "1"}]
    first = _apply(rows, constants=WATER_BODY)
    again = _apply(rows, first.proposals, constants=WATER_BODY)
    constant_rows = [p for p in again.proposals if p.source_column == "(constant)"]
    assert constant_rows == [
        MappingProposal("(constant)", "waterBody", "constant", "document:methods.pdf")
    ]


def test_apply_records_a_marker_constant_under_its_marker():
    rows = [{"occurrenceID": "ds:S1:f1", "marker": "16S"}]
    marker_constants = {"16S": {"sop": ("protocol A", "document:methods.pdf")}}
    result = _apply(rows, marker_constants=marker_constants)
    assert (
        MappingProposal("(constant 16S)", "sop", "constant", "document:methods.pdf")
        in result.proposals
    )
    assert result.rows[0]["sop"] == "protocol A"


def test_apply_gives_a_constant_rerouted_to_dynamic_properties_no_mapping_row():
    result = _apply(
        [{"occurrenceID": "ds:S1:f1", "organismQuantity": "1"}],
        constants={"waterBdoy": ("Gulf of Mexico", "document:methods.pdf")},
    )
    assert not any(p.source_column == "(constant)" for p in result.proposals)


def test_apply_applies_a_confirmed_mapping_as_written():
    proposals = [
        MappingProposal("occurrenceID", "occurrenceID", "exact"),
        MappingProposal("organismQuantity", "organismQuantity", "exact"),
        MappingProposal("weird_col", "recordedBy", "reviewed"),
    ]
    rows = _apply(
        [{"occurrenceID": "ds:S1:f1", "organismQuantity": "1", "weird_col": "x"}], proposals
    ).rows
    assert rows[0]["recordedBy"] == "x"


def test_apply_maps_a_column_build_derived_to_the_term_it_names_without_a_finding():
    proposals = [MappingProposal("occurrenceID", "occurrenceID", "exact")]
    result = _apply(
        [{"occurrenceID": "ds:S1:f1", "eventDate": "2021-06-01", "lineage_key": "k"}], proposals
    )
    assert result.rows[0]["eventDate"] == "2021-06-01"
    assert "lineage_key" not in result.rows[0]
    assert result.findings.findings == []


@pytest.mark.parametrize(
    ("column", "term"),
    [("degrees_latitude", "decimalLatitude"), ("degrees_longitude", "decimalLongitude")],
)
def test_a_coordinate_column_named_in_degrees_maps_to_its_term(column, term):
    proposals, _ = propose_mapping([column], TERMS_TABLE)
    assert (proposals[0].target, proposals[0].basis) == (term, "alias")


def test_dynamic_properties_left_as_given_keeps_a_source_value_no_column_adds_to():
    rows = [
        {"dynamicProperties": '{"depth": 1.50}', "site_notes": ""},
        {"dynamicProperties": '{"depth": 1.50}', "site_notes": "muddy"},
    ]
    result = map_terms.apply_mapping(table_of(rows), [], FORMATTED_TERMS)
    first, second = dicts(result.dynamic.folded(result.table, as_given=True))
    assert first["dynamicProperties"] == '{"depth": 1.50}'
    assert json.loads(second["dynamicProperties"]) == {"depth": 1.5, "site_notes": "muddy"}


def test_converting_derived_columns_formats_them_and_reports_what_failed():
    table = table_of([{"organismQuantity": " 12 ", "eventID": "E1"}, {"organismQuantity": "-3"}])
    converted, findings = map_terms.convert_formats(
        table, ["organismQuantity", "eventID"], PACKAGED_TERMS
    )
    assert [row["organismQuantity"] for row in dicts(converted)] == ["12", ""]
    (finding,) = findings.findings
    assert (finding.code, finding.count) == ("TERM_FORMAT_UNCONVERTIBLE", 1)


def test_converting_columns_without_a_format_leaves_the_table_as_it_is():
    table = table_of([{"eventID": "E1"}])
    assert map_terms.convert_formats(table, ["eventID"], PACKAGED_TERMS) == (table, FindingsLog())


def test_a_value_the_source_gave_that_failed_conversion_still_counts_as_given():
    result = map_terms.apply_mapping(
        table_of([{"depth": "deep"}, {"depth": ""}]),
        [MappingProposal("depth", "minimumDepthInMeters", "alias")],
        PACKAGED_TERMS,
    )
    gave = map_terms.source_gave(result.table, "minimumDepthInMeters")
    assert result.table.rows(f"SELECT {gave} FROM {result.table.name} ORDER BY 1") == [
        (False,),
        (True,),
    ]
