from __future__ import annotations

import json
from pathlib import Path

import pytest

from guardianlens import live_verification as lv
from guardianlens.errors import ProviderOperationError

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "live_pages"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# --------------------------------------------------------------------------- parsing

def test_parse_carousell_live_page():
    live = lv.parse_carousell(_read("carousell_live.html"))
    assert live is not None
    assert live.title == "Hot Air Gun"
    assert live.price == 10.0
    assert live.currency == "MYR"
    assert live.condition == "used"
    assert live.availability == "in_stock"


def test_parse_carousell_sold_page_and_removal_detection():
    html = _read("carousell_sold.html")
    live = lv.parse_carousell(html)
    assert live is not None
    assert live.availability == "sold"
    fetch = lv.FetchResult(status_code=410, final_url="https://www.carousell.com.my/p/splatoon-3/", html=html)
    assert lv.page_looks_removed("carousell", fetch, live) is True


def test_parse_mudah_live_page():
    url = "https://www.mudah.my/silver-high-heels-shoes-115643020.htm"
    live = lv.parse_mudah(_read("mudah_live.html"), url)
    assert live is not None
    assert live.title == "silver high heels shoes"
    assert live.price == 89.0
    assert live.currency == "MYR"
    assert live.location_state == "Kedah"


def test_parse_mudah_removed_page_and_removal_detection():
    # The original ad id (115625432) has no entry under adDetails.byID on this fixture --
    # it represents a redirect to a category browse page, same as a real expired ad.
    url = "https://www.mudah.my/xbox-series-s-fullset-115625432.htm"
    html = _read("mudah_removed.html")
    live = lv.parse_mudah(html, url)
    assert live is None
    fetch = lv.FetchResult(status_code=200, final_url="https://www.mudah.my/malaysia/games-and-consoles-for-sale", html=html)
    assert lv.page_looks_removed("mudah", fetch, live) is True


# --------------------------------------------------------------------------- normalization

@pytest.mark.parametrize(
    "text,expected",
    [
        ("New", "new"),
        ("Brand New", "new"),
        ("Like New", "used"),  # schema.org has no "like new" tier; Carousell reports UsedCondition for it
        ("Almost new", "used"),
        ("Used", "used"),
        ("Lightly Used", "used"),
        ("Pre-owned", "used"),
        (None, None),
        ("", None),
    ],
)
def test_condition_bucket_matches_schema_org_binary_distinction(text, expected):
    assert lv._condition_bucket(text) == expected


def test_compare_deterministic_flags_price_disagreement():
    row = {"price": 3000.0, "currency": "MYR", "condition": "Like new", "location_state": "Selangor"}
    live = lv.LivePage(price=2200.0, currency="MYR", condition="used", location_state="Selangor")
    result = lv.compare_deterministic(row, live)
    assert result.outcome == lv.OUTCOME_MISMATCH
    assert "price" in result.fields_in_disagreement


def test_compare_deterministic_like_new_vs_used_does_not_false_positive():
    row = {"price": 10.0, "currency": "MYR", "condition": "Like new", "location_state": None}
    live = lv.LivePage(price=10.0, currency="MYR", condition="used", location_state=None)
    result = lv.compare_deterministic(row, live)
    assert result.outcome == lv.OUTCOME_MATCH


# --------------------------------------------------------------------------- tier gating

class _FakeResponses:
    def __init__(self, output_text=None, exc=None):
        self.output_text = output_text
        self.exc = exc
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        return type("Resp", (), {"output_text": self.output_text})()


class _FakeClient:
    def __init__(self, output_text=None, exc=None):
        self.responses = _FakeResponses(output_text=output_text, exc=exc)


