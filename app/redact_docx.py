"""Conservative DOCX redaction using OOXML editing and post-save verification.

This is a best-effort sanitizer, not a forensic guarantee. It removes comments,
tracked-change markup, common document properties, custom properties, and hidden
text runs. It preserves paragraph properties but may simplify run-level formatting
inside a paragraph where redaction occurs.
"""
from __future__ import annotations

from pathlib import Path
from collections.abc import Iterable
from zipfile import ZIP_DEFLATED, ZipFile
import os
import tempfile
import xml.etree.ElementTree as ET

from app.models import Finding
from app.redact import RedactionError

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
CT_NS = "{http://schemas.openxmlformats.org/package/2006/content-types}"
XML_NS = "{http://www.w3.org/XML/1998/namespace}"

ET.register_namespace("w", W[1:-1])
ET.register_namespace("r", "http://schemas.openxmlformats.org/officeDocument/2006/relationships")
ET.register_namespace("rel", R_NS[1:-1])
ET.register_namespace("", CT_NS[1:-1])


def _approved_values(findings: Iterable[Finding]) -> list[str]:
    return list(dict.fromkeys(f.text for f in findings if f.approved and f.text))


def _xml_bytes(root: ET.Element) -> bytes:
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _paragraph_text(paragraph: ET.Element) -> str:
    return "".join(node.text or "" for node in paragraph.iter(W + "t"))


def _remove_hidden_runs(root: ET.Element) -> int:
    removed = 0
    for run in list(root.iter(W + "r")):
        properties = run.find(W + "rPr")
        if properties is None:
            continue
        hidden = properties.find(W + "vanish") is not None or properties.find(W + "webHidden") is not None
        if hidden:
            # Remove this run from its parent.
            for parent in root.iter():
                if run in list(parent):
                    parent.remove(run)
                    removed += 1
                    break
    return removed


def _remove_tracked_changes(root: ET.Element) -> int:
    count = 0
    for tag in (W + "ins", W + "del", W + "moveFrom", W + "moveTo"):
        for node in list(root.iter(tag)):
            for parent in root.iter():
                if node in list(parent):
                    parent.remove(node)
                    count += 1
                    break
    # Remove comment range/reference markers; comments.xml is removed separately.
    for tag in (W + "commentRangeStart", W + "commentRangeEnd", W + "commentReference"):
        for node in list(root.iter(tag)):
            for parent in root.iter():
                if node in list(parent):
                    parent.remove(node)
                    count += 1
                    break
    return count


def _replace_paragraph(paragraph: ET.Element, values: list[str]) -> tuple[bool, int]:
    original = _paragraph_text(paragraph)
    updated = original
    occurrences = 0
    for value in sorted(values, key=len, reverse=True):
        count = updated.count(value)
        if count:
            updated = updated.replace(value, "[REDACTED]")
            occurrences += count
    if updated == original:
        return False, 0

    # Keep paragraph properties; rebuild text runs to prevent the original string
    # from remaining split across XML text nodes.
    for child in list(paragraph):
        if child.tag != W + "pPr":
            paragraph.remove(child)
    run = ET.SubElement(paragraph, W + "r")
    text = ET.SubElement(run, W + "t")
    if updated[:1].isspace() or updated[-1:].isspace():
        text.set("{" + XML_NS + "}space", "preserve")
    text.text = updated
    return True, occurrences


