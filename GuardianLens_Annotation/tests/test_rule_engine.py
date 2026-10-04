import pytest

# NOT `from tests.conftest import ...` - a globally installed, unrelated "tests" package
# (from an ultralytics/OpenCV install on this machine) shadows our local tests/ package name.
# pytest's default "prepend" import mode already puts this file's own directory on sys.path,
# so importing conftest.py by its bare module name sidesteps the collision entirely.
from conftest import make_row


# ---------------------------------------------------------------------------
# Task 2: config loader
# ---------------------------------------------------------------------------

def test_load_rules_parses_required_fields(tmp_path):
    from scripts.rule_engine.config import Rule, load_rules

    yaml_text = """
- rule_id: R_TEST
  name: Test rule
  description: A test rule
  category: payment
  severity: strong
  weight: 4
  required_fields: [description]
  matching_method: keyword_group
  evidence_to_record: matched_phrase
  source_reference: "internal test"
  enabled: true
"""
    p = tmp_path / "scam_rules.yaml"
    p.write_text(yaml_text, encoding="utf-8")
    rules = load_rules(p)
    assert len(rules) == 1
    assert rules[0] == Rule(
        rule_id="R_TEST", name="Test rule", description="A test rule",
        category="payment", severity="strong", weight=4,
        required_fields=["description"], matching_method="keyword_group",
        evidence_to_record="matched_phrase", source_reference="internal test",
        enabled=True,
    )


def test_load_rules_rejects_duplicate_ids(tmp_path):
    from scripts.rule_engine.config import load_rules

    p = tmp_path / "dup.yaml"
    p.write_text("""
- rule_id: R_A
  name: A
  description: a
  category: payment
  severity: weak
  weight: 1
  required_fields: [description]
  matching_method: keyword_group
  evidence_to_record: x
  source_reference: ""
  enabled: true
- rule_id: R_A
  name: A2
  description: a2
  category: payment
  severity: weak
  weight: 1
  required_fields: [description]
  matching_method: keyword_group
  evidence_to_record: x
  source_reference: ""
  enabled: true
""", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate rule_id"):
        load_rules(p)


def test_scam_rules_yaml_loads_and_validates():
    from scripts.rule_engine.config import load_rules

    rules = load_rules("rules/scam_rules.yaml")
    ids = [r.rule_id for r in rules]
    assert len(ids) == len(set(ids)), "duplicate rule_id in scam_rules.yaml"
    assert "A1_SEMAK_MULE_PHONE" in ids
    disabled = [r.rule_id for r in rules if not r.enabled]
    assert "A1_SEMAK_MULE_PHONE" in disabled
    assert "A2_SEMAK_MULE_BANK" in disabled


# ---------------------------------------------------------------------------
# Task 3: keyword matcher
# ---------------------------------------------------------------------------

def test_keyword_matcher_uses_word_boundaries_not_substring():
    from scripts.rule_engine.keyword_matcher import match_keywords

    patterns = {"credential_request": {"critical": ["\\btac\\b"]}}
    results = match_keywords("please contact me for details", patterns)
    assert results == []
    results2 = match_keywords("send the TAC code now", patterns)
    assert len(results2) == 1
    assert results2[0].category == "credential_request"
    assert results2[0].strength == "critical"
    assert "tac" in [p.lower() for p in results2[0].matched_phrases]


def test_keyword_matcher_combo_strength():
    from scripts.rule_engine.keyword_matcher import has_combo, match_keywords

    patterns = {
        "off_platform_contact": {"weak": ["whatsapp"]},
        "advance_payment": {"strong": ["deposit first"]},
    }
    text = "WhatsApp me, deposit first before viewing"
    results = match_keywords(text, patterns)
    categories = {r.category for r in results}
    assert categories == {"off_platform_contact", "advance_payment"}
    assert has_combo(results, ["off_platform_contact", "advance_payment"]) is True
    assert has_combo(results, ["off_platform_contact", "credential_request"]) is False


# ---------------------------------------------------------------------------
# Task 5: feature extraction
# ---------------------------------------------------------------------------

def test_extract_features_preserves_nulls_and_computes_price_ratio(tmp_path):
    import csv

    from scripts.extract_annotation_features import extract_features

    listings = tmp_path / "listings.csv"
    with listings.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "listing_id", "platform", "category", "title", "description", "price",
            "price_missing", "account_age_days", "account_age_missing", "seller_rating",
            "seller_rating_missing", "review_count", "review_count_missing",
            "active_listing_count", "active_listing_count_missing", "image_count",
            "reused_image_indicator",
        ])
        w.writeheader()
        base = dict(platform="carousell", category="phones", title="iPhone 12", price_missing="False",
                    account_age_missing="False", seller_rating_missing="False",
                    review_count_missing="False", active_listing_count_missing="False",
                    image_count="3", reused_image_indicator="False")
        for i in range(5):
            w.writerow({**base, "listing_id": f"id{i}", "description": "normal listing",
                        "price": "1000", "account_age_days": "400", "seller_rating": "4.8",
                        "review_count": "20", "active_listing_count": "2"})
        w.writerow({**base, "listing_id": "cheap", "description": "WhatsApp me, deposit first",
                    "price": "200", "account_age_days": "", "account_age_missing": "True",
                    "seller_rating": "", "seller_rating_missing": "True",
                    "review_count": "0", "review_count_missing": "False",
                    "active_listing_count": "", "active_listing_count_missing": "True"})

    validation_summary = tmp_path / "summary.json"
    validation_summary.write_text('{"near_duplicate_cross_listing_groups": []}', encoding="utf-8")
    image_validation = tmp_path / "image_validation.csv"
    image_validation.write_text("listing_id,image_id,sha256,phash\n", encoding="utf-8")

    features = extract_features(listings, image_validation, validation_summary)
    cheap = next(f for f in features if f["listing_id"] == "cheap")
    assert cheap["account_age_days"] is None  # NULL stays NULL, never 0
    assert cheap["price_ratio"] < 0.25  # 200 / median(1000) = 0.2
    assert cheap["has_whatsapp"] is True
    assert cheap["has_advance_payment_strong"] is True  # "deposit first" is a strong-tier phrase
    assert cheap["has_advance_payment_weak"] is False   # mutually exclusive with strong


