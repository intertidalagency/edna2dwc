from __future__ import annotations

import httpx
import pytest



@pytest.fixture(autouse=True)
def _reset_api_usage():
    api_usage.reset()
    yield
    api_usage.reset()


def _record(**overrides) -> dict:
    base = {
        "AphiaID": 1,
        "url": "https://www.marinespecies.org/aphia.php?p=taxdetails&id=1",
        "scientificname": "Placeholder",
        "authority": "",
        "taxonRankID": 220,
        "rank": "Species",
        "status": "accepted",
        "unacceptreason": None,
        "valid_AphiaID": None,
        "valid_name": None,
        "valid_authority": None,
        "parentNameUsageID": 0,
        "kingdom": "",
        "phylum": "",
        "class": "",
        "order": "",
        "family": "",
        "genus": "",
        "citation": "Placeholder citation, accessed through WoRMS",
        "lsid": "urn:lsid:marinespecies.org:taxname:1",
        "isMarine": 1,
        "isBrackish": 0,
        "isFreshwater": 0,
        "isTerrestrial": 0,
        "isExtinct": 0,
        "match_type": "exact",
        "modified": "2020-05-14T15:18:26.397Z",
    }
    base.update(overrides)
    return base


def _resolver(
) -> TaxonResolver:


def test_leaf_exact_match():
    assert result.resolution_path == "leaf"
    assert result.scientific_name_id == "urn:lsid:marinespecies.org:taxname:132064"
    assert result.needs_review is False


        "Prasinoderma coloniale",
        {"kingdom": "Bacteria", "phylum": "Cyanobacteria", "genus": "Chloroplast"},
    )
    assert result.kingdom != "Plantae"
    assert result.resolution_path == "rank_backoff"
    assert result.scientific_name == "Cyanobacteria"


    assert result.resolution_path == "incertae_sedis_placeholder"
    assert result.kingdom == "Biota incertae sedis"


    resolver = _resolver(
        {
            "Pelargonium": [
                _record(
                    AphiaID=249154,
                    scientificname="Pelargonium",
                    kingdom="Animalia",
                    phylum="Arthropoda",
                    match_type="fuzzy",
                    status="accepted",
                )
            ]
        }
    )
    result = resolver.resolve("Pelargonium", {"kingdom": "Eukaryota"})
    assert result.resolution_path == "biota_fallback"
    assert result.scientific_name != "Pelargonium"


    assert result.needs_review is True
    assert result.review_reason == "ambiguous_homonym"
    assert result.resolution_path == "leaf"


        "Actinocyclus", {"kingdom": "Chromista", "phylum": "Bacillariophyta"}
    )
    assert result.resolution_path == "homonym_disambiguated"
    assert result.needs_review is False


    )
    assert result.needs_review is True
    assert result.review_reason == "homonym_source_mismatch"
    assert set(result.candidate_ids.split("|")) == {"1", "2"}


        "Some unresolvable terminal name",
        {"kingdom": "Unknownia", "phylum": "Bacillariophyta", "genus": "Actinocyclus"},
    )
    assert result.needs_review is True
    assert result.review_reason == "ambiguous_homonym"
    assert result.resolution_path == "rank_backoff"


        "Homonymus",
        {"kingdom": "Chromista", "phylum": "Bacillariophyta", "class": "Coscinodiscophyceae"},
    )
    assert result.resolution_path == "homonym_disambiguated"
    assert result.needs_review is False


    )
    assert result.needs_review is True
    assert result.review_reason == "ambiguous_homonym"


    )
        "Homonymus", {"kingdom": "Unknownia", "phylum": "Nope", "class": "AlsoNope"}
    )
    assert result.needs_review is True
    assert result.review_reason == "homonym_source_mismatch"


def test_homonym_tiebreak_does_not_compare_phylum_against_a_class_value():
    resolver = _resolver(
        {
            "Homonymus": [
                _record(
                    AphiaID=1,
                    scientificname="Homonymus",
                    kingdom="Chromista",
                    **{"class": "Bacillariophyceae"},
                ),
                _record(
                    AphiaID=2,
                    scientificname="Homonymus",
                    kingdom="Animalia",
                    phylum="Arthropoda",
                    **{"class": "Insecta"},
                ),
            ]
        }
    )
    result = resolver.resolve("Homonymus", {"kingdom": "Animalia", "class": "Insecta"})
    assert result.resolution_path == "homonym_disambiguated"


