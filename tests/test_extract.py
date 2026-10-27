from pathlib import Path

import fitz
import pytest
from docx import Document

from app.extract import (
    UnsupportedFileTypeError,
    UnsupportedScannedPDFError,
    extract_document,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_extract_txt_with_line_locations():
    result = extract_document(FIXTURES / "synthetic_case.txt")
    assert result.file_type == "txt"
    assert "Morgan Example" in result.text
    assert any(segment.location == "line 2" for segment in result.segments)


def test_extract_pdf_with_page_location():
    result = extract_document(FIXTURES / "synthetic_case.pdf")
    assert result.file_type == "pdf"
    assert "morgan.example@example.invalid" in result.text
    assert result.segments[0].location == "page 1"


def test_extract_docx_includes_paragraph_table_header_and_footer():
    result = extract_document(FIXTURES / "synthetic_case.docx")
    assert result.file_type == "docx"
    assert "Morgan Example" in result.text
    assert "morgan.example@example.invalid" in result.text
    assert "FAKE-FOOTER-001" in result.text
    locations = [segment.location for segment in result.segments]
    assert any(location.startswith("table 1") for location in locations)
    assert any("header" in location for location in locations)
    assert any("footer" in location for location in locations)


def test_rejects_pdf_with_insufficient_extractable_text(tmp_path):
    path = tmp_path / "scanned_like.pdf"
    with fitz.open() as pdf:
        page = pdf.new_page()
        # Drawing a rectangle simulates an image-only/scanned page: no text layer.
        page.draw_rect(fitz.Rect(50, 50, 250, 250), color=(0, 0, 0))
        pdf.save(path)

    with pytest.raises(UnsupportedScannedPDFError) as error:
        extract_document(path)
    assert error.value.pages == [1]


def test_rejects_unsupported_extension(tmp_path):
    path = tmp_path / "image.png"
    path.write_bytes(b"not actually an image")
    with pytest.raises(UnsupportedFileTypeError):
        extract_document(path)
