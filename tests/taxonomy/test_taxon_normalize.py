from __future__ import annotations



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


