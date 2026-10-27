"""Evaluate detectors against per-file synthetic ground truth; no real data required."""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from collections import Counter
from pathlib import Path

from app.pipeline import analyze_file

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
GROUND_TRUTH = ROOT / "tests" / "ground_truth" / "evaluation_cases.json"


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-ai", action="store_true", help="Use configured local GLiNER and Ollama models. May be slower.")
    parser.add_argument("--model", help="Local Ollama model tag, e.g. qwen2.5:3b or llama3.2:3b.")
    args = parser.parse_args(argv)
    if args.model:
        os.environ["GHOST_OLLAMA_MODEL"] = args.model

    truth = json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))
    if truth.get("synthetic_data_only") is not True:
        raise SystemExit("Refusing to evaluate: ground truth is not marked synthetic-only.")
    expected_cases: dict[str, set[str]] = {
        filename: set(values) for filename, values in truth["cases"].items()
    }
    actual_pairs: set[tuple[str, str]] = set()
    expected_pairs = {(filename, value) for filename, values in expected_cases.items() for value in values}
    per_file: dict[str, dict] = {}
    layer_counts: Counter[str] = Counter()
    warnings: list[str] = []

    for filename, expected in expected_cases.items():
        path = FIXTURES / filename
        if not path.is_file():
            per_file[filename] = {"error": "Fixture file is missing."}
            continue
        started = time.perf_counter()
        try:
            report = analyze_file(path, use_ai=args.with_ai)
            elapsed = time.perf_counter() - started
            actual = {finding.text for finding in report.findings}
            actual_pairs.update((filename, value) for value in actual)
            for finding in report.findings:
                layer_counts.update(finding.source_layer.split("+"))
            warnings.extend(report.warnings)
            per_file[filename] = {
                "elapsed_seconds": round(elapsed, 3),
                "expected_items": len(expected),
                "detected_findings": len(report.findings),
                "matched_expected": sorted(expected & actual),
                "missed_expected": sorted(expected - actual),
                "unexpected_findings": sorted(actual - expected),
                "warnings": report.warnings,
            }
        except Exception as exc:
            per_file[filename] = {"error": f"{type(exc).__name__}: {exc}"}

    tp = len(expected_pairs & actual_pairs)
    fp = len(actual_pairs - expected_pairs)
    fn = len(expected_pairs - actual_pairs)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    result = {
        "synthetic_data_only": True,
        "ai_enabled": args.with_ai,
        "ai_models": {
            "gliner_model_path_configured": bool(os.environ.get("GHOST_GLINER_MODEL_PATH")),
            "ollama_model": os.environ.get("GHOST_OLLAMA_MODEL", "qwen2.5:3b"),
        },
        "method": "Exact (filename, text) span-set comparison against per-file ground truth; not offset-aware.",
        "files_in_ground_truth": len(expected_cases),
        "files_evaluated": sum(1 for name, value in per_file.items() if "error" not in value),
        "expected_items": len(expected_pairs),
        "true_positive_items": tp,
        "false_positive_items": fp,
        "missed_expected_items": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0,
        "mean_seconds_per_file": round(
            sum(v.get("elapsed_seconds", 0.0) for v in per_file.values()) /
            max(1, sum(1 for v in per_file.values() if "error" not in v)), 3
        ),
        "findings_by_source_layer": dict(sorted(layer_counts.items())),
        "warnings": list(dict.fromkeys(warnings)),
        "per_file": per_file,
        "limitations": [
            "This is a small synthetic benchmark, not a real-world privacy guarantee.",
            "Exact text matching is not location-aware and may count semantically equivalent spans as misses.",
            "When --with-ai is used, results depend on the locally configured model versions and settings.",
        ],
    }
    model_slug = re.sub(r"[^A-Za-z0-9_-]+", "_", os.environ.get("GHOST_OLLAMA_MODEL", "qwen2.5:3b"))
    output = ROOT / (f"evaluation-results-ai-{model_slug}.json" if args.with_ai else "evaluation-results.json")
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"\nSaved: {output}")


if __name__ == "__main__":
    main()
