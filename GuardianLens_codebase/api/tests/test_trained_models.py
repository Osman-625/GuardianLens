"""Serving contract tests with disposable fitted models, never research artifacts."""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from api.models.domain import AssessmentRecord, SellerInput
from api.schemas import RiskBand, SignalName
from api.services.pipelines import SignalOutput
from api.services.trained_models import (
    TrainedModels,
    _shown_value,
    missing_artifacts,
    verify_train_split,
)
from api.settings import Settings
from api.tests.test_api import submit


@pytest.mark.parametrize(
    ("key", "value", "shown"),
    [
        ("seller_rating", 4.8, " (4.8)"),
        ("review_count", 1_500_000, " (1,500,000)"),
        ("account_age_days", 1, " (1 day)"),
        ("account_age_days", 400.0, " (400 days)"),
        ("price", 1250.5, " (RM 1,250.50)"),
        ("price", 300, " (RM 300)"),
        ("review_count", None, ""),
        ("review_count", float("nan"), ""),
    ],
)
def test_reasons_state_the_listings_own_value_in_plain_numbers(
    key: str, value: Any, shown: str
) -> None:
    """A reason quotes the value as a person writes it: no exponent, "1 day", thousands commas."""
    assert _shown_value(key, value) == shown


def test_trained_mode_rejects_missing_saved_models(tmp_path: Path) -> None:
    """Trained mode refuses to start on an empty run folder and names the missing files."""
    settings = Settings(  # type: ignore[call-arg]  # _env_file is a pydantic-settings init option
        _env_file=None, guardianlens_inference_mode="trained", guardianlens_model_run_dir=tmp_path
    )
    with pytest.raises(RuntimeError, match="models/T.joblib"):
        TrainedModels(settings)
    assert "fusion.joblib" in missing_artifacts(tmp_path)


def test_reference_split_mismatch_is_rejected(tmp_path: Path) -> None:
    """A training split whose hash differs from the run's recorded hash is refused."""
    (tmp_path / "train.csv").write_text("modified", encoding="utf-8")
    meta = {"config": {"paths": {"splits_dir": "."}}, "split_hashes": {"train.csv": "wrong"}}
    with pytest.raises(RuntimeError, match="does not match"):
        verify_train_split(tmp_path, meta)


@pytest.fixture
def saved_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Settings, Any]:
    """Fits small disposable models, saves them as a run folder, and returns settings for it.

    The visual engine is switched off, so the run exercises an unavailable visual signal.
    """

    def missing_visual(*args: Any, **kwargs: Any) -> None:
        """Stands in for the visual engine and reports that its assets are absent."""
        raise FileNotFoundError("Visual assets intentionally absent in this fixture.")

    monkeypatch.setattr("api.services.trained_visual.TrainedVisual", missing_visual)
    joblib = pytest.importorskip("joblib")
    np = pytest.importorskip("numpy")
    pd = pytest.importorskip("pandas")
    pytest.importorskip("sklearn")
    pytest.importorskip("xgboost")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]  # pydantic-settings init option
    sys.path.insert(0, str(settings.guardianlens_training_workspace))
    from gl.fusion import FusionModel
    from gl.models import BehaviouralSignal, TextCueSignal, VisualSignal
    from gl.visual import FEATURES
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    n = 30
    y = np.arange(n) % 2
    df = pd.DataFrame(
        {
            "title": ["Urgent phone" if v else "Used laptop" for v in y],
            "description": [
                "Deposit bank transfer today!" if v else "Original unit COD available." for v in y
            ],
            "price": np.where(y, 100.0, 1250.0),
            "category": "Electronics",
            "seller_rating": np.where(y, 2.0, 4.8),
            "account_age_days": np.where(y, 2.0, 400.0),
            "review_count": np.where(y, 0.0, 21.0),
            "active_listing_count": np.where(y, 20.0, 4.0),
        }
    )
    text = TextCueSignal().fit(df, y)
    behaviour = BehaviouralSignal()
    behaviour.params = {
        "max_depth": 2,
        "n_estimators": 5,
        "min_child_weight": 1,
        "learning_rate": 0.1,
    }
    behaviour.fit(df, y)
    visual = VisualSignal(None, FEATURES)
    X = np.random.default_rng(42).normal(size=(n, len(FEATURES)))
    visual.scaler = StandardScaler().fit(X)
    visual.model = LogisticRegression().fit(visual.scaler.transform(X), y)
    P = {"T": text.predict(df), "B": behaviour.predict(df), "V": np.where(y, 0.7, 0.2)}
    fusion = FusionModel(["V", "T", "B"], [0.1], folds=3).fit(P, y, np.arange(n))
    run = tmp_path / "fixture_run"
    (run / "models").mkdir(parents=True)
    for key, model in (("T", text), ("B", behaviour), ("V", visual)):
        joblib.dump(model, run / "models" / f"{key}.joblib")
    bands = {"low_moderate": 0.1632444545047918, "moderate_high": 0.4665169077375488}
    joblib.dump(
        {"core": ["V", "T", "B"], "full": "V+T+B", "bands": bands, "fusions": {"V+T+B": fusion}},
        run / "fusion.joblib",
    )
    latest = (
        settings.guardianlens_training_workspace / "runs/final_test_results/"
        "20261002_062026_colab_v3_noMeta/run.json"
    )
    meta = json.loads(latest.read_text(encoding="utf-8"))
    meta["run_id"] = "fixture_run"
    (run / "run.json").write_text(json.dumps(meta), encoding="utf-8")
    settings.guardianlens_model_run_dir = run
    settings.guardianlens_inference_mode = "trained"
    settings.guardianlens_database_path = Path(":memory:")
    return settings, df


