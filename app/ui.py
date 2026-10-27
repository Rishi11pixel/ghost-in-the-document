"""Local-only Gradio review interface. Launch with: python -m app.ui"""
from __future__ import annotations

import tempfile
from pathlib import Path

import gradio as gr

from app.models import Report
from app.pipeline import AnalysisError, analyze_file, redact_analyzed_file, write_report

CSS = r"""
:root { --ghost-ink: #111827; --ghost-muted: #667085; --ghost-teal: #00b3a4; }
.gradio-container { max-width: 1180px !important; margin: 0 auto !important; font-family: ui-sans-serif, system-ui, "Segoe UI", sans-serif; }
#ghost-hero { border-radius: 22px; padding: 28px 30px; margin: 8px 0 20px 0;
  color: #f8fafc; background: radial-gradient(circle at 90% 5%, #164e63 0, transparent 36%),
  linear-gradient(125deg, #101827 0%, #172554 58%, #123c4a 100%); border: 1px solid #26364e; }
#ghost-hero h1 { font-size: clamp(30px, 4vw, 42px); line-height: 1.08; margin: 8px 0 10px; letter-spacing: -1.2px; }
#ghost-hero p { color: #dbeafe; max-width: 760px; font-size: 15px; line-height: 1.6; }
.ghost-eyebrow { color: #5eead4; text-transform: uppercase; letter-spacing: 2px; font-size: 11px; font-weight: 800; }
.ghost-pill { display: inline-block; padding: 5px 10px; margin: 4px 5px 0 0; border: 1px solid #426274;
  border-radius: 999px; color: #ccfbf1; font-size: 12px; }
.ghost-panel { border: 1px solid var(--border-color-primary); border-radius: 18px; padding: 18px; }
#ghost-scan button, #ghost-redact button { border-radius: 12px; min-height: 46px; font-weight: 700; }
#ghost-scan button { background: #0f766e !important; }
#ghost-redact button { background: #111827 !important; color: white !important; }
#ghost-status { border-radius: 14px; padding: 12px 16px; background: var(--background-fill-secondary); }
footer { display: none !important; }
"""


def _rows(report: Report, approved: bool = False):
    return [
        [approved, f.id, f.category, f.text, f.source_layer, f.location or "", f.reason or ""]
        for f in report.findings
    ]


def scan_callback(uploaded_path, use_ai=True):
    if not uploaded_path:
        return [], None, "**Choose a file first.** Supported: TXT, text-based PDF, DOCX."
    try:
        report = analyze_file(uploaded_path, use_ai=bool(use_ai))
        status = (
            f"### Scan complete\n\n**{len(report.findings)} candidate finding(s)** in `{Path(uploaded_path).name}`. "
            "Review each row and tick **Approve** only for items you want removed. Nothing has been redacted yet."
        )
        if not report.findings:
            status += "\n\n> No candidates were found. This does **not** prove the document is free of sensitive data."
        if report.warnings:
            warning_lines = "\n".join(f"- {warning}" for warning in report.warnings)
            status += "\n\n**Local AI notes**\n\n" + warning_lines
        elif use_ai:
            status += "\n\n**Local AI assist:** completed without startup warnings. Review its candidates like any others."
        return _rows(report), report.model_dump(mode="json"), status
    except Exception as exc:
        return [], None, f"### Scan refused\n\n`{type(exc).__name__}: {exc}`"


def redact_callback(uploaded_path, rows, report_data):
    if not uploaded_path or not report_data:
        return None, "**Scan a document first.**"
    try:
        report = Report.model_validate(report_data)
        approved_ids = set()
        # Gradio Dataframe may pass a pandas.DataFrame, not a list of rows.
        # Never evaluate a DataFrame's truth value.
        if rows is None:
            row_values = []
        elif hasattr(rows, "to_numpy"):
            row_values = rows.to_numpy().tolist()
        else:
            row_values = rows

        for row in row_values:
            if row is None or len(row) < 2:
                continue
            checked = row[0]
            if isinstance(checked, str):
                checked = checked.strip().lower() in {"true", "1", "yes", "y"}
            else:
                checked = bool(checked) if checked is not None else False
            if checked:
                approved_ids.add(str(row[1]))
        if not approved_ids:
            return None, "**No findings were approved.** No output was written. Tick the Approve column for at least one finding."
        source = Path(uploaded_path)
        output_dir = Path(tempfile.mkdtemp(prefix="ghost_redacted_"))
        output = output_dir / f"{source.stem}.redacted{source.suffix.lower()}"
        final_report = redact_analyzed_file(source, output, report, approved_ids)
        report_path = output_dir / f"{output.name}.report.json"
        write_report(final_report, report_path)
        if final_report.verified_clean:
            status = (
                f"### Redacted copy created\n\n**Post-save checks: PASSED** for the checks implemented by this app. "
                f"Approved finding IDs: {len(approved_ids)}.\n\n"
                "This is not a guarantee that every possible sensitive detail was found or removed. "
                "Keep the JSON report private; it may contain matched text."
            )
        else:
            status = (
                "### Output created, but verification did not pass\n\n"
                "Do not share this file. Review the leftovers in the report and correct them first."
            )
        return str(output), status
    except Exception as exc:
        return None, f"### Redaction refused or failed\n\n`{type(exc).__name__}: {exc}`"


