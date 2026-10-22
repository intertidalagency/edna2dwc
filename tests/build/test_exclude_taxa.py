from __future__ import annotations

import pytest

from edna2dwc.build.exclude_taxa import (
    HOMO_SAPIENS_GBIF_TAXON_CONCEPT_ID,
    HOMO_SAPIENS_WORMS_LSID,
    exclude,
    human_taxa,
    is_human,
)
from edna2dwc.build.filter_controls import control_samples
from tests.tables import dicts, table_of


@pytest.mark.parametrize(
    ("scientific_name_id", "taxon_concept_id"),
    [
        (HOMO_SAPIENS_WORMS_LSID, ""),
        ("", HOMO_SAPIENS_GBIF_TAXON_CONCEPT_ID),
        ("urn:lsid:marinespecies.org:taxname:1455976", ""),
        ("", "https://www.gbif.org/species/2436435"),
        ("", "NCBI:txid9606"),
        ("", "NCBI:txid9605"),
    ],
)
def test_any_known_human_id_marks_a_row_human(scientific_name_id, taxon_concept_id):
    assert is_human(
        scientific_name="something odd",
        scientific_name_id=scientific_name_id,
        taxon_concept_id=taxon_concept_id,
    )


def test_a_human_name_is_human_whatever_ids_the_row_carries():
    assert is_human(
        scientific_name="Homo",
        scientific_name_id="urn:lsid:marinespecies.org:taxname:1455976",
        taxon_concept_id="https://www.gbif.org/species/9999",
    )
    assert is_human(scientific_name="Homo sapiens", taxon_concept_id="NCBI:txid1")


def test_a_row_with_neither_a_human_name_nor_a_human_id_is_not_human():
    assert not is_human(
        scientific_name="Aaptos",
        scientific_name_id="urn:lsid:marinespecies.org:taxname:132064",
        taxon_concept_id="NCBI:txid6544",
    )


@pytest.mark.parametrize(
    ("scientific_name", "human"),
    [
        ("Homo sapiens Linnaeus, 1758", True),
        ("Homo sapiens sapiens", True),
        ("Homo", True),
        ("Homarus", False),
        ("Homo erectus", False),
    ],
)
def test_widened_string_fallback_covers_authorship_and_subspecies(scientific_name, human):
    assert is_human(scientific_name=scientific_name) is human


def _exclude(rows, *, drop_human=False, kingdoms=None):
    table = table_of(rows)
    result = exclude(
        table,
        controls=control_samples(table.con, []),
        humans=human_taxa(table),
        drop_human=drop_human,
        excluded_kingdoms_by_marker=kingdoms,
    )
    return dicts(result.kept), dicts(result.excluded), result.findings.findings


def test_excluding_humans_only_when_asked_reports_a_finding_and_keeps_everything_else():
    rows = [
        {"sampleID": "S1", "featureID": "f1", "count": "1", "scientificName": "Homo sapiens"},
        {"sampleID": "S1", "featureID": "f2", "count": "1", "scientificName": "Aaptos"},
    ]
    kept, excluded, findings = _exclude(rows, drop_human=True)
    assert [r["featureID"] for r in kept] == ["f2"]
    assert excluded[0]["exclusion_reason"] == "human"
    assert [f.code for f in findings] == ["HUMAN_EXCLUDED"]
    assert _exclude(rows, drop_human=False)[0] == rows


def test_a_human_exclusion_covering_the_genus_does_not_call_every_row_homo_sapiens():
    rows = [
        {"sampleID": "S1", "featureID": "f1", "count": "1", "scientificName": "Homo sapiens"},
        {"sampleID": "S1", "featureID": "f2", "count": "1", "scientificName": "Homo"},
    ]
    _, _, (finding,) = _exclude(rows, drop_human=True)
    assert finding.count == 2
    assert "Homo" in finding.message
    assert "Homo sapiens" not in finding.message


def test_a_kingdom_exclusion_names_each_kingdom_and_marker_it_removed():
    rows = [
        {"marker": "12S", "kingdom": "Bacteria"},
        {"marker": "12S", "kingdom": "Bacteria"},
        {"marker": "COI", "kingdom": "Fungi"},
    ]
    _, _, (finding,) = _exclude(rows, kingdoms={"12S": {"Bacteria"}, "COI": {"Fungi"}})
    assert finding.count == 3
    assert finding.message == "3 row(s) excluded by kingdom: 2 Bacteria from 12S, 1 Fungi from COI"


def test_excluding_kingdoms_never_touches_a_row_with_no_matching_marker_entry():
    rows = [
        {"sampleID": "S1", "featureID": "f1", "count": "1", "marker": "COI", "kingdom": "Bacteria"}
    ]
    kept, excluded, _ = _exclude(rows, kingdoms={})
    assert kept == rows
    assert excluded == []


def _rows(*marker_kingdom_names):
    return [
        {
            "sampleID": "S1",
            "featureID": f"f{i}",
            "count": "1",
            "marker": marker,
            "kingdom": kingdom,
            "scientificName": name,
        }
        for i, (marker, kingdom, name) in enumerate(marker_kingdom_names)
    ]


def test_exclude_drops_a_kingdom_only_for_the_markers_it_is_excluded_from():
    rows = _rows(("16S", "Bacteria", ""), ("18S", "Bacteria", ""), ("18S", "Animalia", ""))

    kept, _, findings = _exclude(rows, kingdoms={"18S": {"Bacteria"}})

    assert {(row["marker"], row["kingdom"]) for row in kept} == {
        ("16S", "Bacteria"),
        ("18S", "Animalia"),
    }
    assert [f.code for f in findings] == ["CONTAMINANT_EXCLUDED"]


def test_exclude_returns_every_dropped_row_with_its_reason():
    rows = _rows(("18S", "Animalia", "Homo sapiens"), ("18S", "Bacteria", "Vibrio"))

    _, excluded, _ = _exclude(rows, drop_human=True, kingdoms={"18S": {"Bacteria"}})

    assert [row["exclusion_reason"] for row in excluded] == ["human", "kingdom:Bacteria"]
