"""Deterministic, local regex-based detection for structured PII."""
from __future__ import annotations

import re
import hashlib
from dataclasses import dataclass

from app.models import Finding


@dataclass(frozen=True)
class Rule:
    category: str
    pattern: re.Pattern[str]
    reason: str


# Patterns intentionally favor precision. They do not prove that a match is real PII.
RULES: tuple[Rule, ...] = (
    Rule(
        "EMAIL",
        re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])", re.IGNORECASE),
        "Email-like address matched by a deterministic pattern.",
    ),
    Rule(
        "PHONE",
        re.compile(r"(?<!\w)(?:\+?91[\s.-]?)?[6-9]\d{9}(?!\w)|(?<!\w)\+?91[\s.-]?[6-9]\d{4}[\s.-]?\d{5}(?!\w)"),
        "Phone-like number matched by an Indian mobile-number pattern.",
    ),
    Rule(
        "AADHAAR_LIKE_ID",
        re.compile(r"(?<!\d)(?:\d{4}[\s-]?\d{4}[\s-]?\d{4})(?![\s-]?\d)"),
        "Twelve-digit Aadhaar-like identifier. This is a format match, not validation.",
    ),
    Rule(
        "PAN_LIKE_ID",
        re.compile(r"(?<![A-Z0-9])[A-Z]{5}\d{4}[A-Z](?![A-Z0-9])", re.IGNORECASE),
        "PAN-like identifier matched by its expected character pattern.",
    ),
    Rule(
        "IFSC",
        re.compile(r"(?<![A-Z0-9])[A-Z]{4}0[A-Z0-9]{6}(?![A-Z0-9])", re.IGNORECASE),
        "IFSC-like bank code matched by its expected format.",
    ),
    Rule(
        "PIN_CODE",
        re.compile(r"(?<!\d)[1-9]\d{5}(?!\d)"),
        "Six-digit Indian PIN-code-like value; contextual review is required.",
    ),
    Rule(
        "CARD_NUMBER",
        re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)"),
        "13–19 digit card-number-like sequence; not validated with Luhn.",
    ),
    Rule(
        "ACCOUNT_NUMBER",
        re.compile(r"(?i)\b(?:account|a/c|acct)\s*(?:number|no\.?|#)?\s*[:=-]?\s*(\d{8,18})\b"),
        "Bank-account-number-like value following an account label.",
    ),
    Rule(
        "DATE_OF_BIRTH",
        re.compile(r"(?i)\b(?:dob|date of birth|birth date)\s*[:=-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b"),
        "Date-like value following a date-of-birth label.",
    ),
)


def _stable_id(category: str, text: str, start: int, end: int) -> str:
    raw = f"{category}|{start}|{end}|{text}".encode("utf-8")
    return "regex-" + hashlib.sha256(raw).hexdigest()[:12]


def detect(text: str, *, location: str | None = None) -> list[Finding]:
    """Return structured PII candidates from text.

    `text` is never changed. `location` can carry a page/paragraph/line locator
    from the extraction layer. Findings are deduplicated by span/category.
    """
    if not isinstance(text, str):
        raise TypeError("text must be a string")

    findings: list[Finding] = []
    seen: set[tuple[int, int, str]] = set()

    for rule in RULES:
        for match in rule.pattern.finditer(text):
            # For labelled account/DOB patterns, capture the sensitive value only.
            if rule.category in {"ACCOUNT_NUMBER", "DATE_OF_BIRTH"} and match.lastindex:
                start, end = match.span(1)
                value = match.group(1)
            else:
                start, end = match.span()
                value = match.group(0)

            # A 16-digit card number with separators contains overlapping
            # 12-digit windows. Do not label a partial window as Aadhaar-like.
            if rule.category == "AADHAAR_LIKE_ID":
                before = text[:start]
                after = text[end:]
                if re.search(r"\d{4}[\s-]$", before) or re.match(r"[\s-]\d", after):
                    continue

            key = (start, end, rule.category)
            if key in seen:
                continue
            seen.add(key)
            findings.append(
                Finding(
                    id=_stable_id(rule.category, value, start, end),
                    text=value,
                    category=rule.category,
                    source_layer="regex",
                    reason=rule.reason,
                    location=location,
                    approved=True,
                )
            )

    # Stable reading order, then deterministic category ordering for same-start matches.
    findings.sort(key=lambda item: (text.find(item.text), item.category, item.id))
    return findings
