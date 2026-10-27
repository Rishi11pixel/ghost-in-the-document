"""Simple local CLI: inspect findings, approve selected IDs, and redact."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.pipeline import AnalysisError, analyze_file, redact_analyzed_file, write_report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Local PII scan and redaction for TXT and text-based PDF files."
    )
    parser.add_argument("input", help="Input .txt or text-based .pdf file")
    parser.add_argument("--output", help="Redacted output path")
    parser.add_argument("--report", help="JSON report path (default: <input>.report.json)")
    parser.add_argument(
        "--scan-only", action="store_true",
        help="Only scan and write a report; do not redact."
    )
    args = parser.parse_args()

    source = Path(args.input)
    try:
        report = analyze_file(source)
        print(f"\nFile: {report.filename}")
        print(f"Candidate findings: {len(report.findings)}")
        if not report.findings:
            print("No regex candidates found. This is not proof the file contains no sensitive data.")

        for index, finding in enumerate(report.findings, start=1):
            print(
                f"{index}. [{finding.category}] {finding.text!r} "
                f"({finding.location or 'location unknown'})"
            )

        report_path = Path(args.report) if args.report else source.with_name(source.name + ".report.json")
        write_report(report, report_path)
        print(f"\nScan report saved: {report_path}")

        if args.scan_only:
            print("Scan-only mode: no redacted output was written.")
            return 0
        if not report.findings:
            print("No findings to approve; no redacted output was written.")
            return 0

        approved_ids: set[str] = set()
        print("\nReview each candidate. Enter y to approve redaction, anything else to skip.")
        for finding in report.findings:
            answer = input(f"Redact {finding.category} {finding.text!r}? [y/N]: ").strip().lower()
            if answer == "y":
                approved_ids.add(finding.id)

        if not approved_ids:
            print("No candidates approved; no redacted output was written.")
            return 0

        default_output = source.with_name(source.stem + ".redacted" + source.suffix)
        destination = Path(args.output) if args.output else default_output
        final_report = redact_analyzed_file(source, destination, report, approved_ids)
        write_report(final_report, destination.with_name(destination.name + ".report.json"))
        print(f"\nRedacted copy: {destination}")
        print(f"Post-save verification: {'PASSED' if final_report.verified_clean else 'FAILED'}")
        return 0 if final_report.verified_clean else 2
    except (AnalysisError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
