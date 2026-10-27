import json
from pathlib import Path

ROOT = Path(__file__).parent
FIXTURES = ROOT / "fixtures"
TRUTH = ROOT / "ground_truth" / "synthetic_case.json"


def test_synthetic_fixtures_exist_and_are_nonempty():
    for name in ("synthetic_case.txt", "synthetic_case.pdf", "synthetic_case.docx"):
        path = FIXTURES / name
        assert path.exists(), f"Missing fixture: {name}"
        assert path.stat().st_size > 0


def test_ground_truth_is_marked_synthetic_and_has_expected_categories():
    data = json.loads(TRUTH.read_text(encoding="utf-8"))
    assert data["synthetic_data_only"] is True
    categories = {item["category"] for item in data["expected_findings"]}
    assert {"NAME", "EMAIL", "PHONE", "ID_NUMBER", "ADDRESS", "METADATA", "HIDDEN_TEXT"} <= categories


def test_fixture_markers_are_fake_and_not_real_contact_details():
    txt = (FIXTURES / "synthetic_case.txt").read_text(encoding="utf-8")
    assert "morgan.example@example.invalid" in txt
    assert "SYNTHETIC TEST DOCUMENT" in txt


def test_evaluation_ground_truth_covers_ten_synthetic_files():
    data = json.loads((ROOT / "ground_truth" / "evaluation_cases.json").read_text(encoding="utf-8"))
    assert data["synthetic_data_only"] is True
    assert len(data["cases"]) == 10
    assert all((FIXTURES / name).is_file() for name in data["cases"])
