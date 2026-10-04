from pathlib import Path

from scripts.verify_guideline_consistency import (
    check_label_schema_structure,
    check_doc_contains_sections,
    check_no_stale_phrases,
    run_all_checks,
)

WORKSPACE = Path(__file__).resolve().parent.parent


def test_check_label_schema_structure_flags_missing_taxonomy():
    errors = check_label_schema_structure({"labels": []})
    assert any("signal_taxonomy" in e for e in errors)
    assert any("confidence_scale" in e for e in errors)
    assert any("scam_fraud_boundary_rule" in e for e in errors)
    assert any("evidence_sufficiency_gate" in e for e in errors)
    assert any("conflict_policy" in e for e in errors)


def test_check_label_schema_structure_passes_on_complete_schema():
    schema = {
        "signal_taxonomy": {"weak": {}, "strong": {}, "critical": {}},
        "confidence_scale": {"anchors": {"1": "x", "2": "x", "3": "x", "4": "x", "5": "x"}},
        "scam_fraud_boundary_rule": {"rules": ["a"]},
        "evidence_sufficiency_gate": {"rule": "x"},
        "conflict_policy": {"rules": ["a"]},
    }
    assert check_label_schema_structure(schema) == []


def test_check_doc_contains_sections_flags_missing_header():
    errors = check_doc_contains_sections("## Foo\ncontent", ["## Foo", "## Bar"], "test.md")
    assert len(errors) == 1
    assert "## Bar" in errors[0]


def test_check_no_stale_phrases_flags_conflated_wording():
    errors = check_no_stale_phrases(
        "one flag is strong enough alone", ["one flag is strong enough alone"], "test.md"
    )
    assert len(errors) == 1


def test_check_no_stale_phrases_passes_when_absent():
    errors = check_no_stale_phrases("nothing bad here", ["forbidden phrase"], "test.md")
    assert errors == []


def test_run_all_checks_on_real_workspace_docs():
    errors = run_all_checks(WORKSPACE)
    assert errors == [], "\n".join(errors)