def test_homonym_tiebreak_with_no_phylum_and_no_class_never_guesses():
    resolver = _resolver(
        {
            "Homonymus": [
                _record(AphiaID=1, scientificname="Homonymus", kingdom="Chromista"),
                _record(AphiaID=2, scientificname="Homonymus", kingdom="Animalia"),
            ]
        }
    )
    result = resolver.resolve("Homonymus", {"kingdom": "Unknownia"})
    assert result.review_reason == "ambiguous_homonym"
    assert result.needs_review is True
    assert set(result.candidate_ids.split("|")) == {"1", "2"}


def test_exact_but_unaccepted_match_is_flagged_by_status_not_match_type():
    resolver = _resolver(
        {
            "Homonymus unacceptus": [
                _record(
                    AphiaID=7,
                    scientificname="Homonymus unacceptus",
                    kingdom="Animalia",
                    status="unaccepted",
                    match_type="exact",
                )
            ]
        }
    )
    result = resolver.resolve("Homonymus unacceptus", {"kingdom": "Animalia"})
    assert result.needs_review is True
    assert result.review_reason == "unaccepted_status:unaccepted"


def test_rank_backoff_tries_genus_before_family():
    resolver = _resolver(
        {
            "Nonexistentus": [],
            "Suberitidae": [
                _record(
                    AphiaID=5,
                    scientificname="Suberitidae",
                    kingdom="Animalia",
                    family="Suberitidae",
                )
            ],
        }
    )
    result = resolver.resolve("Nonexistentus", {"kingdom": "Animalia", "family": "Suberitidae"})
    assert result.resolution_path == "rank_backoff"
    assert result.scientific_name == "Suberitidae"


def test_rank_backoff_landing_on_a_tied_family_still_disambiguates_by_phylum():
    resolver = _resolver(
        {
            "Nonexistentus": [],
            "Suberitidae": [
                _record(
                    AphiaID=20,
                    scientificname="Suberitidae",
                    kingdom="Animalia",
                    family="Suberitidae",
                    phylum="Porifera",
                ),
                _record(
                    AphiaID=21,
                    scientificname="Suberitidae",
                    kingdom="Animalia",
                    family="Suberitidae",
                    phylum="Cnidaria",
                ),
            ],
        }
    )
    result = resolver.resolve(
        "Nonexistentus", {"kingdom": "Animalia", "family": "Suberitidae", "phylum": "Porifera"}
    )
    assert result.resolution_path == "homonym_disambiguated"
    assert result.needs_review is False


    )
    assert result.resolution_path == "compound_common_ancestor"
    assert result.genus == "Leucoraja"


def test_terminal_fallback_when_nothing_resolves():
    assert result.resolution_path == "biota_fallback"


def test_terminal_fallback_biota_option_produces_a_blank_kingdom():
    assert result.resolution_path == "biota_fallback"
    assert result.kingdom == ""


    assert result.resolution_path == "compound_common_ancestor"
    assert result.genus == "Leucoraja"
    assert result.review_reason == (
    )


def _gbif_match(**overrides) -> dict:
    base = {
        "usageKey": 100,
        "scientificName": "Placeholder Author, 1900",
        "canonicalName": "Placeholder",
        "rank": "GENUS",
        "status": "ACCEPTED",
        "confidence": 95,
        "matchType": "EXACT",
        "kingdom": "",
        "phylum": "",
        "class": "",
        "order": "",
        "family": "",
        "genus": "",
        "kingdomKey": 1,
        "phylumKey": 2,
        "classKey": 3,
        "orderKey": 4,
        "familyKey": 5,
        "genusKey": 6,
        "synonym": False,
        "alternatives": [],
    }
    base.update(overrides)
    return base


def test_gbif_fallback_wins_at_genus_before_worms_tries_family():
    result = resolver.resolve(
        "Nonexistentus madeupii",
        {"kingdom": "Animalia", "genus": "Suberitidae", "family": "Suberitidae"},
    )
    assert result.resolution_path == "gbif_fallback"
    assert result.authority == "gbif"


def test_gbif_win_still_carries_a_worms_lsid_when_worms_also_resolves():
    )
    result = resolver.resolve(
        "Some unrecognized synonym", {"kingdom": "Animalia", "genus": "Aaptidae"}
    )
    assert result.authority == "gbif"
    assert result.scientific_name_id == "urn:lsid:marinespecies.org:taxname:132064"


