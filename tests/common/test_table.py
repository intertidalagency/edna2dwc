from __future__ import annotations

import errno
from pathlib import Path

import pytest

from edna2dwc.common import table as table_module
from edna2dwc.common.table import (
    ROW,
    connect,
    lookup,
    read_delimited,
    read_tsv,
    read_unpivoted,
    write_tsv,
)
from tests.tables import dicts, table_of


def test_columns_that_differ_only_in_case_stay_apart(tmp_path):
    path = tmp_path / "occurrence_long.tsv"
    path.write_text("﻿sampleID\tLat\tlat\nS1\t10\t20\n", encoding="utf-8")

    with connect() as con:
        table = read_tsv(con, path, "source")

        assert table.columns == ["sampleID", "Lat", "lat"]
        assert dicts(table) == [{"sampleID": "S1", "Lat": "10", "lat": "20"}]


def test_an_empty_cell_is_read_as_empty_not_missing(tmp_path):
    path = tmp_path / "occurrence_long.tsv"
    path.write_text("sampleID\tmarker\nS1\t\n", encoding="utf-8")

    with connect() as con:
        assert dicts(read_tsv(con, path, "source")) == [{"sampleID": "S1", "marker": ""}]


def test_a_repeated_column_name_keeps_its_last_value(tmp_path):
    path = tmp_path / "occurrence_long.tsv"
    path.write_text("sampleID\tsite\tsite\nS1\ta\tb\n", encoding="utf-8")

    with connect() as con:
        assert dicts(read_tsv(con, path, "source")) == [{"sampleID": "S1", "site": "b"}]


def test_a_quoted_line_break_stays_inside_its_value(tmp_path):
    path = tmp_path / "samples.csv"
    path.write_text('sampleID,remarks\nS1,"a\nb"\nS2,plain\n', encoding="utf-8", newline="")

    with connect() as con:
        assert dicts(read_delimited(con, path, "source")) == [
            {"sampleID": "S1", "remarks": "a\nb"},
            {"sampleID": "S2", "remarks": "plain"},
        ]


def test_a_wide_table_is_read_within_the_memory_limit_in_file_order(tmp_path, monkeypatch):
    monkeypatch.setenv(table_module.MEMORY_LIMIT_ENV, "192MB")
    samples = 100
    path = tmp_path / "wide.tsv"
    filler = "\t1" * (samples - 1)
    with path.open("w", encoding="utf-8") as out:
        out.write("row" + "".join(f"\tS{i}" for i in range(1, samples)) + "\n")
        out.writelines(f"{row}{filler}\n" for row in range(150_000))

    with connect() as con:
        table = read_tsv(con, path, "source")

        assert table.count() == 150_000
        assert table.count(f"{ROW} <> CAST(row AS BIGINT)") == 0


def test_an_unpivoted_read_keeps_file_order_across_its_column_groups(tmp_path, monkeypatch):
    monkeypatch.setattr(table_module, "COLUMNS_PER_READ", 2)
    path = tmp_path / "wide.csv"
    path.write_text("id,a,b,c\nx,1,0,3\ny,4,5,0\n", encoding="utf-8")

    with connect() as con:
        table = read_unpivoted(con, path, "long", ["id"], '"^_name"', "value", "value <> '0'")
        found = table.rows(f'SELECT {ROW}, id, "^_name", value FROM long ORDER BY {ROW}, "^_name"')

    assert found == [
        (0, "x", "a", "1"),
        (0, "x", "c", "3"),
        (1, "y", "a", "4"),
        (1, "y", "b", "5"),
    ]


def test_a_written_table_keeps_its_header_and_row_order(tmp_path):
    table = table_of([{"Lat": "1", "lat": "a\tb"}, {"Lat": "2"}])
    path = tmp_path / "out.tsv"

    write_tsv(table, path, ["lat", "Lat"])

    assert path.read_text(encoding="utf-8") == "lat\tLat\na b\t1\n\t2\n"


@pytest.mark.parametrize(
    "value, expected",
    [("a\tb", "a b"), ("a\t\t\tb", "a b"), ("a\r\nb", "a b"), ("plain", "plain"), ("", "")],
)
def test_a_written_table_can_collapse_a_run_of_breaks(tmp_path, value, expected):
    path = tmp_path / "out.tsv"

    write_tsv(table_of([{"a": value}]), path, ["a"], collapse_breaks=True)

    assert path.read_text(encoding="utf-8") == f"a\n{expected}\n"


