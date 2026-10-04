import csv
from pathlib import Path

from scripts.compute_consensus import build_consensus, RULE_LABEL_MAP


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def test_three_way_agreement_when_all_sources_match(tmp_path):
    claude_csv = tmp_path / "claude.csv"
    codex_csv = tmp_path / "codex.csv"
    rule_csv = tmp_path / "rule.csv"
    _write_csv(claude_csv, [{"listing_id": "L1", "label": "scam_fraud", "confidence": "5"}],
               ["listing_id", "label", "confidence"])
    _write_csv(codex_csv, [{"listing_id": "L1", "label": "scam_fraud", "confidence": "4"}],
               ["listing_id", "label", "confidence"])
    _write_csv(rule_csv, [{"listing_id": "L1", "rule_label": "likely_scam", "label_confidence": "high"}],
               ["listing_id", "rule_label", "label_confidence"])

    rows = build_consensus(claude_csv, codex_csv, rule_csv)
    assert len(rows) == 1
    row = rows[0]
    assert row["ai_agreement"] is True
    assert row["rule_label_mapped"] == "scam_fraud"
    assert row["three_way_agreement"] is True
    assert row["rule_ai_conflict"] is False
    assert row["severe_disagreement"] is False


def test_severe_disagreement_flagged(tmp_path):
    claude_csv = tmp_path / "claude.csv"
    codex_csv = tmp_path / "codex.csv"
    rule_csv = tmp_path / "rule.csv"
    _write_csv(claude_csv, [{"listing_id": "L2", "label": "legitimate", "confidence": "3"}],
               ["listing_id", "label", "confidence"])
    _write_csv(codex_csv, [{"listing_id": "L2", "label": "scam_fraud", "confidence": "5"}],
               ["listing_id", "label", "confidence"])
    _write_csv(rule_csv, [{"listing_id": "L2", "rule_label": "insufficient_evidence", "label_confidence": "rough"}],
               ["listing_id", "rule_label", "label_confidence"])

    rows = build_consensus(claude_csv, codex_csv, rule_csv)
    assert rows[0]["severe_disagreement"] is True
    assert rows[0]["ai_agreement"] is False


def test_rule_conflict_when_ai_agrees_but_rule_differs(tmp_path):
    claude_csv = tmp_path / "claude.csv"
    codex_csv = tmp_path / "codex.csv"
    rule_csv = tmp_path / "rule.csv"
    _write_csv(claude_csv, [{"listing_id": "L5", "label": "suspicious", "confidence": "3"}],
               ["listing_id", "label", "confidence"])
    _write_csv(codex_csv, [{"listing_id": "L5", "label": "suspicious", "confidence": "3"}],
               ["listing_id", "label", "confidence"])
    _write_csv(rule_csv, [{"listing_id": "L5", "rule_label": "likely_legitimate", "label_confidence": "moderate"}],
               ["listing_id", "rule_label", "label_confidence"])

    rows = build_consensus(claude_csv, codex_csv, rule_csv)
    assert rows[0]["ai_agreement"] is True
    assert rows[0]["rule_ai_conflict"] is True
    assert rows[0]["three_way_agreement"] is False


def test_rule_label_map_covers_all_rule_engine_values():
    assert RULE_LABEL_MAP == {
        "likely_legitimate": "legitimate",
        "likely_scam": "scam_fraud",
        "suspicious": "suspicious",
        "insufficient_evidence": "insufficient_evidence",
    }