def _theme():
    return gr.themes.Soft(
        primary_hue=gr.themes.colors.teal,
        secondary_hue=gr.themes.colors.slate,
        neutral_hue=gr.themes.colors.slate,
        radius_size="lg",
    )


def build_app():
    with gr.Blocks(title="Ghost in the Document") as demo:
        gr.HTML(
            """<section id="ghost-hero">
              <div class="ghost-eyebrow">LOCAL DOCUMENT PRIVACY LAB</div>
              <h1>Ghost in the Document</h1>
              <p>Find the visible and hidden traces a document leaves behind. Review every candidate, redact only what you approve, then inspect the saved output.</p>
              <span class="ghost-pill">Offline-first</span><span class="ghost-pill">Human review</span><span class="ghost-pill">TXT · PDF · DOCX</span>
            </section>"""
        )
        with gr.Row(equal_height=False):
            with gr.Column(scale=5, elem_classes=["ghost-panel"]):
                gr.Markdown("### 01 · Choose a document\nUse synthetic data while testing. Scanned PDFs and OCR are not supported.")
                uploaded = gr.File(
                    label="Document to inspect", type="filepath", file_count="single",
                    file_types=[".txt", ".pdf", ".docx"],
                )
                use_ai = gr.Checkbox(
                    value=True,
                    label="Use local AI assist (GLiNER + Ollama when configured)",
                    info="Inference is local-only. If a model is unavailable, rule-based scanning continues and a warning is shown.",
                )
                scan_button = gr.Button("Scan for document ghosts", variant="primary", elem_id="ghost-scan")
            with gr.Column(scale=4, elem_classes=["ghost-panel"]):
                gr.Markdown("### 02 · Review before removal\nNothing is changed until you approve findings and run redaction.")
                gr.Markdown(
                    "**Workflow**\n\n"
                    "1. Scan visible text and selected hidden channels.\n"
                    "2. Review candidate text, category and source.\n"
                    "3. Tick **Approve** for each item to remove.\n"
                    "4. Save a separate copy and inspect verification status."
                )
                status = gr.Markdown("### Ready\n\nChoose a file and start a scan.", elem_id="ghost-status")
        report_state = gr.State(None)
        gr.Markdown("## Findings review\nApproved text matches are replaced. For PDF/DOCX, the sanitizer also removes common hidden channels (metadata, comments, tracked changes, hidden text and embedded files) as a conservative cleanup step.")
        table = gr.Dataframe(
            headers=["Approve", "Finding ID", "Category", "Matched text", "Source layer", "Location", "Reason"],
            datatype=["bool", "str", "str", "str", "str", "str", "str"],
            interactive=True, wrap=True,
            label="Select the exact candidates you want redacted",
        )
        with gr.Row():
            redact_button = gr.Button("Redact approved findings & verify", variant="primary", elem_id="ghost-redact")
            output_file = gr.File(label="Redacted copy", interactive=False)
        scan_button.click(scan_callback, inputs=[uploaded, use_ai], outputs=[table, report_state, status])
        redact_button.click(
            redact_callback, inputs=[uploaded, table, report_state], outputs=[output_file, status]
        )
        with gr.Accordion("Privacy and limitations", open=False):
            gr.Markdown(
                "- Processing and AI inference are intended to stay on this computer; the Ollama integration refuses non-loopback hosts.\n"
                "- Regex and AI detection can miss names, addresses, or unusual/contextual PII. Human review is essential.\n"
                "- Scanned PDFs, images and OCR are out of scope; scanned PDFs are refused.\n"
                "- Verification covers only the channels implemented by this project; it is not a forensic guarantee.\n"
                "- PDF/DOCX cleanup strips common hidden channels as a whole-document cleanup step, even when individual hidden findings were not ticked.\n"
                "- JSON reports may contain matched sensitive strings. Store them securely and use fake data in demos.\n"
                "- Keep this interface on `127.0.0.1`; do not enable public sharing or expose it to a network."
            )
    return demo


if __name__ == "__main__":
    build_app().launch(server_name="127.0.0.1", share=False, theme=_theme(), css=CSS)
