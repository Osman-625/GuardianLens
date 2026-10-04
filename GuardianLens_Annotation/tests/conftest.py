import pytest

from scripts.rule_engine.config import load_rules, load_thresholds

BASE_ROW = {
    "listing_id": "base", "description": "", "has_credential_request": False,
    "has_whatsapp": False, "has_advance_payment_language": False,
    "has_advance_payment_weak": False, "has_advance_payment_strong": False,
    "has_agent_fee_language": False, "has_fake_payment_language": False,
    "has_impersonation_language": False, "price_ratio": None, "price_anomaly_score": None,
    "cross_listing_duplicate_count": 0, "cross_listing_related_ids": [],
    "description_duplicate_count": 0, "description_related_ids": [],
    "account_age_days": None, "seller_rating": None, "review_count": None,
    "active_listing_count": None, "image_count": 1,
}


def make_row(**overrides) -> dict:
    return {**BASE_ROW, **overrides}


@pytest.fixture(scope="session")
def rules():
    return load_rules("rules/scam_rules.yaml")


@pytest.fixture(scope="session")
def thresholds():
    return load_thresholds("rules/thresholds.yaml")
