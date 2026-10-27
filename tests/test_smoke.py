from app.models import Finding, Report
from app.extract import supported_extension


def test_supported_extensions_are_case_insensitive():
    assert supported_extension("sample.txt")
    assert supported_extension("sample.PDF")
    assert supported_extension("sample.docx")
    assert not supported_extension("sample.png")


def test_finding_schema_contract():
    finding = Finding(
        id="fake-001",
        text="FAKE-PHONE-0001",
        category="PHONE",
        source_layer="regex",
        reason="Synthetic fixture marker",
        location="paragraph 1",
        approved=True,
    )
    assert finding.category == "PHONE"
    assert finding.approved is True


def test_report_schema_contract():
    report = Report(
        filename="synthetic.txt",
        findings=[],
        verified_clean=False,
        leftovers=[],
    )
    assert report.filename == "synthetic.txt"
    assert report.verified_clean is False
