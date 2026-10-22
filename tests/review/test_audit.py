from __future__ import annotations

import json

import pytest

    build_audit_prompt,
    load_audit_result,
    load_recorded_audit,
    record_audit,
)


    prompt = build_audit_prompt(source_paths=["raw.csv"], archive_dir="/archive")
    check_3 = prompt.split("3. ")[1].split("4. ")[0]


def test_audit_prompt_fills_in_source_and_archive_paths():
    prompt = build_audit_prompt(source_paths=["a.csv", "b.csv"], archive_dir="/out/archive")
    assert "a.csv, b.csv" in prompt
    assert "/out/archive" in prompt


    path = tmp_path / "audit_result.json"




def test_load_recorded_audit_is_none_when_nothing_was_recorded(tmp_path):
