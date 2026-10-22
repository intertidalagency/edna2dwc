from __future__ import annotations

import json

from tests.inputs.test_document_text import write_docx


def test_text_prints_each_file_under_its_name_and_names_one_it_cannot_read(run_cli, tmp_path):
    readable = tmp_path / "protocol.docx"
    write_docx(readable, "Primers: MiFish-U")
    unreadable = tmp_path / "methods.pdf"
    unreadable.write_bytes(b"not a pdf")
    result = run_cli(["text", str(readable), str(unreadable)])
    assert result.exit_code == 0
    assert f"==> {readable} <==\nPrimers: MiFish-U\n" in result.text
    assert f"==> {unreadable} <==\nunreadable: " in result.text


def test_text_as_json_maps_each_path_to_its_text(run_cli, tmp_path):
    path = tmp_path / "protocol.docx"
    write_docx(path, "Primers: MiFish-U")
    result = run_cli(["text", str(path), "--json"])
    assert json.loads(result.render()) == {str(path): "Primers: MiFish-U\n"}
