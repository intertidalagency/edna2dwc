from __future__ import annotations

import pytest
import yaml



    path = tmp_path / "conversion.yaml"
    path.write_text(yaml.safe_dump({"dataset_id": "ds1"}), encoding="utf-8")


    assert step.n == 1


    path.write_text(yaml.safe_dump({"dataset_id": "ds1"}), encoding="utf-8")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert raw["dataset_id"] == "ds1"
    assert len(raw["steps"]) == 1


    assert (first.n, second.n) == (1, 2)






    assert step.script == "scripts/patch.py"








def test_vendor_script_copies_verbatim_content(tmp_path):
    script = tmp_path / "src" / "reader.py"
    script.parent.mkdir()
    scripts_dir = tmp_path / "scripts"


    assert dest == scripts_dir / "reader.py"
    assert dest.read_text() == "x = 1\n"


def test_vendor_script_re_vendoring_the_identical_script_is_a_noop(tmp_path):
    script = tmp_path / "reader.py"
    scripts_dir = tmp_path / "scripts"

    assert dest.read_text() == "x = 1\n"


def test_vendor_script_refuses_to_overwrite_a_different_script_under_the_same_name(tmp_path):
    scripts_dir = tmp_path / "scripts"
    first = tmp_path / "one" / "reader.py"
    first.parent.mkdir()
    first.write_text("x = 1\n", encoding="utf-8")

    second = tmp_path / "two" / "reader.py"
    second.parent.mkdir()
    second.write_text("x = 2\n", encoding="utf-8")

    assert (scripts_dir / "reader.py").read_text() == "x = 1\n"
