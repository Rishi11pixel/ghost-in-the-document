from pathlib import Path
import json
import subprocess
import sys

from app.pipeline import analyze_file


def test_analyze_all_synthetic_fixture_formats():
    fixture_dir = Path(__file__).parent / "fixtures"
    for name in ("synthetic_case.txt", "synthetic_case.pdf", "synthetic_case.docx"):
        report = analyze_file(fixture_dir / name)
        assert report.filename == name


def test_ground_truth_is_synthetic_and_has_expected_findings():
    path = Path(__file__).parent / "ground_truth" / "synthetic_case.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["synthetic_data_only"] is True
    assert len(data["expected_findings"]) >= 5


def test_gradio_ui_module_imports():
    import app.ui
    assert callable(app.ui.build_app)