def test_saved_models_drive_api_result(
    saved_run: tuple[Settings, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The API serves the saved models: real probabilities, no stub flag, the run's label."""
    settings, _ = saved_run
    monkeypatch.setattr("api.main.get_settings", lambda: settings)
    with TestClient(create_app()) as client:
        active = client.app.state.trained_models  # type: ignore[attr-defined]  # FastAPI app state
        accepted = submit(client)
        assert accepted.status_code == 202
        result = client.get(f"/api/v1/assess/{accepted.json()['assessment_id']}/result").json()
        assert result["development_stub"] is False
        assert result["model_bundle_label"] == "fixture_run"
        cards = {card["signal"]: card for card in result["signal_cards"]}
        assert "TF-IDF" in cards["textual"]["summary"]
        assert "XLM" not in cards["textual"]["summary"]
        assert cards["visual"]["available"] is False
        assert cards["visual"]["probability"] is None
        # A reason says what happened in THIS check ("raised"/"lowered"), never a general rule
        # such as "is linked with higher risk", and the behavioural ones show the seller's value.
        for card in cards.values():
            for reason in card["reasons"]:
                assert " linked with " not in reason["display_text"]
                assert reason["display_text"].endswith("the risk estimate.")
        assert any("(" in reason["display_text"] for reason in cards["behavioural"]["reasons"])
        # The seller-profile limit is always stated with the behavioural signal.
        assert "does not mean a safe listing" in cards["behavioural"]["scope_note"]
        record = AssessmentRecord(
            session_id=uuid4(),
            platform="carousell",
            title_scrubbed="Used laptop",
            title_for_inference="Used laptop",
            description_for_inference="Original unit in good condition. COD available.",
            price=1250,
            category="Electronics",
            language_detected="en",
            seller=SellerInput(
                account_age_days=400, rating=4.8, review_count=21, active_listing_count=4
            ),
            images=[],
        )
        frame = active.frame(record)
        assert cards["textual"]["probability"] == pytest.approx(active.text.predict(frame)[0])
        assert cards["behavioural"]["probability"] == pytest.approx(
            active.behaviour.predict(frame)[0]
        )
        signals = [
            SignalOutput(
                signal=SignalName(key),
                probability=card["probability"],
                available=card["available"],
                status_word="",
                summary="",
            )
            for key, card in cards.items()
        ]
        score, band = active.fuse(signals)
        assert (result["score"], result["band"]) == (score, band.value)
        assert client.get("/health").json()["stub_mode"] is False
        assert active.label == "fixture_run"
        assert active.bands["low_moderate"] == pytest.approx(0.1632444545047918)
        unknown = submit(
            client, account_age_days="", rating="", review_count="", active_listing_count=""
        )
        payload = client.get(f"/api/v1/assess/{unknown.json()['assessment_id']}/result").json()
        behavioural = next(
            card for card in payload["signal_cards"] if card["signal"] == "behavioural"
        )
        assert behavioural["available"] is True
        assert "4 seller fields are unknown" in behavioural["scope_note"]


def test_bands_use_unrounded_probability() -> None:
    """Two probabilities that round to the same score still land in different bands."""
    np = pytest.importorskip("numpy")
    runtime = TrainedModels.__new__(TrainedModels)
    runtime.lock = threading.Lock()
    runtime.bands = {"low_moderate": 0.1632444545047918, "moderate_high": 0.4665169077375488}
    runtime.fusion = {
        "full": "V+T+B",
        "fusions": {"V+T+B": SimpleNamespace(predict=lambda _: np.array([0.163]))},
    }
    outputs = [
        SignalOutput(signal=name, probability=0.2, available=True, status_word="", summary="")
        for name in SignalName
    ]
    assert runtime.fuse(outputs) == (84, RiskBand.LOW)
    runtime.fusion["fusions"]["V+T+B"].predict = lambda _: np.array([0.164])
    assert runtime.fuse(outputs) == (84, RiskBand.MODERATE)
