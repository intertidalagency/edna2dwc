from __future__ import annotations

import pytest

from edna2dwc.taxonomy.taxon_normalize import normalize_name


def test_strips_authorship_after_first_comma():
    assert normalize_name("Acartia tonsa, Dana 1849") == "Acartia tonsa"


def test_strips_parenthesized_author():
    assert normalize_name("Acartia (Acanthacartia) tonsa (Dana, 1849)") == "Acartia tonsa"


def test_strips_trailing_year_with_no_comma():
    assert normalize_name("Genus species 1849") == "Genus species"


def test_strips_sp_and_cf_and_aff():
    assert normalize_name("Genus sp.") == "Genus"
    assert normalize_name("Genus cf. species") == "Genus species"
    assert normalize_name("Genus aff. species") == "Genus species"


def test_collapses_whitespace():
    assert normalize_name("Genus    species") == "Genus species"


@pytest.mark.parametrize(
    "label",
    [
        "Cyanobium_PCC-6307",
        "SAR11_clade_Ia",
        "MALV-II_X",
        "Bacteroidetes_BD2-2",
        "Marinimicrobia_(SAR406_clade)",
        "Synechococcus_CC9902",
        "hydrothermal_vent",
    ],
)
def test_a_label_with_an_underscore_is_not_a_name(label):
    assert normalize_name(label) == ""


def test_an_underscore_joined_latin_name_reads_as_spaced():
    assert normalize_name("Mytilus_edulis") == "Mytilus edulis"
    assert normalize_name("Candidatus_Pelagibacter") == "Candidatus Pelagibacter"


def test_drops_a_strain_code_after_the_epithet():
    assert normalize_name("Pelagibacter ubique HTCC1062") == "Pelagibacter ubique"


def test_drops_an_author_citation_however_it_is_written():
    assert normalize_name("Gadus morhua Linnaeus, 1758") == "Gadus morhua"
    assert normalize_name("Gadus morhua (Linnaeus, 1758)") == "Gadus morhua"
    assert normalize_name("Homo sapiens Linnaeus 1758") == "Homo sapiens"
    assert normalize_name("Gadidae Rafinesque, 1810") == "Gadidae"


def test_keeps_the_candidatus_prefix():
    assert normalize_name("Candidatus Pelagibacter ubique HTCC1062") == (
        "Candidatus Pelagibacter ubique"
    )


def test_keeps_an_infraspecific_rank_marker():
    assert normalize_name("Genus species var. alba Author") == "Genus species var. alba"
    assert normalize_name("Genus species subsp. alba") == "Genus species subsp. alba"


def test_keeps_a_one_word_name_followed_by_something_other_than_a_citation():
    assert normalize_name("Bacteroidetes BD2-2") == "Bacteroidetes BD2-2"


def test_ends_the_name_at_sp():
    assert normalize_name("Austrarchaea sp. QLD") == "Austrarchaea"


def test_normalizes_each_part_of_a_compound_name():
    assert normalize_name("Gadus morhua Linnaeus / Gadus chalcogrammus Pallas") == (
        "Gadus morhua/Gadus chalcogrammus"
    )
    assert normalize_name("Genus a or b") == "Genus a or b"


@pytest.mark.parametrize(
    "hybrid",
    [
        "Salmo salar × Salmo trutta",
        "Salmo salar x Salmo trutta",
        "Salmo salar X Salmo trutta",
        "Salmo salar × trutta",
        "Salmo salar ×trutta",
    ],
)
def test_keeps_a_hybrid_formula_whole_rather_than_naming_one_parent(hybrid):
    assert normalize_name(hybrid) == hybrid


@pytest.mark.parametrize(
    ("name", "normalized"),
    [
        ("Gadus morhua, other Gadidae", "Gadus morhua, Gadidae"),
        ("Phoca largha, others", "Phoca largha"),
        ("Branta canadensis, other Anatidae", "Branta canadensis, Anatidae"),
        ("Acartia tonsa, Dana 1849", "Acartia tonsa"),
        ("Gadus morhua Linnaeus, 1758", "Gadus morhua"),
        ("Pseudocalanus moultoni", "Pseudocalanus moultoni"),
        ("Chrysochromulina_sp.", ""),
        ("Eupelagonemidae_X_sp.", ""),
        ("MAST-2B_sp.", ""),
        ("Haptophyta_X", ""),
        ("Candidatus_Thioglobus", "Candidatus Thioglobus"),
        ("HOC36", "HOC36"),
        ("Sva0996_marine_group", ""),
        ("uncultured_marine", ""),
        ("Diaphus theta", "Diaphus theta"),
        ("Akashiwo sanguinea", "Akashiwo sanguinea"),
    ],
)
def test_a_real_source_name_normalizes_to_the_name_a_register_can_answer(name, normalized):
    assert normalize_name(name) == normalized
