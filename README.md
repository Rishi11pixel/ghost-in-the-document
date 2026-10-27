# Ghost in the Document

Local-first privacy review for TXT, text-based PDF, and DOCX. It detects structured
visible PII candidates, scans selected hidden document channels, asks the user to
approve findings, creates a separate sanitized copy, and performs post-save checks.

## Quick start (Windows / Python 3.11)

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pytest -v
.venv\Scripts\python.exe -m app.ui
```

The interface binds to `127.0.0.1` and does not enable Gradio sharing. Keep it local;
do not expose it to a public network. The app code does not call remote inference APIs. Optional Ollama inference is restricted to a loopback host; GLiNER must use a downloaded local model directory.

## Optional local AI assist

See `LOCAL_AI_SETUP.md` for one-time model setup and offline-use instructions. AI is optional so the app remains usable without model dependencies; when enabled, check the UI warnings to confirm which local layers actually ran.

## Evaluation

Synthetic fixtures and expected findings are under `tests/fixtures/` and
`tests/ground_truth/`. Run:

```powershell
.venv\Scripts\python.exe -m app.evaluate
```

This writes `evaluation-results.json`. Metrics compare exact unique text strings across
the small synthetic fixture set; they are not location-aware and are not evidence of
real-world performance. Review missed findings and false positives before submission.

## Supported scope and limitations

- TXT: exact-string replacement in a separate output file, followed by re-reading.
- Text-based PDF: applies PDF redaction operations, removes common metadata, annotations,
  and embedded files, then reopens and checks extracted text and those channels.
- DOCX: best-effort OOXML sanitization for visible matches and common hidden channels
  (metadata, comments, tracked changes, hidden text runs). Paragraph formatting can
  be simplified where a redaction occurs.
- Scanned/image-only PDFs are refused. OCR is not implemented.
- Regex detection is always available. Optional local AI assist adds GLiNER NER and an Ollama LLM; it must be configured and its runtime warnings checked. Names, addresses, contextual PII, and unusual formats may still be missed; human review is required.
- The hidden scanner checks selected common channels, not every possible embedded object,
  external relationship, revision artifact, or forensic recovery path.
- Post-save verification covers only the implemented checks. `verified_clean` must not
  be interpreted as a universal guarantee that a file contains no sensitive information.
- JSON reports include matched sensitive strings. Keep them private.
- Use synthetic test data during development and demo.

## Project structure

- `app/extract.py` — local extraction and scanned-PDF guard
- `app/detect_rules.py` — deterministic regex detection
- `app/hidden.py` — hidden-content scanner
- `app/merge.py` — conservative finding merge
- `app/redact.py`, `app/redact_docx.py` — format-specific redaction dispatch
- `app/pipeline.py` — end-to-end orchestration
- `app/ui.py` — local review UI
- `app/evaluate.py` — synthetic ground-truth evaluation