# ---------------------------------------------------------------------------
# Task 6: rule evaluation + confidence + reason + human-override contract
# ---------------------------------------------------------------------------

def test_evaluate_listing_critical_rule_forces_likely_scam(rules, thresholds):
    from scripts.rule_engine.evaluator import evaluate_listing

    row = make_row(listing_id="x1", description="please send the OTP", has_credential_request=True)
    result = evaluate_listing(row, rules, thresholds)
    assert result.critical_rule_count == 1
    assert result.rule_label == "likely_scam"
    assert result.label_confidence == "high"  # critical rule fired -> always high, never hedged
    assert "OTP" in result.label_reason
    assert "A3_A7_CREDENTIAL_REQUEST" in result.matched_rule_ids
    assert result.evidence["A3_A7_CREDENTIAL_REQUEST"]


def test_evaluate_listing_no_signals_is_insufficient_evidence_not_legitimate(thresholds):
    from scripts.rule_engine.evaluator import evaluate_listing

    row = make_row(listing_id="x2")
    result = evaluate_listing(row, [], thresholds)
    assert result.rule_label == "insufficient_evidence"
    assert result.label_confidence == "rough"
    assert result.label_reason
    assert "no rule fired" in result.label_reason.lower() or "insufficient evidence" in result.label_reason.lower()


def test_evaluate_listing_result_has_no_override_fields(thresholds):
    from scripts.rule_engine.evaluator import evaluate_listing

    row = make_row(listing_id="x3")
    result = evaluate_listing(row, [], thresholds)
    assert not hasattr(result, "human_override_label")


