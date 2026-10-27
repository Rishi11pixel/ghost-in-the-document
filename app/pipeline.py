"""Unified analysis, review and redaction pipeline."""
from __future__ import annotations

import json
from pathlib import Path

from app.detect_rules import detect
from app.detect_ai import detect_ai
from app.extract import extract_document
from app.hidden import scan_hidden
from app.merge import merge_findings
from app.models import Finding, Report
from app.redact import RedactionError, redact_file


class AnalysisError(RuntimeError):
    """Raised when a file cannot be inspected or sanitized safely."""


def analyze_file(source: str | Path, *, use_ai: bool = False) -> Report:
    path = Path(source)
    if not path.is_file():
        raise AnalysisError(f"Input file does not exist: {path}")
    try:
        extracted = extract_document(path)
        visible: list[Finding] = []
        warnings: list[str] = []
        for segment in extracted.segments:
            visible.extend(detect(segment.text, location=segment.location))
        if use_ai and extracted.text.strip():
            # Join extracted segments so a local model is called once per ~1,200
            # characters rather than once per paragraph/line. Map exact spans back
            # to a source segment whenever possible.
            for offset in range(0, len(extracted.text), 1200):
                chunk = extracted.text[offset:offset + 1200]
                chunk_location = f"document text chunk {offset // 1200 + 1}"
                ai_findings, ai_warnings = detect_ai(chunk, location=chunk_location)
                for finding in ai_findings:
                    original_segment = next(
                        (segment for segment in extracted.segments if finding.text in segment.text),
                        None,
                    )
                    if original_segment is not None:
                        finding = finding.model_copy(update={"location": original_segment.location}, deep=True)
                    visible.append(finding)
                warnings.extend(ai_warnings)
        hidden = scan_hidden(path)
        findings = merge_findings(visible, hidden)
    except Exception as exc:
        if isinstance(exc, AnalysisError):
            raise
        raise AnalysisError(str(exc)) from exc
    return Report(filename=path.name, findings=findings, verified_clean=False, leftovers=[], warnings=list(dict.fromkeys(warnings)))


def redact_analyzed_file(source: str | Path, destination: str | Path,
                         report: Report, approved_ids: set[str]) -> Report:
    if not approved_ids:
        raise AnalysisError("No findings were approved; no redacted output was written.")
    approved_findings = [
        finding.model_copy(update={"approved": finding.id in approved_ids}, deep=True)
        for finding in report.findings
    ]
    chosen = [f for f in approved_findings if f.approved]
    try:
        result = redact_file(source, destination, chosen)
    except RedactionError as exc:
        raise AnalysisError(str(exc)) from exc
    return Report(
        filename=Path(destination).name,
        findings=approved_findings,
        verified_clean=bool(result.get("verified_clean")),
        leftovers=result.get("leftovers", []),
        warnings=report.warnings,
    )


def write_report(report: Report, destination: str | Path) -> Path:
    output = Path(destination)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False), encoding="utf-8")
    return output
