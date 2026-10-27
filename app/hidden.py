"""Read-only scanner for hidden document data.

This module reports potential hidden-data findings; it never changes input files.
DOCX scanning reads the OOXML package directly to detect structures that
python-docx does not expose consistently.
"""
from __future__ import annotations

import hashlib
import re
import zipfile
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as ET

import fitz

from app.models import Finding

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"w": W_NS, "rel": PKG_REL_NS}

# Use stable IDs based on category/location/text so repeated runs are reproducible.
def _finding(text: str, category: str, location: str, reason: str) -> Finding:
    key = f"{category}|{location}|{text}".encode("utf-8", errors="replace")
    stable_id = hashlib.sha256(key).hexdigest()[:12]
    return Finding(
        id=f"hidden-{stable_id}",
        text=text,
        category=category,
        source_layer="hidden_scan",
        reason=reason,
        location=location,
        approved=True,
    )


def _nonempty_metadata(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "null"}:
        return None
    return text


def scan_pdf(path: str | Path) -> list[Finding]:
    """Scan PDF metadata, annotations and embedded-file names/content markers."""
    source = Path(path)
    findings: list[Finding] = []

    with fitz.open(source) as pdf:
        metadata = pdf.metadata or {}
        for key in (
            "author", "creator", "producer", "title", "subject",
            "keywords", "creationDate", "modDate",
        ):
            value = _nonempty_metadata(metadata.get(key))
            if value:
                findings.append(
                    _finding(
                        value,
                        "METADATA",
                        f"PDF metadata: {key}",
                        f"Non-empty PDF metadata field {key!r} may identify a person or reveal document history.",
                    )
                )

        for page_number, page in enumerate(pdf, start=1):
            try:
                annotations = page.annots()
                if annotations:
                    for annotation_index, annotation in enumerate(annotations, start=1):
                        info = annotation.info or {}
                        parts = []
                        for key in ("title", "subject", "content", "name"):
                            value = _nonempty_metadata(info.get(key))
                            if value:
                                parts.append(f"{key}={value}")
                        description = "; ".join(parts) or str(annotation.type)
                        findings.append(
                            _finding(
                                description,
                                "COMMENT",
                                f"PDF page {page_number}, annotation {annotation_index}",
                                "PDF annotation may contain reviewer comments or other information not obvious in the page text.",
                            )
                        )
            except Exception as exc:
                # Fail closed for this scan: don't silently claim the PDF had no annotations.
                raise RuntimeError(
                    f"Could not inspect annotations on PDF page {page_number}: {exc}"
                ) from exc

        try:
            embedded = pdf.embfile_names()
        except Exception as exc:
            raise RuntimeError(f"Could not inspect PDF embedded files: {exc}") from exc

        for index, embedded_name in enumerate(embedded, start=1):
            findings.append(
                _finding(
                    embedded_name,
                    "EMBEDDED_FILE",
                    f"PDF embedded file {index}",
                    "PDF contains an embedded file; its contents may disclose information outside the visible pages.",
                )
            )

    return findings


def _xml_text(element: ET.Element) -> str:
    """Collect text nodes in document order, including text inside tracked changes."""
    return "".join(element.itertext()).strip()


def _find_text_nodes(root: ET.Element, xpath: str) -> list[str]:
    # ElementTree's limited XPath supports the paths used here.
    result = []
    for element in root.findall(xpath, NS):
        value = _xml_text(element)
        if value:
            result.append(value)
    return result


