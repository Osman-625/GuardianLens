from scripts.verify_final_dataset import run_checks


def test_passes_on_clean_input():
    final_rows = [{"listing_id": "L1", "final_label": "legitimate", "final_label_source": "unanimous_ai"}]
    errors = run_checks(final_rows, listing_ids={"L1"})
    assert errors == []


def test_flags_duplicate_listing_id():
    final_rows = [
        {"listing_id": "L1", "final_label": "legitimate", "final_label_source": "unanimous_ai"},
        {"listing_id": "L1", "final_label": "suspicious", "final_label_source": "human_review"},
    ]
    errors = run_checks(final_rows, listing_ids={"L1"})
    assert any("duplicate" in e.lower() for e in errors)


def test_flags_invalid_label_value():
    final_rows = [{"listing_id": "L1", "final_label": "maybe_scam", "final_label_source": "unanimous_ai"}]
    errors = run_checks(final_rows, listing_ids={"L1"})
    assert any("invalid" in e.lower() for e in errors)


def test_flags_missing_listing():
    final_rows = [{"listing_id": "L1", "final_label": "legitimate", "final_label_source": "unanimous_ai"}]
    errors = run_checks(final_rows, listing_ids={"L1", "L2"})
    assert any("L2" in e for e in errors)


def test_unresolved_label_is_not_an_error_by_itself():
    final_rows = [{"listing_id": "L1", "final_label": None, "final_label_source": "unresolved"}]
    errors = run_checks(final_rows, listing_ids={"L1"})
    assert errors == []