def test_matching_listing_never_calls_openai(monkeypatch):
    row = {
        "platform": "carousell", "price": 10.0, "currency": "MYR", "condition": "Used",
        "location_state": None, "source_url": "https://www.carousell.com.my/p/hot-air-gun-1411659175",
    }
    monkeypatch.setattr(
        lv, "fetch_listing_page",
        lambda url: lv.FetchResult(200, url, _read("carousell_live.html")),
    )
    fake_client = _FakeClient()

    def _fail_build():
        raise AssertionError("should not need to build an OpenAI client for a tier-1 match")

    monkeypatch.setattr(lv, "build_openai_client", _fail_build)
    comparison = lv.verify_listing(row, client=fake_client)

    assert comparison.outcome == lv.OUTCOME_MATCH
    assert comparison.tier == lv.TIER_DETERMINISTIC
    assert fake_client.responses.calls == 0


def test_price_disagreement_escalates_to_openai_and_reports_mismatch(monkeypatch):
    row = {
        "platform": "carousell", "title": "Samsung Galaxy S25 Ultra 512GB Phone only",
        "price": 3000.0, "currency": "MYR", "condition": "Like new", "location_state": "Selangor",
        "source_url": "https://www.carousell.com.my/p/hot-air-gun-1411659175",
    }
    monkeypatch.setattr(
        lv, "fetch_listing_page",
        lambda url: lv.FetchResult(200, url, _read("carousell_live.html")),  # price 10.0, not 3000.0
    )
    verdict_text = json.dumps({
        "verdict": "MISMATCH", "fields_in_disagreement": ["price", "title"],
        "details": "different product entirely",
    })
    fake_client = _FakeClient(output_text=verdict_text)

    comparison = lv.verify_listing(row, client=fake_client)

    assert comparison.outcome == lv.OUTCOME_MISMATCH
    assert comparison.tier == lv.TIER_OPENAI
    assert fake_client.responses.calls == 1
    assert "price" in comparison.fields_in_disagreement


def test_quota_error_is_not_retried_and_propagates_as_halt_batch(monkeypatch):
    row = {
        "platform": "carousell", "price": 3000.0, "currency": "MYR", "condition": "Used",
        "location_state": None, "source_url": "https://www.carousell.com.my/p/hot-air-gun-1411659175",
    }
    monkeypatch.setattr(
        lv, "fetch_listing_page",
        lambda url: lv.FetchResult(200, url, _read("carousell_live.html")),  # price 10.0, disagrees -> escalates
    )
    fake_client = _FakeClient(exc=RuntimeError("insufficient_quota: your account has no credit remaining"))

    with pytest.raises(ProviderOperationError) as excinfo:
        lv.verify_listing(row, client=fake_client)

    assert excinfo.value.classification.kind == "quota"
    assert excinfo.value.classification.halt_batch is True
    # Non-retryable: exactly one call, no wasted retry attempts burning more of the quota.
    assert fake_client.responses.calls == 1


