from zipfile import ZipFile
from pathlib import Path

from docx import Document

from app.models import Finding
from app.redact_docx import redact_docx


def finding(text, approved=True):
    return Finding(
        id="synthetic-id", text=text, category="EMAIL", source_layer="regex",
        reason="synthetic test", location=None, approved=approved,
    )


def test_redacts_docx_paragraph_and_table_text_and_verifies(tmp_path):
    src, dst = tmp_path / "in.docx", tmp_path / "out.docx"
    doc = Document()
    doc.add_paragraph("Contact morgan@example.invalid")
    table = doc.add_table(rows=1, cols=1)
    table.cell(0, 0).text = "Repeat morgan@example.invalid"
    doc.save(src)

    result = redact_docx(src, dst, [finding("morgan@example.invalid")])
    assert result["verified_clean"] is True
    assert result["redacted_occurrences"] == 2
    reopened = Document(dst)
    all_text = "\n".join(p.text for p in reopened.paragraphs)
    all_text += "\n" + "\n".join(c.text for t in reopened.tables for row in t.rows for c in row.cells)
    assert "morgan@example.invalid" not in all_text
    assert "[REDACTED]" in all_text


def test_redacts_header_and_footer_text(tmp_path):
    src, dst = tmp_path / "in.docx", tmp_path / "out.docx"
    doc = Document()
    section = doc.sections[0]
    section.header.paragraphs[0].text = "Header: morgan@example.invalid"
    section.footer.paragraphs[0].text = "Footer: morgan@example.invalid"
    doc.add_paragraph("Synthetic body text long enough for the test.")
    doc.save(src)

    result = redact_docx(src, dst, [finding("morgan@example.invalid")])
    assert result["verified_clean"] is True
    reopened = Document(dst)
    assert "morgan@example.invalid" not in reopened.sections[0].header.paragraphs[0].text
    assert "morgan@example.invalid" not in reopened.sections[0].footer.paragraphs[0].text


def test_unapproved_values_are_not_redacted(tmp_path):
    src, dst = tmp_path / "in.docx", tmp_path / "out.docx"
    doc = Document()
    doc.add_paragraph("Contact morgan@example.invalid")
    doc.save(src)
    # With no approved values, fail closed.
    try:
        redact_docx(src, dst, [finding("morgan@example.invalid", approved=False)])
    except Exception as exc:
        assert "No approved findings" in str(exc)
    else:
        raise AssertionError("Expected no-approved-findings to fail closed")
    assert not dst.exists()


def test_missing_approved_value_fails_without_output(tmp_path):
    src, dst = tmp_path / "in.docx", tmp_path / "out.docx"
    doc = Document()
    doc.add_paragraph("Harmless synthetic text for test purposes.")
    doc.save(src)
    try:
        redact_docx(src, dst, [finding("missing@example.invalid")])
    except Exception as exc:
        assert "not found" in str(exc)
    else:
        raise AssertionError("Expected missing finding to fail closed")
    assert not dst.exists()


def test_source_is_not_modified(tmp_path):
    src, dst = tmp_path / "in.docx", tmp_path / "out.docx"
    doc = Document()
    doc.add_paragraph("Contact morgan@example.invalid")
    doc.save(src)
    before = src.read_bytes()
    redact_docx(src, dst, [finding("morgan@example.invalid")])
    assert src.read_bytes() == before


def test_comments_and_custom_properties_are_removed_if_present(tmp_path):
    src, dst = tmp_path / "in.docx", tmp_path / "out.docx"
    doc = Document()
    doc.add_paragraph("Contact morgan@example.invalid")
    doc.core_properties.author = "FAKE AUTHOR: Morgan Example"
    doc.save(src)

    # Inject a synthetic custom property part and relationship/content type entries
    # only if the library fixture doesn't already include them.
    with ZipFile(src, "a") as z:
        z.writestr("docProps/custom.xml", b'<?xml version="1.0"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties"><property name="fake"><vt:lpwstr xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">FAKE-CUSTOM-PROPERTY</vt:lpwstr></property></Properties>')
    result = redact_docx(src, dst, [finding("morgan@example.invalid")])
    assert result["verified_clean"] is True
    with ZipFile(dst) as z:
        assert "docProps/custom.xml" not in z.namelist()
    reopened = Document(dst)
    assert reopened.core_properties.author in (None, "")
