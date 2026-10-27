import io
import json

from app import detect_ai


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_ollama_verbatim_guard_discards_hallucinated_spans(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    source = "Contact Riley Sample at riley.sample@example.invalid"
    answer = {
        "message": {
            "content": json.dumps({
                "findings": [
                    {"text": "Riley Sample", "category": "NAME", "reason": "Person name in source."},
                    {"text": "Jordan Made Up", "category": "NAME", "reason": "Hallucinated."},
                ]
            })
        }
    }
    monkeypatch.setattr(detect_ai.urllib.request, "urlopen", lambda *a, **k: _FakeResponse(answer))
    findings, warning = detect_ai.detect_ollama(source, location="line 1")
    assert warning is None
    assert [f.text for f in findings] == ["Riley Sample"]
    assert findings[0].source_layer == "llm"


def test_ollama_refuses_non_loopback_host(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "https://example.com")
    findings, warning = detect_ai.detect_ollama("Some synthetic text")
    assert findings == []
    assert warning and "loopback" in warning


def test_gliner_skips_cleanly_without_local_model_path(monkeypatch):
    monkeypatch.delenv("GHOST_GLINER_MODEL_PATH", raising=False)
    findings, warning = detect_ai.detect_gliner("Riley Sample lives at 12 Fiction Street")
    assert findings == []
    assert warning and "local model directory" in warning


def test_pipeline_includes_ai_candidates_and_warnings_when_enabled(monkeypatch, tmp_path):
    from app import pipeline
    from app.models import Finding

    source = tmp_path / "context.txt"
    source.write_text("My friend Riley Sample attends Example Academy.", encoding="utf-8")

    def fake_detect_ai(text, *, location=None):
        return [Finding(
            id="ner-test", text="Riley Sample", category="NAME", source_layer="ner",
            reason="Synthetic mocked NER finding", location=location, approved=True,
        )], ["synthetic AI warning"]

    monkeypatch.setattr(pipeline, "detect_ai", fake_detect_ai)
    report = pipeline.analyze_file(source, use_ai=True)
    assert any(f.text == "Riley Sample" and f.source_layer == "ner" for f in report.findings)
    assert "synthetic AI warning" in report.warnings
