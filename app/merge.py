"""Conservative deduplication of detector findings."""
from __future__ import annotations
import hashlib
from collections.abc import Iterable
from app.models import Finding


def _key(f: Finding) -> tuple[str, str, str | None]:
    # No offsets exist in the current schema, so location is part of identity.
    return (f.text, f.category, f.location)


def merge_findings(*groups: Iterable[Finding]) -> list[Finding]:
    """Merge exact duplicates while preserving sources, reasons, and occurrences."""
    merged: dict[tuple[str, str, str | None], Finding] = {}
    for group in groups:
        for finding in group:
            key = _key(finding)
            old = merged.get(key)
            if old is None:
                merged[key] = finding.model_copy(deep=True)
                continue
            layers = sorted(set(old.source_layer.split("+") + finding.source_layer.split("+")))
            reasons = list(dict.fromkeys(r for r in (old.reason, finding.reason) if r))
            digest = hashlib.sha256("|".join((key[0], key[1], key[2] or "")).encode()).hexdigest()[:12]
            merged[key] = old.model_copy(update={
                "id": f"merge-{digest}",
                "source_layer": "+".join(layers),
                "reason": " | ".join(reasons) if reasons else None,
                "approved": old.approved and finding.approved,
            }, deep=True)
    return sorted(merged.values(), key=lambda f: (f.location or "", f.text.casefold(), f.category, f.id))
