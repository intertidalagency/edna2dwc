from edna2dwc.dwca import dna_derived_data
from tests.tables import dicts, table_of

TERM_TABLE = {
    "occurrenceID": {"uri": "http://rs.tdwg.org/dwc/terms/occurrenceID", "class": "Occurrence"},
    "scientificName": {"uri": "http://rs.tdwg.org/dwc/terms/scientificName", "class": "Taxon"},
    "basisOfRecord": {
        "uri": "http://rs.tdwg.org/dwc/terms/basisOfRecord",
        "class": "record-level",
    },
    "kingdom": {"uri": "http://rs.tdwg.org/dwc/terms/kingdom", "class": "Taxon"},
    "DNA_sequence": {"uri": "http://rs.gbif.org/terms/dna_sequence", "class": "DNADerivedData"},
    "target_gene": {
        "uri": "https://w3id.org/gensc/terms/MIXS:0000044",
        "class": "DNADerivedData",
    },
    "dynamicProperties": {
        "uri": "http://rs.tdwg.org/dwc/terms/dynamicProperties",
        "class": "record-level",
    },
}

CORE_COLUMNS = [
    "occurrenceID",
    "scientificName",
    "basisOfRecord",
    "kingdom",
    "DNA_sequence",
    "target_gene",
]

CORE_ROWS = [
    {
        "occurrenceID": "ds1_s1_f1",
        "scientificName": "Mytilus californianus",
        "basisOfRecord": "MaterialSample",
        "kingdom": "Animalia",
        "DNA_sequence": "ACGTACGT",
        "target_gene": "18S",
    },
    {
        "occurrenceID": "ds1_s2_f1",
        "scientificName": "Mytilus californianus",
        "basisOfRecord": "MaterialSample",
        "kingdom": "Animalia",
        "DNA_sequence": "TTGGCCAA",
        "target_gene": "18S",
    },
]


def test_select_dna_columns_picks_every_dna_derived_data_classed_column():
    selected = dna_derived_data.select_dna_columns(CORE_COLUMNS, TERM_TABLE)
    assert selected == ["DNA_sequence", "target_gene"]


def test_select_dna_columns_never_selects_the_id_column():
    term_table = TERM_TABLE | {"occurrenceID": {"class": "DNADerivedData"}}
    selected = dna_derived_data.select_dna_columns(CORE_COLUMNS, term_table)
    assert "occurrenceID" not in selected


def test_select_dna_columns_ignores_a_column_absent_from_the_term_table():
    selected = dna_derived_data.select_dna_columns(["occurrenceID", "mystery"], TERM_TABLE)
    assert selected == []


def _dna(rows, columns=CORE_COLUMNS):
    return dna_derived_data.select_and_build_dna(table_of(rows), columns, TERM_TABLE)


def test_select_and_build_dna_moves_the_columns_out_of_the_core():
    result = _dna(CORE_ROWS)
    assert result.core_header == ["occurrenceID", "scientificName", "basisOfRecord", "kingdom"]
    assert result.dna_header == ["occurrenceID", "DNA_sequence", "target_gene"]
    assert result.dna is not None
    assert dicts(result.dna) == [
        {"occurrenceID": "ds1_s1_f1", "DNA_sequence": "ACGTACGT", "target_gene": "18S"},
        {"occurrenceID": "ds1_s2_f1", "DNA_sequence": "TTGGCCAA", "target_gene": "18S"},
    ]


def test_select_and_build_dna_skips_a_row_with_no_dna_values_at_all():
    rows = [*CORE_ROWS, {"occurrenceID": "ds1_s3_f1", "DNA_sequence": "", "target_gene": ""}]
    result = _dna(rows)
    assert result.dna is not None
    assert [r["occurrenceID"] for r in dicts(result.dna)] == ["ds1_s1_f1", "ds1_s2_f1"]


def test_select_and_build_dna_discloses_what_it_routed():
    findings = _dna(CORE_ROWS).findings.findings
    assert [(f.code, f.message) for f in findings] == [
        (
            "DNA_TERMS_ROUTED",
            "moved into the DNADerivedData extension, keyed by occurrenceID: DNA_sequence, target_gene",
        )
    ]


def test_select_and_build_dna_is_a_no_op_when_nothing_is_dna_classed():
    columns = ["occurrenceID", "scientificName", "basisOfRecord"]
    rows = [{c: r[c] for c in columns} for r in CORE_ROWS]
    result = _dna(rows, columns)
    assert result.core_header == columns
    assert result.dna is None
    assert result.findings.findings == []