def redact_docx(source: str | Path, destination: str | Path,
                findings: Iterable[Finding]) -> dict:
    """Redact approved strings and strip common hidden DOCX content."""
    src, dst = Path(source), Path(destination)
    if src.resolve() == dst.resolve():
        raise RedactionError("Input and output paths must be different.")
    if src.suffix.lower() != ".docx" or dst.suffix.lower() != ".docx":
        raise RedactionError("redact_docx only supports .docx input and output.")
    findings = list(findings)
    values = _approved_values(findings)
    if not values:
        raise RedactionError("No approved findings supplied; no output written.")

    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(suffix=".docx", dir=str(dst.parent))
    os.close(fd)
    temp_path = Path(temp_name)
    occurrence_count = 0
    found_values: set[str] = set()
    try:
        with ZipFile(src, "r") as zin:
            names = zin.namelist()
            xml_parts: dict[str, bytes] = {}
            for name in names:
                if not name.endswith(".xml") or name in {
                    "word/comments.xml", "docProps/custom.xml"
                }:
                    continue
                try:
                    root = ET.fromstring(zin.read(name))
                except ET.ParseError:
                    # If an XML part cannot be parsed, fail closed instead of copying it.
                    raise RedactionError(f"Could not safely inspect DOCX XML part: {name}")

                # Sanitize document text-bearing parts (main document, headers, footers,
                # footnotes, endnotes and similar WordprocessingML parts).
                if name.startswith("word/"):
                    for paragraph in root.iter(W + "p"):
                        paragraph_text = _paragraph_text(paragraph)
                        for value in values:
                            if value in paragraph_text:
                                found_values.add(value)
                        changed, count = _replace_paragraph(paragraph, values)
                        occurrence_count += count
                    _remove_hidden_runs(root)
                    _remove_tracked_changes(root)

                # Clear common personal properties from docProps/core.xml.
                if name == "docProps/core.xml":
                    for child in list(root):
                        local = child.tag.rsplit("}", 1)[-1]
                        if local in {
                            "creator", "lastModifiedBy", "title", "subject", "keywords",
                            "description", "category", "identifier", "language",
                            "version", "revision",
                        }:
                            child.text = None
                            child.attrib.clear()

                xml_parts[name] = _xml_bytes(root)

            missing = [f.text for f in findings if f.approved and f.text and f.category not in {"METADATA", "COMMENT", "EMBEDDED_FILE", "HIDDEN_TEXT", "TRACKED_CHANGE", "HIDDEN_CONTENT"} and f.text not in found_values]
            if missing:
                raise RedactionError(
                    "Refusing to write DOCX: approved finding(s) were not found in "
                    "Word text. Some matches split across paragraphs/runs may require "
                    "review; no output was retained."
                )

            with ZipFile(temp_path, "w", ZIP_DEFLATED) as zout:
                for info in zin.infolist():
                    name = info.filename
                    if name in {"word/comments.xml", "docProps/custom.xml"}:
                        continue
                    # Drop comments relationships and content-type declaration.
                    if name == "word/_rels/document.xml.rels":
                        root = ET.fromstring(xml_parts.get(name, zin.read(name)))
                        for rel in list(root):
                            if "comments" in (rel.attrib.get("Type", "").lower()):
                                root.remove(rel)
                        data = _xml_bytes(root)
                    elif name == "[Content_Types].xml":
                        root = ET.fromstring(xml_parts.get(name, zin.read(name)))
                        for child in list(root):
                            if "comments" in child.attrib.get("PartName", "").lower() or "custom.xml" in child.attrib.get("PartName", "").lower():
                                root.remove(child)
                        data = _xml_bytes(root)
                    else:
                        data = xml_parts.get(name, zin.read(name))
                    zout.writestr(info, data)

        # Reopen the generated archive and scan all remaining XML for approved values.
        with ZipFile(temp_path, "r") as check:
            leftovers: list[str] = []
            for name in check.namelist():
                if name.endswith(".xml"):
                    raw = check.read(name)
                    try:
                        root = ET.fromstring(raw)
                        serialized_text = " ".join((node.text or "") for node in root.iter())
                    except ET.ParseError:
                        leftovers.append(f"unreadable XML part: {name}")
                        continue
                    for value in values:
                        if value in serialized_text and value not in leftovers:
                            leftovers.append(value)
            if "word/comments.xml" in check.namelist():
                leftovers.append("comments.xml")
            if "docProps/custom.xml" in check.namelist():
                leftovers.append("custom.xml")

        if leftovers:
            raise RedactionError(
                "Post-save DOCX verification found leftover content; output was not retained."
            )
        os.replace(temp_path, dst)
        return {
            "output_path": str(dst),
            "verified_clean": True,
            "redacted_occurrences": occurrence_count,
            "leftovers": [],
            "removed_comments": True,
            "removed_tracked_changes": True,
            "removed_hidden_text_runs": True,
        }
    except RedactionError:
        raise
    except Exception as exc:
        raise RedactionError(f"DOCX redaction failed; no output retained: {exc}") from exc
    finally:
        temp_path.unlink(missing_ok=True)
