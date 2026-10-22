from __future__ import annotations

from pathlib import Path
import re

import pytest

from edna2dwc.build.join_taxonomy import (
    JoinAuditError,
    apply_confirmed_taxa,
    confirmed_answers,
    join_taxonomy,
    taxa_for_join,
)
from edna2dwc.build.sheets import SheetRefused
from edna2dwc.conversion.provenance import Answer
from tests.tables import dicts, table_of


def joined(rows, taxa):
    return dicts(join_taxonomy(table_of(rows), taxa))


RESOLVED = {
    "k1": {
        "lineage_key": "k1",
        "scientificName": "Aaptos",
        "scientificNameID": "urn:lsid:marinespecies.org:taxname:132064",
        "taxonRank": "Genus",
        "scientificNameAuthorship": "",
        "taxonomicStatus": "accepted",
        "aphia_id": "132064",
        "taxonConceptID": "",
        "kingdom": "Animalia",
        "phylum": "Porifera",
        "class": "",
        "order": "",
        "family": "",
        "genus": "Aaptos",
        "needs_review": "false",
        "review_reason": "",
        "candidate_ids": "",
        "resolution_path": "leaf",
    }
}


def test_joins_resolved_fields_onto_every_occurrence_row_of_the_lineage():
    occurrence_rows = [
        {"sampleID": "S1", "featureID": "f1", "count": "10", "lineage_key": "k1"},
        {"sampleID": "S2", "featureID": "f1", "count": "5", "lineage_key": "k1"},
    ]
    result = joined(occurrence_rows, RESOLVED)
    assert len(result) == 2
    for row in result:
        assert row["scientificName"] == "Aaptos"
        assert row["scientificNameID"] == "urn:lsid:marinespecies.org:taxname:132064"
        assert row["kingdom"] == "Animalia"


def test_a_missing_join_is_always_an_error_never_silent():
    occurrence_rows = [
        {"sampleID": "S1", "featureID": "f1", "count": "10", "lineage_key": "missing_key"}
    ]
    with pytest.raises(JoinAuditError, match="missing_key"):
        joined(occurrence_rows, RESOLVED)


def test_needs_review_reaches_identification_remarks():
    resolved = {
        **RESOLVED,
        "k2": {
            **RESOLVED["k1"],
            "lineage_key": "k2",
            "needs_review": "true",
            "review_reason": "ambiguous_homonym",
            "candidate_ids": "1|2",
        },
    }
    occurrence_rows = [{"sampleID": "S1", "featureID": "f2", "count": "5", "lineage_key": "k2"}]
    remarks = joined(occurrence_rows, resolved)[0]["identificationRemarks"]
    assert remarks == (
        "the name has several accepted homonyms that the source's phylum and class don't "
        "tell apart, and the first is published; tied candidates: 1, 2"
    )


_INTERNAL_CODE = re.compile(r"\b[a-z]+(?:_[a-z]+)+\b|\w:\w")


def _remarks_for(review_reason: str) -> str:
    resolved = {
        "k2": {
            **RESOLVED["k1"],
            "lineage_key": "k2",
            "needs_review": "true",
            "review_reason": review_reason,
        }
    }
    occurrence_rows = [{"sampleID": "S1", "featureID": "f2", "count": "5", "lineage_key": "k2"}]
    return joined(occurrence_rows, resolved)[0]["identificationRemarks"]