def test_b1_and_b2_are_mutually_exclusive(rules, thresholds):
    # Regression test for a real bug caught during implementation: a single
    # has_advance_payment_language boolean made B1 (weak) and B2 (strong) fire together on
    # every match, double-counting weight. Fixed via separate weak/strong feature flags.
    from scripts.rule_engine.evaluator import evaluate_listing

    weak_only = make_row(listing_id="w1", has_advance_payment_weak=True, has_advance_payment_strong=False)
    result = evaluate_listing(weak_only, rules, thresholds)
    assert "B1_ADVANCE_PAYMENT_WEAK" in result.matched_rule_ids
    assert "B2_ADVANCE_PAYMENT_STRONG" not in result.matched_rule_ids

    strong_only = make_row(listing_id="s1", has_advance_payment_weak=False, has_advance_payment_strong=True)
    result2 = evaluate_listing(strong_only, rules, thresholds)
    assert "B2_ADVANCE_PAYMENT_STRONG" in result2.matched_rule_ids
    assert "B1_ADVANCE_PAYMENT_WEAK" not in result2.matched_rule_ids


def test_run_rule_annotation_end_to_end(tmp_path):
    import csv
    import subprocess
    import sys
    from pathlib import Path

    features = tmp_path / "features.csv"
    fieldnames = [
        "listing_id", "description", "has_credential_request", "has_whatsapp",
        "has_advance_payment_language", "has_advance_payment_weak", "has_advance_payment_strong",
        "has_agent_fee_language", "has_fake_payment_language",
        "has_impersonation_language", "price_ratio", "price_anomaly_score",
        "cross_listing_duplicate_count", "cross_listing_related_ids",
        "description_duplicate_count", "description_related_ids",
        "account_age_days", "seller_rating", "review_count", "active_listing_count", "image_count",
    ]
    with features.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerow({"listing_id": "scam1", "description": "send OTP now", "has_credential_request": "True",
                    "has_whatsapp": "False", "has_advance_payment_language": "False",
                    "has_advance_payment_weak": "False", "has_advance_payment_strong": "False",
                    "has_agent_fee_language": "False", "has_fake_payment_language": "False",
                    "has_impersonation_language": "False", "price_ratio": "", "price_anomaly_score": "",
                    "cross_listing_duplicate_count": "0", "cross_listing_related_ids": "[]",
                    "description_duplicate_count": "0", "description_related_ids": "[]",
                    "account_age_days": "", "seller_rating": "", "review_count": "", "active_listing_count": "",
                    "image_count": "1"})
    out = tmp_path / "weak.csv"
    reports_dir = tmp_path / "reports"
    workspace = str(Path(__file__).resolve().parent.parent)
    result = subprocess.run(
        [sys.executable, "scripts/run_rule_annotation.py", "--features", str(features), "--out", str(out),
         "--reports-dir", str(reports_dir)],
        cwd=workspace, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    with out.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["listing_id"] == "scam1"
    assert rows[0]["rule_label"] == "likely_scam"
    assert rows[0]["label_confidence"] == "high"
    assert rows[0]["label_reason"]
    assert rows[0]["human_override_label"] == ""
    assert "ground_truth" not in "".join(rows[0].keys())


def test_rerun_preserves_human_override(tmp_path):
    import csv
    import subprocess
    import sys
    from pathlib import Path

    features = tmp_path / "features.csv"
    fieldnames = [
        "listing_id", "description", "has_credential_request", "has_whatsapp",
        "has_advance_payment_language", "has_advance_payment_weak", "has_advance_payment_strong",
        "has_agent_fee_language", "has_fake_payment_language",
        "has_impersonation_language", "price_ratio", "price_anomaly_score",
        "cross_listing_duplicate_count", "cross_listing_related_ids",
        "description_duplicate_count", "description_related_ids",
        "account_age_days", "seller_rating", "review_count", "active_listing_count", "image_count",
    ]
    with features.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerow({"listing_id": "x1", "description": "normal", "has_credential_request": "False",
                    "has_whatsapp": "False", "has_advance_payment_language": "False",
                    "has_advance_payment_weak": "False", "has_advance_payment_strong": "False",
                    "has_agent_fee_language": "False", "has_fake_payment_language": "False",
                    "has_impersonation_language": "False", "price_ratio": "", "price_anomaly_score": "",
                    "cross_listing_duplicate_count": "0", "cross_listing_related_ids": "[]",
                    "description_duplicate_count": "0", "description_related_ids": "[]",
                    "account_age_days": "", "seller_rating": "", "review_count": "", "active_listing_count": "",
                    "image_count": "1"})
    out = tmp_path / "weak.csv"
    reports_dir = tmp_path / "reports"
    workspace = str(Path(__file__).resolve().parent.parent)

    def run():
        return subprocess.run(
            [sys.executable, "scripts/run_rule_annotation.py", "--features", str(features), "--out", str(out),
             "--reports-dir", str(reports_dir)],
            cwd=workspace, capture_output=True, text=True,
        )

    r1 = run()
    assert r1.returncode == 0, r1.stderr
    with out.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    rows[0]["human_override_label"] = "likely_legitimate"
    rows[0]["reviewer_id"] = "osman"
    with out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    r2 = run()
    assert r2.returncode == 0, r2.stderr
    with out.open(encoding="utf-8", newline="") as f:
        rows_after = list(csv.DictReader(f))
    assert rows_after[0]["human_override_label"] == "likely_legitimate"
    assert rows_after[0]["reviewer_id"] == "osman"


# ---------------------------------------------------------------------------
# Task 7: review queue
# ---------------------------------------------------------------------------

def test_build_review_queue_orders_by_priority(tmp_path):
    import csv

    from scripts.build_review_queue import build_queue

    weak = tmp_path / "weak.csv"
    with weak.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["listing_id", "rule_label", "risk_score", "trust_score",
                                           "critical_rule_count", "strong_rule_count",
                                           "human_override_label"])
        w.writeheader()
        w.writerow({"listing_id": "leg1", "rule_label": "likely_legitimate", "risk_score": "0",
                    "trust_score": "3", "critical_rule_count": "0", "strong_rule_count": "0",
                    "human_override_label": ""})
        w.writerow({"listing_id": "scam1", "rule_label": "likely_scam", "risk_score": "10",
                    "trust_score": "0", "critical_rule_count": "1", "strong_rule_count": "0",
                    "human_override_label": ""})
        w.writerow({"listing_id": "susp1", "rule_label": "suspicious", "risk_score": "5",
                    "trust_score": "0", "critical_rule_count": "0", "strong_rule_count": "0",
                    "human_override_label": ""})

    queue = build_queue(weak)
    order = [row["listing_id"] for row in queue]
    assert len(queue) == 3, "full coverage by default - nothing sampled away"
    assert order.index("scam1") < order.index("susp1") < order.index("leg1")
    assert queue[0]["human_override_label"] == ""