def test_a_table_with_no_columns_is_written_as_an_empty_file(tmp_path):
    path = tmp_path / "out.tsv"

    write_tsv(table_of([]), path, [])

    assert Path(path).read_text(encoding="utf-8") == ""


def test_a_table_written_in_batches_keeps_its_order_across_them(tmp_path, monkeypatch):
    monkeypatch.setattr(table_module, "WRITE_BATCH_BYTES", 10)
    path = tmp_path / "out.tsv"

    write_tsv(
        table_of([{"n": f"{n:02d}"} for n in reversed(range(30))]), path, ["n"], order=('"n"',)
    )

    assert path.read_text(encoding="utf-8").split() == ["n", *(f"{n:02d}" for n in range(30))]


def test_an_order_that_names_two_rows_alike_is_refused(tmp_path):
    with pytest.raises(ValueError, match="share their place in the file"):
        write_tsv(table_of([{"n": "1"}, {"n": "1"}]), tmp_path / "out.tsv", ["n"], order=('"n"',))


def _memory_limit_of_a_connection() -> str:
    with connect() as con:
        [(limit,)] = con.execute("SELECT current_setting('memory_limit')").fetchall()
    return limit


def test_the_memory_limit_environment_variable_sets_the_limit(monkeypatch):
    monkeypatch.setenv(table_module.MEMORY_LIMIT_ENV, "300MiB")
    assert _memory_limit_of_a_connection() == "300.0 MiB"


def test_the_default_memory_limit_is_a_share_of_the_memory_the_process_can_use(monkeypatch):
    monkeypatch.delenv(table_module.MEMORY_LIMIT_ENV, raising=False)
    monkeypatch.setattr(table_module, "usable_memory", lambda: 4 << 30)
    assert _memory_limit_of_a_connection() == "2.0 GiB"


def test_a_container_limit_below_the_machine_memory_is_the_usable_memory(tmp_path, monkeypatch):
    cgroup = tmp_path / "memory.max"
    cgroup.write_text(f"{1 << 30}\n", encoding="utf-8")
    monkeypatch.setattr(table_module, "CGROUP_LIMITS", (tmp_path / "absent", cgroup))
    assert table_module.usable_memory() == 1 << 30


def test_an_unlimited_container_leaves_the_machine_memory(tmp_path, monkeypatch):
    cgroup = tmp_path / "memory.max"
    cgroup.write_text("max\n", encoding="utf-8")
    monkeypatch.setattr(table_module, "CGROUP_LIMITS", (cgroup,))
    assert table_module.usable_memory() > 1 << 30


def test_running_out_of_memory_names_the_limit_the_free_disk_and_the_setting(monkeypatch):
    monkeypatch.setenv(table_module.MEMORY_LIMIT_ENV, "1MB")
    with pytest.raises(table_module.ResourceLimitError) as raised, connect() as con:
        con.execute("SELECT string_agg(i::VARCHAR, ',') FROM range(1000000) t(i)")
    message = str(raised.value)
    assert all(part in message for part in ("1MB", "free", table_module.MEMORY_LIMIT_ENV))


def test_a_full_disk_names_the_free_disk_and_the_setting():
    with pytest.raises(table_module.ResourceLimitError) as raised, connect():
        raise OSError(errno.ENOSPC, "No space left on device")
    message = str(raised.value)
    assert all(part in message for part in ("full", "TMPDIR", table_module.MEMORY_LIMIT_ENV))


def test_an_error_that_is_not_about_memory_or_disk_passes_through():
    with pytest.raises(FileNotFoundError), connect():
        raise FileNotFoundError("tables/counts.csv")


def test_a_memory_limit_that_is_not_a_size_is_refused_by_name(monkeypatch):
    monkeypatch.setenv(table_module.MEMORY_LIMIT_ENV, "lots")
    with pytest.raises(table_module.ResourceLimitError, match="EDNA2DWC_MEMORY_LIMIT='lots'"):
        _memory_limit_of_a_connection()


def test_a_lookup_converts_every_distinct_value_however_many_batches_it_takes(monkeypatch):
    monkeypatch.setattr(table_module, "LOOKUP_BATCH_ROWS", 2)
    table = table_of([{"value": str(n % 5)} for n in range(12)])

    found = lookup(
        table,
        "doubled",
        ["value"],
        {"doubled": "VARCHAR"},
        lambda value: (str(int(value) * 2),),
        keep=lambda values, _: values != ("3",),
    )

    assert sorted(found.rows(f"SELECT * FROM {found.name}")) == [
        ("0", "0"),
        ("1", "2"),
        ("2", "4"),
        ("4", "8"),
    ]
