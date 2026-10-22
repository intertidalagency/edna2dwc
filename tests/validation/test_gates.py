from __future__ import annotations

import duckdb
import pytest

from edna2dwc.common.tsv import write_tsv
from edna2dwc.dwca import writer
from edna2dwc.validation import gates, validate
from tests import manifests

TERM_TABLE = {
    "occurrenceID": {"uri": "u:occurrenceID", "priority_tier": "required"},
    "scientificName": {"uri": "u:scientificName", "priority_tier": "required"},
    "basisOfRecord": {"uri": "u:basisOfRecord"},
    "eventDate": {"uri": "u:eventDate", "format": "iso8601_date", "priority_tier": "required"},
    "recordedBy": {"uri": "u:recordedBy", "priority_tier": "strongly_recommended"},
}


@pytest.fixture
def archive_dir(tmp_path):
    core_path = tmp_path / "occurrence.tsv"
    write_tsv(
        [
            {
                "occurrenceID": "ds:s1:f1",
                "scientificName": "A",
                "basisOfRecord": "MaterialSample",
                "eventDate": "not a date",
            }
        ],
        core_path,
        columns=["occurrenceID", "scientificName", "basisOfRecord", "eventDate"],
    )
    out_dir = tmp_path / "archive"
    writer.write_archive(
        core_path=core_path,
        extensions={},
        manifest=manifests.required_manifest(),
        dataset_id="ds",
        generated_at="2024-06-01T00:00:00Z",
        term_table=TERM_TABLE,
        out_dir=out_dir,
    )
    return out_dir


def test_read_tables_reads_the_core_and_counts_format_failures(archive_dir):
    tables = gates.read_tables(archive_dir, TERM_TABLE, duckdb.connect())

    assert tables.core_header[:2] == ["occurrenceID", "scientificName"]
    assert tables.record_count == 1
    assert tables.all_headers == [tables.core_header]
    assert (tables.format_checked, tables.format_failed) == (1, 1)


def test_read_tables_refuses_a_directory_with_no_core(tmp_path):
    with pytest.raises(validate.ArchiveInvalidError):
        gates.read_tables(tmp_path, TERM_TABLE, duckdb.connect())


def test_check_gates_splits_the_term_tiers_and_leaves_unsupplied_gates_unmeasured(archive_dir):
    tables = gates.read_tables(archive_dir, TERM_TABLE, duckdb.connect())

    measured = gates.check_gates(
        tables,
        TERM_TABLE,
        states=[],
        mapping_path=None,
        term_states_path=None,
        intermediate_path=None,
        excluded_report_path=None,
    )

    assert measured.required_terms == (True, "")
    assert measured.strongly_recommended_terms == (False, "recordedBy (0/1 rows)")
    assert measured.valid_darwin_core_terms == (True, "")
    assert measured.mapping_description is None
    assert measured.every_term_has_a_state is None
    assert measured.row_accounting is None
    assert measured.measured_optional() == {}


def test_a_not_applicable_state_removes_the_term_from_the_missing_list(archive_dir, tmp_path):
    tables = gates.read_tables(archive_dir, TERM_TABLE, duckdb.connect())
    states_path = tmp_path / "term_states.tsv"
    write_tsv(
        [{"term": "recordedBy", "state": "Not-applicable", "evidence": "no collector"}],
        states_path,
        columns=["term", "state", "evidence"],
    )

    measured = gates.check_gates(
        tables,
        TERM_TABLE,
        states=gates.load_term_states(states_path),
        mapping_path=None,
        term_states_path=states_path,
        intermediate_path=None,
        excluded_report_path=None,
    )

    assert measured.strongly_recommended_terms == (True, "")


def test_row_accounting_compares_the_intermediate_against_the_core(archive_dir, tmp_path):
    tables = gates.read_tables(archive_dir, TERM_TABLE, duckdb.connect())
    intermediate = tmp_path / "occurrence_long.tsv"
    write_tsv(
        [
            {"sampleID": "s1", "featureID": "f1", "count": "3"},
            {"sampleID": "s1", "featureID": "f2", "count": "1"},
        ],
        intermediate,
        columns=["sampleID", "featureID", "count"],
    )

    measured = gates.check_gates(
        tables,
        TERM_TABLE,
        states=[],
        mapping_path=None,
        term_states_path=None,
        intermediate_path=intermediate,
        excluded_report_path=None,
    )

    gate = measured.row_accounting
    assert gate is not None
    passed, reason = gate
    assert passed is False
    assert measured.measured_optional() == {"row_accounting": gate}
    assert "2" in reason and "1" in reason