def test_build_review_queue_can_still_sample_legitimate_when_explicitly_asked(tmp_path):
    import csv

    from scripts.build_review_queue import build_queue

    weak = tmp_path / "weak2.csv"
    with weak.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["listing_id", "rule_label", "risk_score", "trust_score",
                                           "critical_rule_count", "strong_rule_count",
                                           "human_override_label"])
        w.writeheader()
        for i in range(20):
            w.writerow({"listing_id": f"leg{i}", "rule_label": "likely_legitimate", "risk_score": "0",
                        "trust_score": "3", "critical_rule_count": "0", "strong_rule_count": "0",
                        "human_override_label": ""})
    queue = build_queue(weak, random_seed=42, legitimate_sample_rate=0.25)
    assert len(queue) == 5


# ---------------------------------------------------------------------------
# Task 9: 16 required scenarios
# ---------------------------------------------------------------------------

def test_scenario_01_old_seller_good_rating_is_legitimate(rules, thresholds):
    from scripts.rule_engine.evaluator import evaluate_listing

    row = make_row(listing_id="s1", account_age_days=800, seller_rating=4.9, review_count=50,
                    price_ratio=1.0)
    result = evaluate_listing(row, rules, thresholds)
    assert result.rule_label == "likely_legitimate"


def test_scenario_02_new_seller_zero_reviews_otherwise_normal_not_scam(rules, thresholds):
    from scripts.rule_engine.evaluator import evaluate_listing

    row = make_row(listing_id="s2", account_age_days=3, review_count=0, price_ratio=1.0)
    result = evaluate_listing(row, rules, thresholds)
    assert result.rule_label != "likely_scam"


