from scripts.build_human_review_queue import assign_priority, build_queue


def test_p0_severe_disagreement():
    row = {"claude_label": "legitimate", "codex_label": "scam_fraud", "severe_disagreement": True,
           "ai_agreement": False, "rule_ai_conflict": False, "claude_confidence": "4", "codex_confidence": "5",
           "annotation_readiness": "ready"}
    priority, reason = assign_priority(row)
    assert priority == "P0"


def test_p1_plain_ai_disagreement():
    row = {"claude_label": "suspicious", "codex_label": "insufficient_evidence", "severe_disagreement": False,
           "ai_agreement": False, "rule_ai_conflict": False, "claude_confidence": "3", "codex_confidence": "2",
           "annotation_readiness": "ready"}
    priority, reason = assign_priority(row)
    assert priority == "P1"


def test_p2_rule_conflict_only():
    row = {"claude_label": "legitimate", "codex_label": "legitimate", "severe_disagreement": False,
           "ai_agreement": True, "rule_ai_conflict": True, "claude_confidence": "4", "codex_confidence": "4",
           "annotation_readiness": "ready"}
    priority, reason = assign_priority(row)
    assert priority == "P2"


def test_p3_low_confidence_unanimous():
    row = {"claude_label": "suspicious", "codex_label": "suspicious", "severe_disagreement": False,
           "ai_agreement": True, "rule_ai_conflict": False, "claude_confidence": "1", "codex_confidence": "2",
           "annotation_readiness": "ready"}
    priority, reason = assign_priority(row)
    assert priority == "P3"


def test_p3_needs_review_readiness_flag():
    row = {"claude_label": "legitimate", "codex_label": "legitimate", "severe_disagreement": False,
           "ai_agreement": True, "rule_ai_conflict": False, "claude_confidence": "5", "codex_confidence": "5",
           "annotation_readiness": "needs_review"}
    priority, reason = assign_priority(row)
    assert priority == "P3"


def test_p4_unanimous_high_confidence_clean():
    row = {"claude_label": "legitimate", "codex_label": "legitimate", "severe_disagreement": False,
           "ai_agreement": True, "rule_ai_conflict": False, "claude_confidence": "5", "codex_confidence": "5",
           "annotation_readiness": "ready"}
    priority, reason = assign_priority(row)
    assert priority == "P4"


def test_build_queue_orders_by_priority_and_samples_p4():
    rows = [
        {"claude_label": "legitimate", "codex_label": "legitimate", "severe_disagreement": False,
         "ai_agreement": True, "rule_ai_conflict": False, "claude_confidence": "5", "codex_confidence": "5",
         "annotation_readiness": "ready", "listing_id": f"L{i}"}
        for i in range(20)
    ] + [
        {"claude_label": "legitimate", "codex_label": "scam_fraud", "severe_disagreement": True,
         "ai_agreement": False, "rule_ai_conflict": False, "claude_confidence": "4", "codex_confidence": "4",
         "annotation_readiness": "ready", "listing_id": "P0_ROW"}
    ]
    queue = build_queue(rows, qc_sample_rate=0.5, seed=42)
    assert queue[0]["listing_id"] == "P0_ROW"
    assert queue[0]["review_priority"] == "P0"
    assert all(r["review_priority"] != "P0" for r in queue[1:])
    p4_reviewed = [r for r in queue if r["review_priority"] == "P4" and r["requires_human_review"]]
    assert len(p4_reviewed) >= 1
