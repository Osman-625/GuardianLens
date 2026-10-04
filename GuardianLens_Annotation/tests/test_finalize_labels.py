from scripts.finalize_labels import finalize


def test_human_reviewed_row_uses_human_final_label():
    consensus = [{"listing_id": "L1", "claude_label": "legitimate", "codex_label": "scam_fraud"}]
    reviewed = [{"listing_id": "L1", "human_final_label": "suspicious", "review_status": "reviewed"}]
    out = finalize(consensus, reviewed)
    assert out[0]["final_label"] == "suspicious"
    assert out[0]["final_label_source"] == "human_review"


def test_unanimous_unreviewed_row_finalizes_from_ai_agreement():
    consensus = [{"listing_id": "L2", "claude_label": "legitimate", "codex_label": "legitimate"}]
    reviewed = []
    out = finalize(consensus, reviewed)
    assert out[0]["final_label"] == "legitimate"
    assert out[0]["final_label_source"] == "unanimous_ai"


def test_disagreement_without_human_review_is_unresolved_not_defaulted():
    consensus = [{"listing_id": "L3", "claude_label": "legitimate", "codex_label": "scam_fraud"}]
    reviewed = []
    out = finalize(consensus, reviewed)
    assert out[0]["final_label"] is None
    assert out[0]["final_label_source"] == "unresolved"


def test_rule_label_is_never_a_final_label_source():
    consensus = [{"listing_id": "L4", "claude_label": None, "codex_label": None, "rule_label_mapped": "scam_fraud"}]
    out = finalize(consensus, [])
    assert out[0]["final_label_source"] != "rule_label"
    assert out[0]["final_label_source"] == "unresolved"


def test_human_review_wins_even_when_ai_agrees():
    consensus = [{"listing_id": "L5", "claude_label": "legitimate", "codex_label": "legitimate"}]
    reviewed = [{"listing_id": "L5", "human_final_label": "suspicious", "review_status": "reviewed"}]
    out = finalize(consensus, reviewed)
    assert out[0]["final_label"] == "suspicious"
    assert out[0]["final_label_source"] == "human_review"