def test_scenario_03_very_low_price_only_not_scam(rules, thresholds):
    from scripts.rule_engine.evaluator import evaluate_listing

    row = make_row(listing_id="s3", price_ratio=0.2, price_anomaly_score="very_strong")
    result = evaluate_listing(row, rules, thresholds)
    assert result.rule_label != "likely_scam"


def test_scenario_04_whatsapp_only_not_scam(rules, thresholds):
    from scripts.rule_engine.evaluator import evaluate_listing

    row = make_row(listing_id="s4", has_whatsapp=True)
    result = evaluate_listing(row, rules, thresholds)
    assert result.rule_label != "likely_scam"


def test_scenario_05_whatsapp_plus_deposit_is_at_least_suspicious(rules, thresholds):
    from scripts.rule_engine.evaluator import evaluate_listing

    row = make_row(listing_id="s5", has_whatsapp=True, has_advance_payment_strong=True)
    result = evaluate_listing(row, rules, thresholds)
    assert result.rule_label in ("suspicious", "likely_scam")


def test_scenario_06_otp_request_is_very_high_risk(rules, thresholds):
    from scripts.rule_engine.evaluator import evaluate_listing

    row = make_row(listing_id="s6", has_credential_request=True)
    result = evaluate_listing(row, rules, thresholds)
    assert result.rule_label == "likely_scam"
    assert result.critical_rule_count >= 1


def test_scenario_07_suspicious_payment_link_present(rules, thresholds):
    # url_suspicious is disabled/stubbed - this documents the CURRENT (honest) behavior and
    # must be re-asserted once the follow-up domain-heuristics task lands.
    from scripts.rule_engine.evaluator import evaluate_listing

    row = make_row(listing_id="s7")
    result = evaluate_listing(row, rules, thresholds)
    assert "G1_SUSPICIOUS_URL" not in result.matched_rule_ids


def test_scenario_08_agent_fee_to_release_payment_is_very_high_risk(rules, thresholds):
    from scripts.rule_engine.evaluator import evaluate_listing

    row = make_row(listing_id="s8", has_agent_fee_language=True)
    result = evaluate_listing(row, rules, thresholds)
    assert "C1_RELEASE_FEE" in result.matched_rule_ids
    assert result.rule_label in ("suspicious", "likely_scam")


def test_scenario_09_reused_image_alone_not_scam(rules, thresholds):
    from scripts.rule_engine.evaluator import evaluate_listing

    row = make_row(listing_id="s9", cross_listing_duplicate_count=1, cross_listing_related_ids=["other1"])
    result = evaluate_listing(row, rules, thresholds)
    assert result.rule_label != "likely_scam"


def test_scenario_10_reused_image_plus_low_price_plus_new_account_is_suspicious_or_worse(rules, thresholds):
    from scripts.rule_engine.evaluator import evaluate_listing

    row = make_row(listing_id="s10", cross_listing_duplicate_count=1, cross_listing_related_ids=["other1"],
                    price_ratio=0.2, price_anomaly_score="very_strong", account_age_days=2)
    result = evaluate_listing(row, rules, thresholds)
    assert result.rule_label in ("suspicious", "likely_scam")


def test_scenario_11_trusted_seller_plus_one_weak_risk_stays_non_scam(rules, thresholds):
    from scripts.rule_engine.evaluator import evaluate_listing

    row = make_row(listing_id="s11", account_age_days=900, seller_rating=4.8, review_count=80,
                    has_whatsapp=True)
    result = evaluate_listing(row, rules, thresholds)
    assert result.rule_label != "likely_scam"


def test_scenario_12_critical_signal_overrides_strong_trust_history(rules, thresholds):
    from scripts.rule_engine.evaluator import evaluate_listing

    row = make_row(listing_id="s12", account_age_days=900, seller_rating=4.9, review_count=200,
                    has_credential_request=True)
    result = evaluate_listing(row, rules, thresholds)
    assert result.rule_label == "likely_scam"


