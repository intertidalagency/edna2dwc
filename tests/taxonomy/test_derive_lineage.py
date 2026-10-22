from __future__ import annotations

    RANK_COLUMNS,
    derive_lineage,
    lineage_key,
    parse_taxonomy_string,
)


def test_parses_the_d_prefix_grammar():
    parsed = parse_taxonomy_string("d__Bacteria;p__Cyanobacteria")
    assert parsed.ranks == {"kingdom": "Bacteria", "phylum": "Cyanobacteria"}
    assert parsed.terminal == "Cyanobacteria"


    parsed = parse_taxonomy_string("Unassigned")
    assert parsed.ranks == {}


def test_anchored_stripping_only_matches_real_rank_prefixes():
    parsed = parse_taxonomy_string("d__Bacteria;weird__thing")
    assert parsed.terminal == "weird__thing"
    assert parsed.ranks == {"kingdom": "Bacteria"}


def test_terminal_is_the_deepest_non_blank_token():
    parsed = parse_taxonomy_string("d__Bacteria;p__;c__;o__;f__;g__")
    assert parsed.terminal == "Bacteria"
    assert parsed.ranks == {"kingdom": "Bacteria"}


    ranks = {"kingdom": "Bacteria", "phylum": "Cyanobacteria"}


def test_derive_lineage_dedupes_identical_tuples_and_counts_rows():
    rows = [
        {
            "sampleID": "S1",
            "featureID": "f1",
            "count": "1",
            "taxonomy": "d__Bacteria;p__Cyanobacteria",
        },
        {
            "sampleID": "S2",
            "featureID": "f2",
            "count": "1",
            "taxonomy": "d__Bacteria;p__Cyanobacteria",
        },
        {
            "sampleID": "S3",
            "featureID": "f3",
            "count": "1",
            "taxonomy": "d__Bacteria;p__Firmicutes",
        },
    ]
    assert len(result.lineage_rows) == 2
    by_terminal = {r["terminal_name"]: r for r in result.lineage_rows}
    assert by_terminal["Cyanobacteria"]["row_count"] == "2"
    assert by_terminal["Firmicutes"]["row_count"] == "1"


def test_placeholder_terminal_does_not_collapse_distinct_lineages():
    rows = [
        {
            "sampleID": "S1",
            "featureID": "f1",
            "count": "1",
            "taxonomy": "d__Bacteria;p__Cyanobacteria;s__",
        },
        {
            "sampleID": "S2",
            "featureID": "f2",
            "count": "1",
            "taxonomy": "d__Bacteria;p__Firmicutes;s__",
        },
    ]
    assert len({r["lineage_key"] for r in result.lineage_rows}) == 2


def test_already_split_rank_columns_phyloseq_style():
    rows = [
        {
            "sampleID": "S1",
            "featureID": "f1",
            "count": "1",
            "Kingdom": "Bacteria",
            "Phylum": "Cyanobacteria",
        }
    ]
    assert result.lineage_rows[0]["terminal_name"] == "Cyanobacteria"
    assert result.lineage_rows[0]["source_phylum"] == "Cyanobacteria"


def test_bare_scientific_name_with_no_rank_structure_at_all():
    rows = [{"sampleID": "S1", "featureID": "f1", "count": "1", "scientificName": "Acartia tonsa"}]
    assert result.lineage_rows[0]["terminal_name"] == "Acartia tonsa"
    assert all(result.lineage_rows[0][f"source_{r}"] == "" for r in RANK_COLUMNS)


def test_ncbi_taxid_and_source_taxon_id_carried_onto_lineage_row_when_present():
    rows = [
        {
            "sampleID": "S1",
            "featureID": "f1",
            "count": "1",
            "taxonomy": "d__Bacteria",
            "ncbi_taxid": "1224",
            "source_taxon_id": "urn:lsid:marinespecies.org:taxname:2",
        }
    ]
    assert result.lineage_rows[0]["ncbi_taxid"] == "1224"
    assert result.lineage_rows[0]["source_taxon_id"] == "urn:lsid:marinespecies.org:taxname:2"
