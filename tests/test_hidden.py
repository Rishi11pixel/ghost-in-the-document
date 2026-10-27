from pathlib import Path
import zipfile
from xml.etree import ElementTree as ET

import fitz
import pytest
from docx import Document

from app.hidden import scan_hidden, scan_pdf, scan_docx

FIXTURES = Path(__file__).parent / "fixtures"
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def test_txt_has_no_hidden_layer():
    assert scan_hidden(FIXTURES / "synthetic_case.txt") == []


def test_pdf_metadata_is_reported():
    findings = scan_pdf(FIXTURES / "synthetic_case.pdf")
    assert any(f.category == "METADATA" and "Morgan Example" in f.text for f in findings)
    assert all(f.source_layer == "hidden_scan" for f in findings)


def test_docx_core_properties_and_footer_are_reported():
    findings = scan_docx(FIXTURES / "synthetic_case.docx")
    assert any(f.category == "METADATA" and "Morgan Example" in f.text for f in findings)
    assert any(f.category == "METADATA" and "Taylor Sample" in f.text for f in findings)


def _make_docx_with_revision_comment_and_hidden_text(path: Path):
    doc = Document()
    doc.add_paragraph("Visible synthetic sentence.")
    doc.save(path)

    # Inject synthetic OOXML structures for edge-case scanner tests.
    temp = path.with_suffix(".tmp.docx")
    with zipfile.ZipFile(path, "r") as source, zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename == "word/document.xml":
                root = ET.fromstring(data)
                body = root.find(f".//{{{W_NS}}}body")
                ins = ET.SubElement(body, f"{{{W_NS}}}ins")
                run = ET.SubElement(ins, f"{{{W_NS}}}r")
                text = ET.SubElement(run, f"{{{W_NS}}}t")
                text.text = "FAKE-TRACKED-INSERT"
                deletion = ET.SubElement(body, f"{{{W_NS}}}del")
                run2 = ET.SubElement(deletion, f"{{{W_NS}}}r")
                deltext = ET.SubElement(run2, f"{{{W_NS}}}delText")
                deltext.text = "FAKE-TRACKED-DELETE"
                hidden_run = ET.SubElement(body, f"{{{W_NS}}}r")
                props = ET.SubElement(hidden_run, f"{{{W_NS}}}rPr")
                ET.SubElement(props, f"{{{W_NS}}}vanish")
                hidden_text = ET.SubElement(hidden_run, f"{{{W_NS}}}t")
                hidden_text.text = "FAKE-HIDDEN-TEXT"
                data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            elif item.filename == "word/_rels/document.xml.rels":
                # Add comments relationship.
                root = ET.fromstring(data)
                rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
                rel = ET.SubElement(root, f"{{{rel_ns}}}Relationship")
                rel.set("Id", "rIdGhostTest")
                rel.set("Type", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments")
                rel.set("Target", "comments.xml")
                data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            target.writestr(item, data)
        comments_root = ET.Element(f"{{{W_NS}}}comments")
        comment = ET.SubElement(comments_root, f"{{{W_NS}}}comment")
        comment.set(f"{{{W_NS}}}id", "0")
        comment.set(f"{{{W_NS}}}author", "FAKE COMMENT AUTHOR")
        paragraph = ET.SubElement(comment, f"{{{W_NS}}}p")
        run = ET.SubElement(paragraph, f"{{{W_NS}}}r")
        comment_text = ET.SubElement(run, f"{{{W_NS}}}t")
        comment_text.text = "FAKE-COMMENT-BODY"
        target.writestr("word/comments.xml", ET.tostring(comments_root, encoding="utf-8", xml_declaration=True))
    temp.replace(path)


def test_docx_detects_tracked_changes_comments_and_hidden_text(tmp_path):
    path = tmp_path / "edge_cases.docx"
    _make_docx_with_revision_comment_and_hidden_text(path)
    findings = scan_docx(path)
    texts = {f.text for f in findings}
    assert "FAKE-TRACKED-INSERT" in texts
    assert "FAKE-TRACKED-DELETE" in texts
    assert "FAKE-COMMENT-BODY" in texts
    assert "FAKE COMMENT AUTHOR" in texts
    assert "FAKE-HIDDEN-TEXT" in texts


def test_pdf_annotations_are_reported(tmp_path):
    path = tmp_path / "annotated.pdf"
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((72, 72), "Synthetic PDF annotation test content.")
        annotation = page.add_text_annot((72, 100), "FAKE-PDF-COMMENT")
        annotation.set_info(title="FAKE REVIEWER")
        pdf.save(path)
    findings = scan_pdf(path)
    assert any(f.category == "COMMENT" and "FAKE-PDF-COMMENT" in f.text for f in findings)
