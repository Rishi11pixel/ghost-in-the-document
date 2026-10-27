"""Fail-closed local redaction for TXT, text-based PDF and DOCX."""
from __future__ import annotations

from pathlib import Path
from collections.abc import Iterable
import fitz

from app.models import Finding


class RedactionError(RuntimeError):
    """Raised when requested redaction cannot be completed safely."""


HIDDEN_CATEGORIES = {
    "METADATA", "COMMENT", "EMBEDDED_FILE", "HIDDEN_TEXT",
    "TRACKED_CHANGE", "HIDDEN_CONTENT",
}


def _approved(findings: Iterable[Finding]) -> list[Finding]:
    return [f for f in findings if f.approved and f.text]


def _approved_texts(findings: Iterable[Finding]) -> list[str]:
    return list(dict.fromkeys(f.text for f in _approved(findings)))


def redact_txt(source: str | Path, destination: str | Path,
               findings: Iterable[Finding]) -> dict:
    src, dst = Path(source), Path(destination)
    if src.resolve() == dst.resolve():
        raise RedactionError("Input and output paths must be different.")
    if src.suffix.lower() != ".txt" or dst.suffix.lower() != ".txt":
        raise RedactionError("redact_txt only supports .txt input and output.")
    values = _approved_texts(findings)
    original = src.read_text(encoding="utf-8-sig")
    missing = [v for v in values if v not in original]
    if missing:
        raise RedactionError(f"Refusing to write output: {len(missing)} approved finding(s) were not found in the source text.")
    result, count = original, 0
    for value in sorted(values, key=len, reverse=True):
        count += result.count(value)
        result = result.replace(value, "[REDACTED]")
    if any(v in result for v in values):
        raise RedactionError("Verification failed; no output written.")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(result, encoding="utf-8", newline="")
    saved = dst.read_text(encoding="utf-8")
    leftovers = [v for v in values if v in saved]
    if leftovers:
        dst.unlink(missing_ok=True)
        raise RedactionError("Saved output failed verification and was removed.")
    return {"output_path": str(dst), "verified_clean": True, "redacted_occurrences": count, "leftovers": []}


def redact_pdf(source: str | Path, destination: str | Path,
               findings: Iterable[Finding]) -> dict:
    src, dst = Path(source), Path(destination)
    if src.resolve() == dst.resolve():
        raise RedactionError("Input and output paths must be different.")
    if src.suffix.lower() != ".pdf" or dst.suffix.lower() != ".pdf":
        raise RedactionError("redact_pdf only supports .pdf input and output.")
    approved = _approved(findings)
    values = list(dict.fromkeys(f.text for f in approved))
    visible_values = list(dict.fromkeys(
        f.text for f in approved if f.category not in HIDDEN_CATEGORIES
    ))
    try:
        document = fitz.open(src)
    except Exception as exc:
        raise RedactionError(f"Could not open PDF: {exc}") from exc
    try:
        if document.is_encrypted or document.needs_pass:
            raise RedactionError("Encrypted PDFs are not supported.")
        locations: dict[str, list[tuple[int, fitz.Rect]]] = {}
        for value in visible_values:
            matches = []
            for page_index, page in enumerate(document):
                matches.extend((page_index, rect) for rect in page.search_for(value, quads=False))
            if not matches:
                raise RedactionError(f"Refusing to write output: approved visible finding could not be located in PDF text: {value!r}")
            locations[value] = matches
        for matches in locations.values():
            for page_index, rect in matches:
                document[page_index].add_redact_annot(
                    rect, text="[REDACTED]", fill=(0, 0, 0), text_color=(1, 1, 1)
                )
        for page in document:
            page.apply_redactions()
        # Remove common metadata and every annotation/embedded attachment.
        document.set_metadata({})
        for page in document:
            for annot in list(page.annots() or []):
                page.delete_annot(annot)
        try:
            for name in list(document.embfile_names()):
                document.embfile_del(name)
        except Exception as exc:
            raise RedactionError(f"Could not remove PDF embedded files: {exc}") from exc
        dst.parent.mkdir(parents=True, exist_ok=True)
        document.save(dst, garbage=4, deflate=True, clean=True)
    except RedactionError:
        dst.unlink(missing_ok=True)
        raise
    except Exception as exc:
        dst.unlink(missing_ok=True)
        raise RedactionError(f"PDF redaction failed; output was not retained: {exc}") from exc
    finally:
        document.close()
    try:
        with fitz.open(dst) as check:
            extracted = "\n".join(page.get_text("text") for page in check)
            visible_leftovers = [v for v in visible_values if v in extracted]
            metadata = check.metadata or {}
            nonempty_metadata = {
                k: v for k, v in metadata.items()
                if k not in {"format", "encryption"} and v
            }
            annotations_left = any(list(page.annots() or []) for page in check)
            embedded_left = bool(check.embfile_names())
    except Exception as exc:
        dst.unlink(missing_ok=True)
        raise RedactionError(f"Could not verify saved PDF; output was removed: {exc}") from exc
    if visible_leftovers or nonempty_metadata or annotations_left or embedded_left:
        dst.unlink(missing_ok=True)
        raise RedactionError("Post-save PDF verification found residual text, metadata, annotations, or embedded files; output was removed.")
    return {
        "output_path": str(dst), "verified_clean": True,
        "redacted_occurrences": sum(len(x) for x in locations.values()),
        "leftovers": [],
    }


def redact_file(source: str | Path, destination: str | Path,
                findings: Iterable[Finding]) -> dict:
    suffix = Path(source).suffix.lower()
    if suffix == ".txt":
        return redact_txt(source, destination, findings)
    if suffix == ".pdf":
        return redact_pdf(source, destination, findings)
    if suffix == ".docx":
        from app.redact_docx import redact_docx
        return redact_docx(source, destination, findings)
    raise RedactionError(f"Unsupported file type: {suffix or '(no extension)'}")
