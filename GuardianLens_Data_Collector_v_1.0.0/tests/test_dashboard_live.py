"""Dashboard views must represent stored state before and after live refresh."""
from html.parser import HTMLParser
import json

from fastapi.testclient import TestClient

from guardianlens.app import app
from guardianlens.db import now_iso, transaction
from guardianlens.replay import create_manual_batch


class DashboardHTML(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.ids = []
        self.sections = {}
        self.initial = ""
        self.in_initial = False
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag == "details" and "data-dashboard-section" in attrs:
            self.sections[attrs["data-dashboard-section"]] = "open" in attrs
        if tag == "script" and attrs.get("id") == "dashboardInitialState":
            self.in_initial = True

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_initial = False

    def handle_data(self, data):
        if self.in_initial:
            self.initial += data


def test_dashboard_initial_snapshot_and_metrics_use_persisted_counts(isolated):
    create_manual_batch(
        "https://www.carousell.com.my/p/dashboard-test-700801/\n"
        "https://www.carousell.com.my/p/dashboard-test-700802/",
        "Stored batch </script><script>alert(1)</script>",
    )
    with transaction() as con:
        con.execute(
            """INSERT INTO processing_runs
               (run_id,started_at,finished_at,status,attempted,successful,ai_failures)
               VALUES (?,?,?,'completed',7,5,2)""",
            ("dashboard-test-run", now_iso(), now_iso()),
        )
    with TestClient(app) as client:
        page = client.get("/")
        live = client.get("/api/dashboard/status").json()
        assert client.get("/static/app.js").status_code == 200
        assert client.get("/static/attention_agent.js").status_code == 200
        assert client.get("/static/styles.css").status_code == 200

    assert page.status_code == 200
    parsed = DashboardHTML(page.text)
    initial = json.loads(parsed.initial)
    for key in ("counts", "plan", "review_stats", "batch", "replay"):
        assert initial[key] == live[key]
    assert initial["replay"]["import_summary"]["rows"] == 2
    assert 'id="rRows">2</b>' in page.text
    assert 'id="cAttempted">7</b>' in page.text
    assert 'id="cSuccessful">5</b>' in page.text
    assert 'id="cAiFail">2</b>' in page.text
    assert len(parsed.ids) == len(set(parsed.ids))
    assert not any(parsed.sections.values())
    assert "</script><script>alert(1)</script>" not in page.text


def test_empty_dashboard_shows_real_zeroes_and_expands_collection_inputs(isolated):
    with TestClient(app) as client:
        page = client.get("/")
    parsed = DashboardHTML(page.text)
    initial = json.loads(parsed.initial)
    assert sum(initial["counts"].values()) == 0
    assert initial["batch"]["latest_run"] is None
    assert initial["replay"]["batch"] is None
    assert 'id="rRows">0</b>' in page.text
    assert "Not enough history" in page.text
    assert parsed.sections["collection-inputs"]
    assert not parsed.sections["replay-log"]
    assert not parsed.sections["activity-heading"]
    assert not parsed.sections["attention-heading"]
