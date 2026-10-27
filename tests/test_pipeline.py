from pathlib import Path
import fitz
import pytest
from docx import Document

from app.pipeline import AnalysisError, analyze_file, redact_analyzed_file, write_report


def test_analyze_txt_reports_regex_and_hidden_findings(tmp_path):
    source = tmp_path / "synthetic.txt"
    source.write_text("Synthetic content\nContact morgan.example@example.invalid\n", encoding="utf-8")
    report = analyze_file(source)
    match = next(f for f in report.findings if f.text == "morgan.example@example.invalid")
    assert match.location == "line 2"
    assert report.verified_clean is False


def test_analyze_pdf_detects_visible_and_hidden_metadata(tmp_path):
    source = tmp_path / "synthetic.pdf"
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Synthetic document for local test. morgan@example.invalid")
    doc.set_metadata({"author": "FAKE AUTHOR: Morgan Example"})
    doc.save(source)
    doc.close()
    report = analyze_file(source)
    assert any(f.text == "morgan@example.invalid" for f in report.findings)
    assert any(f.category == "METADATA" and f.text == "FAKE AUTHOR: Morgan Example" for f in report.findings)


def test_analyze_pdf_rejects_low_text_page(tmp_path):
    source = tmp_path / "scanned-like.pdf"
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "short")
    doc.save(source)
    doc.close()
    with pytest.raises(AnalysisError):
        analyze_file(source)


def test_analyze_docx_includes_visible_and_hidden_findings(tmp_path):
    source = tmp_path / "synthetic.docx"
    doc = Document()
    doc.add_paragraph("Contact morgan@example.invalid")
    doc.core_properties.author = "FAKE AUTHOR: Morgan Example"
    doc.save(source)
    report = analyze_file(source)
    assert any(f.text == "morgan@example.invalid" for f in report.findings)
    assert any(f.category == "METADATA" for f in report.findings)


def test_redact_only_approved_txt_findings(tmp_path):
    source, output = tmp_path / "input.txt", tmp_path / "output.txt"
    source.write_text("Contact morgan@example.invalid or help@example.invalid", encoding="utf-8")
    report = analyze_file(source)
    chosen = next(f for f in report.findings if f.text == "morgan@example.invalid")
    final = redact_analyzed_file(source, output, report, {chosen.id})
    assert final.verified_clean
    assert "morgan@example.invalid" not in output.read_text(encoding="utf-8")
    assert "help@example.invalid" in output.read_text(encoding="utf-8")


def test_json_report_does_not_contain_full_source_paragraph(tmp_path):
    source = tmp_path / "input.txt"
    source.write_text("Synthetic content; contact morgan@example.invalid", encoding="utf-8")
    report = analyze_file(source)
    out = write_report(report, tmp_path / "report.json")
    payload = out.read_text(encoding="utf-8")
    assert '"filename": "input.txt"' in payload
    assert "Synthetic content;" not in payload
    assert "morgan@example.invalid" in payload