def test_transient_error_is_retried_then_succeeds(monkeypatch):
    row = {
        "platform": "carousell", "price": 3000.0, "currency": "MYR", "condition": "Used",
        "location_state": None, "source_url": "https://www.carousell.com.my/p/hot-air-gun-1411659175",
    }
    monkeypatch.setattr(
        lv, "fetch_listing_page",
        lambda url: lv.FetchResult(200, url, _read("carousell_live.html")),
    )
    monkeypatch.setattr(lv.time, "sleep", lambda *_a, **_k: None)

    class _FlakyResponses(_FakeResponses):
        def create(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise TimeoutError("temporary timeout")
            return type("Resp", (), {"output_text": json.dumps(
                {"verdict": "MATCH", "fields_in_disagreement": [], "details": ""}
            )})()

    fake_client = _FakeClient()
    fake_client.responses = _FlakyResponses()

    comparison = lv.verify_listing(row, client=fake_client)

    assert comparison.outcome == lv.OUTCOME_MATCH
    assert comparison.tier == lv.TIER_OPENAI
    assert fake_client.responses.calls == 2


# --------------------------------------------------------------------------- persistence

def _insert_listing(con, listing_id: str) -> None:
    from guardianlens.db import now_iso
    ts = now_iso()
    con.execute(
        "INSERT INTO listings(listing_id,platform,source_url,source_url_hash,status,"
        "captured_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
        (listing_id, "carousell", f"https://www.carousell.com.my/p/{listing_id}",
         f"hash-{listing_id}", "approved", ts, ts, ts),
    )


def test_record_item_upserts_and_increments_attempt_count(isolated):
    from guardianlens.db import connect, transaction

    listing_id = "11111111-1111-1111-1111-111111111111"
    with transaction() as con:
        _insert_listing(con, listing_id)
        run_id = lv.create_run(
            con, selection="{}", item_limit=None, api_call_limit=200, rate_delay_seconds=1.5,
        )

    with transaction() as con:
        lv.record_item(
            con, run_id=run_id, listing_id=listing_id,
            comparison=lv.Comparison(outcome=lv.OUTCOME_MATCH, verdict="MATCH"),
            api_called=False,
        )
    with transaction() as con:
        lv.record_item(
            con, run_id=run_id, listing_id=listing_id,
            comparison=lv.Comparison(outcome=lv.OUTCOME_MISMATCH, verdict="MISMATCH", fields_in_disagreement=["price"]),
            api_called=True,
        )

    con = connect()
    try:
        row = dict(con.execute(
            "SELECT * FROM live_verification_items WHERE run_id=? AND listing_id=?",
            (run_id, listing_id),
        ).fetchone())
    finally:
        con.close()

    assert row["outcome"] == lv.OUTCOME_MISMATCH
    assert row["attempt_count"] == 2
    assert json.loads(row["fields_in_disagreement"]) == ["price"]


def test_resume_excludes_already_recorded_listings(isolated):
    from guardianlens.db import connect, transaction

    ids = ["22222222-2222-2222-2222-222222222222", "33333333-3333-3333-3333-333333333333"]
    with transaction() as con:
        for listing_id in ids:
            _insert_listing(con, listing_id)
        run_id = lv.create_run(con, selection="{}", item_limit=None, api_call_limit=200, rate_delay_seconds=1.5)
        lv.record_item(
            con, run_id=run_id, listing_id=ids[0],
            comparison=lv.Comparison(outcome=lv.OUTCOME_MATCH, verdict="MATCH"), api_called=False,
        )

    con = connect()
    try:
        recorded = {r["listing_id"] for r in con.execute(
            "SELECT listing_id FROM live_verification_items WHERE run_id=?", (run_id,)
        )}
    finally:
        con.close()

    remaining = [listing_id for listing_id in ids if listing_id not in recorded]
    assert remaining == [ids[1]]


def test_last_checked_at_reflects_most_recent_check(isolated):
    from guardianlens.db import connect, transaction

    listing_id = "44444444-4444-4444-4444-444444444444"
    with transaction() as con:
        _insert_listing(con, listing_id)
        assert lv.last_checked_at(con, listing_id) is None
        run_id = lv.create_run(con, selection="{}", item_limit=None, api_call_limit=200, rate_delay_seconds=1.5)
        lv.record_item(
            con, run_id=run_id, listing_id=listing_id,
            comparison=lv.Comparison(outcome=lv.OUTCOME_MATCH, verdict="MATCH"), api_called=False,
        )

    con = connect()
    try:
        assert lv.last_checked_at(con, listing_id) is not None
    finally:
        con.close()


def test_finish_run_updates_status_and_message(isolated):
    from guardianlens.db import connect, transaction

    with transaction() as con:
        run_id = lv.create_run(con, selection="{}", item_limit=None, api_call_limit=200, rate_delay_seconds=1.5)
    with transaction() as con:
        lv.finish_run(con, run_id, status="failed", api_calls=3, message="halted: quota exhausted")

    con = connect()
    try:
        row = dict(con.execute("SELECT * FROM live_verification_runs WHERE run_id=?", (run_id,)).fetchone())
    finally:
        con.close()
    assert row["status"] == "failed"
    assert row["api_calls"] == 3
    assert row["message"] == "halted: quota exhausted"
    assert row["finished_at"] is not None