def test_scenario_13_missing_seller_data_is_null_not_zero(rules, thresholds):
    from scripts.rule_engine.evaluator import evaluate_listing

    row = make_row(listing_id="s13")
    result = evaluate_listing(row, rules, thresholds)
    assert row["account_age_days"] is None
    assert result.rule_label in ("insufficient_evidence", "suspicious")


def test_scenario_14_missing_price(rules, thresholds):
    from scripts.rule_engine.evaluator import evaluate_listing

    row = make_row(listing_id="s14", price_ratio=None, price_anomaly_score=None)
    result = evaluate_listing(row, rules, thresholds)
    assert "H1_PRICE_ANOMALY" not in result.matched_rule_ids


def test_scenario_15_missing_images(rules, thresholds):
    from scripts.rule_engine.evaluator import evaluate_listing

    row = make_row(listing_id="s15", image_count=0, cross_listing_duplicate_count=0)
    result = evaluate_listing(row, rules, thresholds)
    assert "I1_CROSS_LISTING_IMAGE_REUSE" not in result.matched_rule_ids


def test_scenario_16_mixed_malay_english_scam_wording():
    import yaml

    from scripts.rule_engine.keyword_matcher import match_keywords

    patterns = yaml.safe_load(open("rules/keyword_patterns.yaml", encoding="utf-8"))
    text = "Boleh WhatsApp saya, bayar dulu untuk secure barang ni"
    matches = match_keywords(text, patterns)
    categories = {m.category for m in matches}
    assert "off_platform_contact" in categories
    assert "advance_payment" in categories


@pytest.mark.parametrize("listing_id,overrides", [
    ("r1", {}),
    ("r2", {"has_credential_request": True}),
    ("r3", {"account_age_days": 900, "seller_rating": 4.9, "review_count": 200}),
    ("r4", {"cross_listing_duplicate_count": 3, "cross_listing_related_ids": ["a", "b", "c"]}),
])
def test_every_scenario_gets_a_nonblank_reason_and_valid_confidence(rules, thresholds, listing_id, overrides):
    from scripts.rule_engine.evaluator import evaluate_listing

    row = make_row(listing_id=listing_id, **overrides)
    result = evaluate_listing(row, rules, thresholds)
    assert result.label_reason.strip() != ""
    assert result.label_confidence in ("rough", "moderate", "high")
    assert "weak" not in result.label_confidence


# ---------------------------------------------------------------------------
# Task 10: verifier
# ---------------------------------------------------------------------------

def test_verifier_flags_ground_truth_label_column(tmp_path):
    import csv

    from scripts.verify_rule_annotations import check_no_ground_truth_column

    bad = tmp_path / "bad.csv"
    with bad.open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(["listing_id", "ground_truth_label"])
    errors = check_no_ground_truth_column(bad)
    assert errors, "must flag a ground_truth_label column if present"

    good = tmp_path / "good.csv"
    with good.open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(["listing_id", "rule_label"])
    assert check_no_ground_truth_column(good) == []


def test_verifier_flags_blank_reason_or_weak_confidence(tmp_path):
    import csv

    from scripts.verify_rule_annotations import REQUIRED_LABELING_COLUMNS, check_every_row_fully_labeled

    bad = tmp_path / "bad_labels.csv"
    with bad.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["listing_id", *REQUIRED_LABELING_COLUMNS])
        w.writeheader()
        w.writerow({"listing_id": "x1", "rule_label": "likely_scam", "label_confidence": "weak",
                    "label_reason": "", "human_override_label": "", "human_override_reason": "",
                    "reviewer_id": "", "override_timestamp": ""})
    errors = check_every_row_fully_labeled(bad)
    assert any("label_reason" in e for e in errors)
    assert any("label_confidence" in e for e in errors)

    good = tmp_path / "good_labels.csv"
    with good.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["listing_id", *REQUIRED_LABELING_COLUMNS])
        w.writeheader()
        w.writerow({"listing_id": "x1", "rule_label": "likely_scam", "label_confidence": "high",
                    "label_reason": "credential request detected", "human_override_label": "",
                    "human_override_reason": "", "reviewer_id": "", "override_timestamp": ""})
    assert check_every_row_fully_labeled(good) == []
