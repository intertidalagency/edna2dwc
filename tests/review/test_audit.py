from __future__ import annotations

import json

import pytest

from edna2dwc.review.audit import (
    build_audit_prompt,
    load_audit_result,
    load_recorded_audit,
    record_audit,
)


def test_check_3_tells_the_auditor_to_open_what_the_provenance_names():
    prompt = build_audit_prompt(source_paths=["raw.csv"], archive_dir="/archive")
    check_3 = prompt.split("3. ")[1].split("4. ")[0]
    assert "provenance:" in check_3
    assert "spot-check" in check_3


def test_audit_prompt_fills_in_source_and_archive_paths():
    prompt = build_audit_prompt(source_paths=["a.csv", "b.csv"], archive_dir="/out/archive")
    assert "a.csv, b.csv" in prompt
    assert "/out/archive" in prompt


def test_audit_prompt_defines_a_fabrication_as_traceable_to_neither_source_nor_register():
    prompt = build_audit_prompt(source_paths=["raw.csv"], archive_dir="/archive")
    assert "reproduce/resolved_taxonomy.tsv" in prompt
    assert "resolution_path" in prompt
    assert "authority" in prompt


@pytest.mark.parametrize("findings", [[], ["a", "b"]])
def test_load_audit_result_reads_findings(tmp_path, findings):
    path = tmp_path / "audit_result.json"
    path.write_text(json.dumps({"findings": findings}), encoding="utf-8")
    assert load_audit_result(path) == findings


@pytest.mark.parametrize(
    "content",
    [
        json.dumps([{"findings": []}]),
        json.dumps({}),
        json.dumps({"findings": "a bad row"}),
        json.dumps({"findings": [{"row": 3}]}),
        "{not json",
    ],
)
def test_load_audit_result_rejects_a_file_that_is_not_the_result_schema(tmp_path, content):
    path = tmp_path / "audit_result.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="findings"):
        load_audit_result(path)


def test_load_audit_result_refuses_a_key_other_than_findings_and_names_it(tmp_path):
    path = tmp_path / "audit_result.json"
    path.write_text(json.dumps({"findings": [], "summary": "all fine"}), encoding="utf-8")
    with pytest.raises(ValueError, match="'summary'"):
        load_audit_result(path)


def test_audit_prompt_states_the_result_schema_audit_record_reads(tmp_path):
    prompt = build_audit_prompt(source_paths=["raw.csv"], archive_dir="/archive")
    schema = prompt[prompt.index("{", prompt.index("audit record")) :]
    example = json.loads(schema[: schema.index("}") + 1])
    path = tmp_path / "audit_result.json"
    path.write_text(json.dumps(example), encoding="utf-8")
    assert load_audit_result(path)


def test_record_audit_round_trips(tmp_path):
    record_audit(tmp_path / "audit_record.json", ["issue"])
    assert load_recorded_audit(tmp_path / "audit_record.json") == (["issue"], True)


def test_load_recorded_audit_is_none_when_nothing_was_recorded(tmp_path):
    assert load_recorded_audit(tmp_path / "audit_record.json") is None


def test_audit_prompt_expects_file_names_and_pipeline_bookkeeping_to_be_dropped():
    prompt = build_audit_prompt(source_paths=["raw.csv"], archive_dir="/archive")
    assert "FASTQ" in prompt
    assert "associatedSequences" in prompt


def test_the_audit_prompt_asks_the_auditor_to_read_every_reader_script():
    prompt = build_audit_prompt(source_paths=["data/counts.csv"], archive_dir="archive")
    assert "reproduce/scripts/" in prompt
    assert "answers.yaml" in prompt.split("reproduce/scripts/")[1]


def test_the_audit_prompt_asks_for_an_empty_findings_list_when_nothing_turned_up():
    prompt = build_audit_prompt(source_paths=["raw.csv"], archive_dir="/archive")
    assert "no issues found" not in prompt
    assert "an empty `findings` list" in prompt


def test_record_audit_keeps_the_digest_of_the_archive_it_was_made_against(tmp_path):
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "dwca.zip").write_bytes(b"first build")
    record = tmp_path / "audit_record.json"

    record_audit(record, ["invented a depth"], archive_dir=archive)

    assert load_recorded_audit(record, archive_dir=archive) == (["invented a depth"], False)
    (archive / "dwca.zip").write_bytes(b"second build")
    assert load_recorded_audit(record, archive_dir=archive) == (["invented a depth"], True)


def test_a_record_with_no_digest_reads_as_made_against_an_unknown_build(tmp_path):
    record = tmp_path / "audit_record.json"
    record.write_text('{"findings": ["x"]}')
    assert load_recorded_audit(record, archive_dir=tmp_path) == (["x"], True)