@pytest.mark.parametrize(
    "review_reason,kept",
    [
        ("ambiguous_homonym", []),
        ("homonym_source_mismatch", []),
        ("unaccepted_status:unaccepted", ["WoRMS", "unaccepted"]),
        ("gbif_status:DOUBTFUL", ["GBIF", "doubtful"]),
        ("name_mismatch:Bacteroidetes", ["Bacteroidetes"]),
        ("non_confident_match_type:fuzzy", ["fuzzy"]),
        ("non_confident_match_type:near_1,unaccepted_status:unaccepted", ["near_1", "unaccepted"]),
        ("compound_name_unresolved", []),
        ("compound_name_no_shared_rank", []),
        ("compound_name_part_unresolved:Xyzzy plugh|Foo bar", ["Xyzzy plugh, Foo bar"]),
        (
            "compound_name_common_ancestor; Leucoraja erinacea:ambiguous_homonym:11|12",
            ["Leucoraja erinacea", "11, 12"],
        ),
        (
            "compound_name_common_ancestor; Raja clavata:unaccepted_status:unaccepted",
            ["Raja clavata", "unaccepted"],
        ),
        ("gbif_synonym_resolved_to_accepted", ["GBIF"]),
        ("gbif_synonym_accepted_lookup_failed", ["GBIF"]),
        ("gbif_higher_rank_match", ["GBIF"]),
    ],
)
def test_identification_remarks_explain_a_review_reason_in_plain_words(review_reason, kept):
    remarks = _remarks_for(review_reason)
    assert remarks
    assert not _INTERNAL_CODE.search(remarks.replace("near_1", "")), remarks
    assert all(word in remarks for word in kept), remarks


def test_a_review_reason_already_in_words_is_published_as_written():
    sentence = "the source's NCBI taxid 'x' is not a number, so taxonConceptID was left blank"
    assert _remarks_for(f"ambiguous_homonym; {sentence}").endswith(f"; {sentence}")


def test_no_review_reason_means_no_identification_remarks_column():
    occurrence_rows = [{"sampleID": "S1", "featureID": "f1", "count": "10", "lineage_key": "k1"}]
    result = joined(occurrence_rows, RESOLVED)
    assert "identificationRemarks" not in result[0]


def test_preexisting_identification_remarks_is_preserved_not_overwritten():
    occurrence_rows = [
        {
            "sampleID": "S1",
            "featureID": "f1",
            "count": "10",
            "lineage_key": "k1",
            "identificationRemarks": "identified by J. Smith",
        }
    ]
    result = joined(occurrence_rows, RESOLVED)
    assert result[0]["identificationRemarks"] == "identified by J. Smith"


def test_preexisting_identification_remarks_is_appended_to_when_flagged_for_review():
    resolved = {
        **RESOLVED,
        "k2": {
            **RESOLVED["k1"],
            "lineage_key": "k2",
            "needs_review": "true",
            "review_reason": "ambiguous_homonym",
            "candidate_ids": "1|2",
        },
    }
    occurrence_rows = [
        {
            "sampleID": "S1",
            "featureID": "f2",
            "count": "5",
            "lineage_key": "k2",
            "identificationRemarks": "identified by J. Smith",
        }
    ]
    result = joined(occurrence_rows, resolved)
    remarks = result[0]["identificationRemarks"]
    assert remarks.startswith("identified by J. Smith; ")


@pytest.mark.parametrize(
    "resolution_path,remark",
    [
        ("biota_fallback", "no rank of the source lineage resolved"),
        ("incertae_sedis_placeholder", "the source named no taxon"),
    ],
)
def test_a_placeholder_row_says_why_in_identification_remarks(resolution_path, remark):
    resolved = {
        "k3": {
            **RESOLVED["k1"],
            "lineage_key": "k3",
            "scientificName": "Biota incertae sedis",
            "resolution_path": resolution_path,
        }
    }
    occurrence_rows = [{"sampleID": "S1", "featureID": "f3", "count": "5", "lineage_key": "k3"}]
    result = joined(occurrence_rows, resolved)
    assert remark in result[0]["identificationRemarks"]
    assert result[0]["resolution_path"] == resolution_path


def test_a_rejoin_replaces_the_resolution_path_a_row_already_carries():
    occurrence_rows = [
        {
            "sampleID": "S1",
            "featureID": "f1",
            "count": "1",
            "lineage_key": "k1",
            "resolution_path": "old",
        }
    ]
    result = joined(occurrence_rows, RESOLVED)
    assert result[0]["resolution_path"] == "leaf"