def scan_docx(path: str | Path) -> list[Finding]:
    """Scan DOCX properties, comments, tracked changes and hidden text."""
    source = Path(path)
    findings: list[Finding] = []

    try:
        archive = zipfile.ZipFile(source, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError(f"Invalid DOCX package: {source.name}") from exc

    with archive:
        names = set(archive.namelist())

        # Inspect only properties that can plausibly identify a person or reveal
        # meaningful document context. Generic counters/booleans in docProps/app.xml
        # are not privacy findings and create noisy false positives.
        metadata_fields = {
            "docProps/core.xml": {
                "creator", "lastModifiedBy", "title", "subject", "description",
                "keywords", "category", "identifier", "language", "version",
            },
            "docProps/app.xml": {"Company", "Manager"},
            "docProps/custom.xml": None,  # custom properties are user-defined
        }
        for part_name, allowed_fields in metadata_fields.items():
            if part_name not in names:
                continue
            try:
                root = ET.fromstring(archive.read(part_name))
            except ET.ParseError as exc:
                raise ValueError(f"Malformed XML in {part_name}") from exc

            for element in root.iter():
                value = _xml_text(element)
                if not value or len(list(element)) != 0:
                    continue
                local_name = element.tag.rsplit("}", 1)[-1]
                if allowed_fields is not None and local_name not in allowed_fields:
                    continue
                findings.append(
                    _finding(
                        value,
                        "METADATA",
                        f"DOCX {part_name}: {local_name}",
                        "DOCX package property may identify an author, editor, organization, or reveal document context.",
                    )
                )

        # Comments: report comment body and author separately when present.
        if "word/comments.xml" in names:
            try:
                root = ET.fromstring(archive.read("word/comments.xml"))
            except ET.ParseError as exc:
                raise ValueError("Malformed XML in word/comments.xml") from exc
            for index, comment in enumerate(root.findall(".//w:comment", NS), start=1):
                author = comment.attrib.get(f"{{{W_NS}}}author", "").strip()
                comment_text = _xml_text(comment)
                if author:
                    findings.append(
                        _finding(
                            author,
                            "COMMENT",
                            f"DOCX comment {index}: author",
                            "Comment author metadata can identify a reviewer.",
                        )
                    )
                if comment_text:
                    findings.append(
                        _finding(
                            comment_text,
                            "COMMENT",
                            f"DOCX comment {index}: text",
                            "Reviewer comment text may contain deleted or confidential context.",
                        )
                    )

        # Inspect WordprocessingML story parts: main document, headers, footers,
        # footnotes and endnotes. Avoid scanning comments.xml twice here.
        story_parts = [
            name for name in names
            if name == "word/document.xml"
            or re.fullmatch(r"word/(header|footer)\d+\.xml", name)
            or name in {"word/footnotes.xml", "word/endnotes.xml"}
        ]

        for part_name in sorted(story_parts):
            try:
                root = ET.fromstring(archive.read(part_name))
            except ET.ParseError as exc:
                raise ValueError(f"Malformed XML in {part_name}") from exc

            # Tracked insertions and deletions: include text even if not in the
            # ordinary paragraph view.
            for change_tag, category in (("ins", "TRACKED_CHANGE"), ("del", "TRACKED_CHANGE")):
                for index, element in enumerate(root.findall(f".//w:{change_tag}", NS), start=1):
                    value = _xml_text(element)
                    if value:
                        findings.append(
                            _finding(
                                value,
                                category,
                                f"DOCX {part_name}: {change_tag} {index}",
                                "Tracked insertion/deletion preserves revision history that may not be apparent in the accepted view.",
                            )
                        )

            # Hidden text: Word uses w:vanish and sometimes w:webHidden.
            for tag in ("vanish", "webHidden"):
                for index, marker in enumerate(root.findall(f".//w:{tag}", NS), start=1):
                    run = marker
                    while run is not None and run.tag != f"{{{W_NS}}}r":
                        # ElementTree has no parent pointers; this branch cannot
                        # ascend. The run text is gathered below by scanning runs.
                        break
                    # Find the containing run by checking each run's descendants.
                    for run_index, candidate in enumerate(root.findall(".//w:r", NS), start=1):
                        if marker in list(candidate.iter()):
                            value = _xml_text(candidate)
                            if value:
                                findings.append(
                                    _finding(
                                        value,
                                        "HIDDEN_TEXT",
                                        f"DOCX {part_name}: {tag} run {run_index}",
                                        "Text marked hidden by Word formatting may remain in the document package.",
                                    )
                                )
                            break

    return _dedupe(findings)


def _dedupe(findings: Iterable[Finding]) -> list[Finding]:
    seen: set[tuple[str, str, str]] = set()
    result: list[Finding] = []
    for finding in findings:
        key = (finding.category, finding.location or "", finding.text)
        if key not in seen:
            seen.add(key)
            result.append(finding)
    return result


def scan_hidden(path: str | Path) -> list[Finding]:
    """Dispatch hidden-data scanning by supported file extension."""
    source = Path(path)
    suffix = source.suffix.lower()
    if not source.is_file():
        raise FileNotFoundError(f"Input file does not exist: {source}")
    if suffix == ".pdf":
        return scan_pdf(source)
    if suffix == ".docx":
        return scan_docx(source)
    if suffix == ".txt":
        return []
    raise ValueError(f"Unsupported file extension {suffix!r}")
