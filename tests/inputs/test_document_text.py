from __future__ import annotations

import logging
from pathlib import Path
import zipfile

import pytest

from edna2dwc.inputs.document_text import UnreadableDocument, document_text
from tests.paths import INPUT_FIXTURES


def write_pdf(path: Path, line: str) -> None:
    stream = f"BT /F1 12 Tf 72 720 Td ({line}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>"
        ),
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    body = b"%PDF-1.4\n"
    offsets = []
    for number, content in enumerate(objects, start=1):
        offsets.append(len(body))
        body += b"%d 0 obj\n%s\nendobj\n" % (number, content)
    xref = len(body)
    body += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    body += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    body += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    path.write_bytes(body)


def write_docx(path: Path, *paragraphs: str) -> None:
    namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    runs = "".join(f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" for text in paragraphs)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "word/document.xml",
            f'<w:document xmlns:w="{namespace}"><w:body>{runs}</w:body></w:document>',
        )


def test_a_pdf_gives_the_text_of_its_pages(tmp_path):
    path = tmp_path / "methods.pdf"
    write_pdf(path, "Annealing at 55 C")
    assert "Annealing at 55 C" in document_text(path)


def test_a_docx_gives_one_line_per_paragraph(tmp_path):
    path = tmp_path / "protocol.docx"
    write_docx(path, "Primers: MiFish-U", "Annealing at 55 C")
    assert document_text(path) == "Primers: MiFish-U\nAnnealing at 55 C\n"


def test_a_workbook_gives_each_sheet_as_tab_separated_rows():
    text = document_text(INPUT_FIXTURES / "multisheet.xlsx")
    assert "## Samples\nSample Name\tSite\tDepth (m)\nS001\tNorth Reef\t12.5\n" in text
    assert "## Taxonomy\n" in text


def test_max_chars_stops_reading_early(tmp_path):
    path = tmp_path / "protocol.docx"
    write_docx(path, "Primers: MiFish-U", "Annealing at 55 C")
    assert document_text(path, max_chars=7) == "Primers"


@pytest.mark.parametrize("name", ["methods.pdf", "protocol.docx", "methods.doc"])
def test_a_file_that_is_not_what_its_name_says_is_unreadable(tmp_path, name):
    path = tmp_path / name
    path.write_bytes(b"%PDF-1.4 \xff\xfe not text")
    with pytest.raises(UnreadableDocument, match=name):
        document_text(path)


def test_reading_a_pdf_silences_the_pdf_librarys_font_warnings(tmp_path):
    path = tmp_path / "methods.pdf"
    write_pdf(path, "Filtered 1 L of seawater")
    document_text(path)
    assert not logging.getLogger("pypdf").isEnabledFor(logging.WARNING)
