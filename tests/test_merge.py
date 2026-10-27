from app.models import Finding
from app.merge import merge_findings


def f(text, category="EMAIL", layer="regex", location="line 1", approved=True, reason=None, fid="id"):
    return Finding(id=fid, text=text, category=category, source_layer=layer, reason=reason,
                   location=location, approved=approved)


def test_empty_inputs():
    assert merge_findings() == []
    assert merge_findings([], []) == []


def test_exact_duplicates_merge_sources_and_reasons():
    result = merge_findings([f("morgan@example.invalid", layer="regex", reason="pattern", fid="a")],
                            [f("morgan@example.invalid", layer="llm", reason="context", fid="b")])
    assert len(result) == 1
    assert result[0].source_layer == "llm+regex"
    assert "pattern" in result[0].reason and "context" in result[0].reason


def test_same_text_at_different_locations_stays_separate():
    result = merge_findings([f("same@example.invalid", location="line 1"),
                             f("same@example.invalid", location="line 8")])
    assert len(result) == 2


def test_same_text_different_categories_stays_separate():
    assert len(merge_findings([f("123456", category="PIN_CODE"),
                               f("123456", category="OTHER_ID")])) == 2


def test_unapproved_duplicate_keeps_result_unapproved():
    result = merge_findings([f("same@example.invalid", approved=True),
                             f("same@example.invalid", layer="llm", approved=False)])
    assert len(result) == 1 and result[0].approved is False


def test_input_unchanged_and_order_deterministic():
    a, b = f("z@example.invalid", fid="z"), f("a@example.invalid", fid="a")
    before = (a.id, a.source_layer, a.reason)
    one, two = merge_findings([a, b]), merge_findings([b, a])
    assert (a.id, a.source_layer, a.reason) == before
    assert [(x.text, x.category, x.location) for x in one] == [(x.text, x.category, x.location) for x in two]