def test_run_obis_counts_rows_per_unaccepted_error_class(archive_dir):
    tables = gates.read_tables(archive_dir, TERM_TABLE, duckdb.connect())

    result = gates.run_obis(tables, adjudications={})

    assert result.ran is True
    assert all(count >= 1 for count in result.errors.values())
    assert len(result.error_findings) == len(result.errors)


def _gates_with_states(archive_dir, tmp_path, term_table, rows):
    states_path = tmp_path / "term_states.tsv"
    write_tsv(rows, states_path, columns=["term", "state", "evidence"])
    return gates.check_gates(
        gates.read_tables(archive_dir, term_table, duckdb.connect()),
        term_table,
        states=gates.load_term_states(states_path),
        mapping_path=None,
        term_states_path=states_path,
        intermediate_path=None,
        excluded_report_path=None,
    )


ANNEALING_TERM_TABLE = {
    **TERM_TABLE,
    "annealingTemp": {"uri": "u:annealingTemp", "priority_tier": "required"},
}


@pytest.mark.parametrize("evidence", ["not in the methods", ""])
def test_an_impossible_state_excuses_nothing(archive_dir, tmp_path, evidence):
    measured = _gates_with_states(
        archive_dir,
        tmp_path,
        ANNEALING_TERM_TABLE,
        [{"term": "annealingTemp", "state": "Impossible", "evidence": evidence}],
    )

    assert measured.required_terms == (False, "annealingTemp (0/1 rows)")


def _core_rows(archive_dir, rows: list[dict[str, str]], columns: list[str]) -> None:
    write_tsv(rows, archive_dir / "occurrence.txt", columns=columns)


def test_a_required_term_blank_on_every_row_counts_as_unfilled(archive_dir):
    _core_rows(
        archive_dir,
        [
            {
                "occurrenceID": "ds:s1:f1",
                "scientificName": "A",
                "basisOfRecord": "MaterialSample",
                "eventDate": "",
            }
        ],
        ["occurrenceID", "scientificName", "basisOfRecord", "eventDate"],
    )
    tables = gates.read_tables(archive_dir, TERM_TABLE, duckdb.connect())

    measured = _check(tables)

    assert measured.required_terms == (False, "eventDate (0/1 rows)")
    assert tables.fill["eventDate"] == (0, 1)


def test_the_gate_reports_the_share_of_rows_a_required_term_fills(archive_dir):
    _core_rows(
        archive_dir,
        [
            {
                "occurrenceID": "ds:s1:f1",
                "scientificName": "A",
                "basisOfRecord": "MaterialSample",
                "eventDate": "2024-01-15",
            },
            {
                "occurrenceID": "ds:s1:f2",
                "scientificName": "B",
                "basisOfRecord": "MaterialSample",
                "eventDate": "",
            },
        ],
        ["occurrenceID", "scientificName", "basisOfRecord", "eventDate"],
    )
    tables = gates.read_tables(archive_dir, TERM_TABLE, duckdb.connect())

    measured = _check(tables)

    assert measured.required_terms == (False, "eventDate (1/2 rows)")


def _check(tables: gates.ArchiveTables) -> gates.Gates:
    return gates.check_gates(
        tables,
        TERM_TABLE,
        states=[],
        mapping_path=None,
        term_states_path=None,
        intermediate_path=None,
        excluded_report_path=None,
    )


def test_an_impossible_state_never_excuses_a_term_the_archive_itself_requires(
    archive_dir, tmp_path
):
    term_table = {
        **TERM_TABLE,
        "scientificName": {
            "uri": "u:scientificName",
            "priority_tier": "required",
            "tier": "required",
        },
    }
    (archive_dir / "occurrence.txt").write_text(
        "occurrenceID\tbasisOfRecord\teventDate\nds:s1:f1\tMaterialSample\t2024-01-15\n",
        encoding="utf-8",
    )

    measured = _gates_with_states(
        archive_dir,
        tmp_path,
        term_table,
        [{"term": "scientificName", "state": "Impossible", "evidence": "classifier output lost"}],
    )

    assert measured.required_terms == (False, "scientificName (0/1 rows)")


@pytest.mark.parametrize("state", ["Not-applicable", "Impossible"])
def test_no_state_excuses_a_term_the_archive_itself_requires(archive_dir, tmp_path, state):
    term_table = {
        **TERM_TABLE,
        "occurrenceID": {"uri": "u:occurrenceID", "priority_tier": "required", "tier": "required"},
    }
    (archive_dir / "occurrence.txt").write_text(
        "scientificName\tbasisOfRecord\teventDate\nA\tMaterialSample\t2024-01-15\n",
        encoding="utf-8",
    )

    measured = _gates_with_states(
        archive_dir,
        tmp_path,
        term_table,
        [{"term": "occurrenceID", "state": state, "evidence": "hand-edited"}],
    )

    assert measured.required_terms == (False, "occurrenceID (0/1 rows)")