GBIF_ROW = {
    **RESOLVED["k1"],
    "lineage_key": "g1",
    "scientificName": "Microtrichaceae",
    "scientificNameID": "",
    "taxonRank": "family",
    "aphia_id": "",
    "taxonConceptID": "https://www.gbif.org/species/4321",
    "gbif_usage_key": "4321",
}


def test_the_gbif_usage_key_never_reaches_an_occurrence_column():
    occurrence_rows = [{"sampleID": "S1", "featureID": "f1", "count": "1", "lineage_key": "g1"}]
    row = joined(occurrence_rows, {"g1": GBIF_ROW})[0]
    assert "taxonID" not in row
    assert "aphia_id" not in row
    assert row["taxonConceptID"] == "https://www.gbif.org/species/4321"
    assert "gbif_usage_key" not in row
    assert "identificationRemarks" not in row


def test_a_gbif_usage_key_displaced_from_taxon_concept_id_is_kept_in_identification_remarks():
    resolved = {"g1": {**GBIF_ROW, "taxonConceptID": "NCBI:txid6544"}}
    occurrence_rows = [{"sampleID": "S1", "featureID": "f1", "count": "1", "lineage_key": "g1"}]
    row = joined(occurrence_rows, resolved)[0]
    assert row["identificationRemarks"] == (
        "name from the GBIF backbone: https://www.gbif.org/species/4321"
    )


def test_a_gbif_url_published_as_scientific_name_id_is_not_repeated_in_remarks():
    resolved = {
        "g1": {
            **GBIF_ROW,
            "scientificNameID": "https://www.gbif.org/species/4321",
            "taxonConceptID": "NCBI:txid6544",
        }
    }
    occurrence_rows = [{"sampleID": "S1", "featureID": "f1", "count": "1", "lineage_key": "g1"}]
    assert "identificationRemarks" not in joined(occurrence_rows, resolved)[0]


def test_a_source_taxon_id_passes_through_the_join_untouched():
    occurrence_rows = [
        {"sampleID": "S1", "featureID": "f1", "count": "1", "lineage_key": "k1", "taxonID": "x"}
    ]
    row = joined(occurrence_rows, RESOLVED)[0]
    assert row["taxonID"] == "x"


LOCKED = {"k1": {**RESOLVED["k1"], "provenance": "", "confirmed": ""}}
REVIEWED_SOURCE = Path("confirmed/taxa.tsv")


def _confirmed(**changes):
    return {**LOCKED["k1"], **changes}


def _codes(log):
    return [f.code for f in log.findings]


AAPTOS_AAPTOS = {
    "scientificName": "Aaptos aaptos",
    "scientificNameID": "urn:lsid:marinespecies.org:taxname:134241",
    "taxonRank": "Species",
}


def test_an_attributed_confirmed_row_replaces_the_lock_row():
    row = _confirmed(**AAPTOS_AAPTOS, provenance="checked WoRMS", confirmed="A. Reviewer")
    merged, log = apply_confirmed_taxa(LOCKED, [row], source=REVIEWED_SOURCE)
    assert merged["k1"] == row
    assert _codes(log) == ["TAXON_OVERRIDDEN"]


def test_a_changed_row_without_provenance_refuses_the_sheet():
    row = _confirmed(scientificName="Aaptos aaptos")
    with pytest.raises(SheetRefused, match="k1"):
        apply_confirmed_taxa(LOCKED, [row], source=REVIEWED_SOURCE)