def test_gbif_win_follow_up_worms_lookup_rejects_a_wrong_kingdom_homonym():
    )
    result = resolver.resolve("Some unrecognized synonym", {"kingdom": "Chromista"})
    assert result.authority == "gbif"
    assert result.scientific_name_id == "urn:lsid:marinespecies.org:taxname:1"


    )
    result = resolver.resolve("Some unrecognized synonym", {"kingdom": "Plantae"})
    assert result.authority == "gbif"
    assert result.scientific_name_id == "urn:lsid:marinespecies.org:taxname:2"


def test_gbif_win_follow_up_worms_lookup_leaves_lsid_blank_on_an_unbreakable_tie():
    )
    result = resolver.resolve("Some unrecognized synonym", {"kingdom": "Plantae"})
    assert result.authority == "gbif"


def test_gbif_no_match_falls_through_to_terminal():
    result = resolver.resolve("Totally madeupii", {})
    assert result.resolution_path == "biota_fallback"


def test_gbif_gets_a_shot_at_the_terminal_name_with_no_rank_structure():
    )
    result = resolver.resolve("Aaptos", {})
    assert result.resolution_path == "gbif_fallback"
    assert result.authority == "gbif"


def test_gbif_homonym_disambiguated_by_source_phylum_is_not_flagged_for_review():
    assert result.resolution_path == "homonym_disambiguated"
    assert result.needs_review is False


def test_gbif_ambiguous_homonym_never_guesses():
    assert result.needs_review is True
    assert result.review_reason == "ambiguous_homonym"
    assert set(result.candidate_ids.split("|")) == {"1", "2"}


def test_gbif_homonym_source_mismatch_when_neither_candidate_agrees():
    )
    assert result.needs_review is True
    assert result.review_reason == "homonym_source_mismatch"
    assert set(result.candidate_ids.split("|")) == {"1", "2"}


def test_gbif_combined_phylum_and_class_narrows_a_phylum_only_tie():
        )
    )
    assert result.resolution_path == "homonym_disambiguated"
    assert result.needs_review is False



    )
    result = resolver.resolve("Old synonym name", {"kingdom": "Animalia"})
    assert result.scientific_name == "Accepted properly"
    assert result.taxon_concept_id == "https://www.gbif.org/species/999"
    assert result.review_reason == "gbif_synonym_resolved_to_accepted"


def test_gbif_synonym_follow_up_survives_explicit_nulls_in_the_species_record():
    result = resolver.resolve("Old synonym name", {"kingdom": "Animalia"})
    assert result.scientific_name == "Accepted properly"
    assert result.class_ == ""
    assert result.family == ""
    assert result.genus == ""
    assert result.scientific_name_authorship == ""


    def handler(request):
        if "AphiaRecordByAphiaID" in str(request.url):



def test_bare_aphia_id_also_recognized_as_source_taxon_id():
    result = resolver.resolve("anything", {}, source_taxon_id="132064")


def test_source_taxon_id_contradiction_is_disclosed_but_still_loses_to_the_id():
    result = resolver.resolve(
        {},
        source_taxon_id="urn:lsid:marinespecies.org:taxname:12",
    )
    assert result.scientific_name == "Biota incertae sedis"


def test_source_taxon_id_agreement_raises_no_contradiction_finding():
    result = resolver.resolve(
        "Aaptos", {}, source_taxon_id="urn:lsid:marinespecies.org:taxname:132064"
    )


def test_source_taxon_id_cross_check_ignores_a_weak_name_based_match():
    result = resolver.resolve(
        "Aaptos", {}, source_taxon_id="urn:lsid:marinespecies.org:taxname:12"
    )


def test_ncbi_taxid_takes_precedence_over_gbif_usage_key():
    )
    result = resolver.resolve("Aaptos", {"kingdom": "Animalia"}, ncbi_taxid="6544")
    assert result.taxon_concept_id == "NCBI:txid6544"


def test_taxon_unresolved_aggregates_every_row_into_one_finding():
    resolver = _resolver({})


def test_taxon_fuzzy_is_disclosed_when_a_non_confident_match_is_kept():
    result = resolver.resolve("Aaptos", {"kingdom": "Animalia"})
    assert result.review_reason == "non_confident_match_type:fuzzy"


def test_taxon_rejected_kingdom_is_disclosed_when_a_non_confident_candidate_is_rejected():
    )
    result = resolver.resolve("Weirdname", {"kingdom": "Animalia", "genus": "Aaptos"})


def test_gbif_fuzzy_kept_match_is_disclosed():
    )
    result = resolver.resolve("Someveryfuzzy", {"kingdom": "Animalia"})
    assert result.review_reason == "non_confident_match_type:FUZZY"