@pytest.mark.parametrize(
    "kept",
    [
        {"scientificNameID": RESOLVED["k1"]["scientificNameID"]},
        {"taxonRank": "Genus"},
        {"scientificNameAuthorship": "(Schmidt, 1864)"},
    ],
)
def test_a_renamed_taxon_that_keeps_the_old_names_id_rank_or_authorship_is_refused(kept):
    lock = {"k1": {**LOCKED["k1"], "scientificNameAuthorship": "(Schmidt, 1864)"}}
    row = {**lock["k1"], **AAPTOS_AAPTOS, "scientificNameAuthorship": "", **kept}
    merged, log = apply_confirmed_taxa(
        lock, [{**row, "provenance": "A. Reviewer"}], source=REVIEWED_SOURCE
    )
    assert merged == lock
    assert _codes(log) == ["TAXON_OVERRIDE_INCONSISTENT"]
    assert log.has_errors()


def test_a_renamed_taxon_may_blank_what_it_does_not_know():
    row = _confirmed(
        scientificName="Aaptos aaptos", scientificNameID="", taxonRank="", provenance="A"
    )
    merged, log = apply_confirmed_taxa(LOCKED, [row], source=REVIEWED_SOURCE)
    assert merged["k1"] == row
    assert _codes(log) == ["TAXON_OVERRIDDEN"]


def test_a_species_renamed_to_another_species_keeps_its_rank():
    lock = {"k1": {**LOCKED["k1"], **AAPTOS_AAPTOS}}
    row = {
        **lock["k1"],
        "scientificName": "Aaptos papillata",
        "scientificNameID": "urn:lsid:marinespecies.org:taxname:134242",
        "provenance": "A. Reviewer",
    }
    merged, _ = apply_confirmed_taxa(lock, [row], source=REVIEWED_SOURCE)
    assert merged["k1"] == row


def test_a_changed_taxon_nobody_confirmed_is_named_for_review():
    row = _confirmed(**AAPTOS_AAPTOS, provenance="matched the methods")
    merged, _ = apply_confirmed_taxa(LOCKED, [row], source=REVIEWED_SOURCE)
    assert confirmed_answers(merged) == {"k1": Answer(None, "matched the methods", "")}
    assert confirmed_answers(merged)["k1"].unconfirmed


def test_a_confirmed_row_for_a_lineage_the_lock_lacks_is_reported():
    row = {**_confirmed(provenance="A. Reviewer"), "lineage_key": "gone"}
    merged, log = apply_confirmed_taxa(LOCKED, [row], source=REVIEWED_SOURCE)
    assert merged == LOCKED
    assert _codes(log) == ["CONFIRMED_ROW_UNMATCHED"]


def test_an_unchanged_copy_of_the_lock_applies_nothing_and_says_nothing():
    merged, log = apply_confirmed_taxa(LOCKED, [_confirmed()], source=REVIEWED_SOURCE)
    assert merged == LOCKED
    assert log.findings == []


def test_a_copy_the_lock_resolved_again_since_applies_nothing_and_says_nothing():
    copy = _confirmed(settings="registers: worms, gbif", findings="NCBI_TAXID_MALFORMED")
    lock = {"k1": {**LOCKED["k1"], "settings": "registers: gbif", "findings": ""}}
    merged, log = apply_confirmed_taxa(lock, [copy], source=REVIEWED_SOURCE)
    assert merged == lock
    assert log.findings == []


def _join(lineage_key, confirmed_rows=None):
    taxa, log = taxa_for_join(
        list(LOCKED.values()), confirmed_rows, confirmed_source=REVIEWED_SOURCE
    )
    occurrence = [{"sampleID": "S1", "featureID": "f1", "count": "1", "lineage_key": lineage_key}]
    return log, joined(occurrence, taxa)


def test_a_confirmed_row_joins_in_place_of_the_lock_row():
    confirmed = _confirmed(**AAPTOS_AAPTOS, provenance="A. Reviewer")
    log, rows = _join("k1", [confirmed])
    assert rows[0]["scientificName"] == "Aaptos aaptos"
    assert _codes(log) == ["TAXON_OVERRIDDEN"]
