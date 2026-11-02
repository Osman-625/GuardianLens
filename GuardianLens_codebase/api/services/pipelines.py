# The development stubs for the three signals (visual, textual, behavioural), plus the common
# output type the trained models also return. The stubs are simple rules that exercise the
# interface; their scores are never model results and never research evidence.
from __future__ import annotations

import time
from dataclasses import dataclass, field

from api.models.domain import ImageInput, SellerInput
from api.schemas import SignalName, SignalReason


@dataclass(slots=True)
class SignalOutput:
    """What one signal reports: a probability (None if unavailable), wording, and reasons."""

    signal: SignalName
    probability: float | None
    available: bool
    status_word: str
    summary: str
    reasons: list[SignalReason] = field(default_factory=list)
    scope_note: str | None = None
    latency_ms: int = 0


def _bounded(value: float) -> float:
    """Keeps a stub probability between 0.01 and 0.99, so a stub never claims certainty."""
    return min(0.99, max(0.01, value))


def run_visual_stub(images: list[ImageInput]) -> SignalOutput:
    """Development-only visual contract stub, never research evidence."""

    started = time.perf_counter()
    duplicate_count = len(images) - len({item.sha256 for item in images})
    low_res = sum(1 for item in images if min(item.width_px, item.height_px) < 400)
    probability = _bounded(0.18 + duplicate_count * 0.32 + low_res * 0.12)
    reasons: list[SignalReason] = []
    if duplicate_count:
        reasons.append(
            SignalReason(
                feature_key="dev_duplicate_upload",
                direction="raises",
                display_text="The same uploaded image appears more than once in this check.",
                rank=1,
            )
        )
    if low_res:
        reasons.append(
            SignalReason(
                feature_key="dev_low_resolution",
                direction="raises",
                display_text="One or more photos have limited detail because of low resolution.",
                rank=len(reasons) + 1,
            )
        )
    if not reasons:
        reasons.append(
            SignalReason(
                feature_key="dev_image_baseline",
                direction="lowers",
                display_text="No basic photo-quality warning was found in test mode.",
                rank=1,
            )
        )
    return SignalOutput(
        signal=SignalName.VISUAL,
        probability=probability,
        available=True,
        status_word="development check",
        summary="Basic photo checks completed in test mode.",
        reasons=reasons,
        scope_note=(
            "The real system compares photos only with a fixed set of reference images. "
            "Test mode does no matching."
        ),
        latency_ms=round((time.perf_counter() - started) * 1000),
    )


def run_textual_stub(title: str, description: str) -> SignalOutput:
    """Development-only text contract stub, never research evidence."""

    started = time.perf_counter()
    text = f"{title} {description}".lower()
    warning_phrases = {
        "urgent": 0.12,
        "deposit": 0.16,
        "bank transfer": 0.18,
        "whatsapp only": 0.16,
        "outside platform": 0.22,
        "bayar dulu": 0.18,
        "cepat": 0.08,
        "pm tepi": 0.14,
        "no refund": 0.10,
    }
    matched = [(phrase, weight) for phrase, weight in warning_phrases.items() if phrase in text]
    probability = _bounded(0.20 + sum(weight for _, weight in matched))
    reasons: list[SignalReason] = []
    ranked = sorted(matched, key=lambda item: item[1], reverse=True)[:3]
    for rank, (phrase, _) in enumerate(ranked, 1):
        reasons.append(
            SignalReason(
                feature_key=f"dev_phrase_{phrase.replace(' ', '_')}",
                direction="raises",
                display_text=(f'Test mode found the phrase "{phrase}" in the listing text.'),
                rank=rank,
            )
        )
    if not reasons:
        reasons.append(
            SignalReason(
                feature_key="dev_text_baseline",
                direction="lowers",
                display_text="No phrase from the small test-mode warning list was found.",
                rank=1,
            )
        )
    return SignalOutput(
        signal=SignalName.TEXTUAL,
        probability=probability,
        available=True,
        status_word="development check",
        summary=("Basic wording checks completed in test mode."),
        reasons=reasons,
        latency_ms=round((time.perf_counter() - started) * 1000),
    )


def run_behavioural_stub(seller: SellerInput, price: float) -> SignalOutput:
    """Development-only behavioural contract stub, never research evidence."""

    started = time.perf_counter()
    provided = [
        seller.account_age_days is not None,
        seller.rating is not None,
        seller.review_count is not None,
        seller.active_listing_count is not None,
    ]
    if not any(provided):
        return SignalOutput(
            signal=SignalName.BEHAVIOURAL,
            probability=None,
            available=False,
            status_word="limited information",
            summary="Not enough information. Treated as unknown, not as suspicious.",
            latency_ms=round((time.perf_counter() - started) * 1000),
        )

    score = 0.22
    reasons: list[SignalReason] = []
    if seller.account_age_days is not None and seller.account_age_days < 30:
        score += 0.26
        reasons.append(
            SignalReason(
                feature_key="dev_new_account",
                direction="raises",
                display_text="The visible account age is under 30 days.",
                rank=len(reasons) + 1,
            )
        )
    if seller.rating is not None and seller.rating >= 4.5 and (seller.review_count or 0) >= 10:
        score -= 0.12
        reasons.append(
            SignalReason(
                feature_key="dev_rating_history",
                direction="lowers",
                display_text="The visible rating is high and is supported by at least 10 reviews.",
                rank=len(reasons) + 1,
            )
        )
    if seller.active_listing_count is not None and seller.active_listing_count > 80:
        score += 0.16
        reasons.append(
            SignalReason(
                feature_key="dev_many_active_listings",
                direction="raises",
                display_text=(
                    "The visible account has an unusually large number of active listings."
                ),
                rank=len(reasons) + 1,
            )
        )
    if price == 0:
        score += 0.08
        reasons.append(
            SignalReason(
                feature_key="dev_zero_price",
                direction="raises",
                display_text=(
                    "The entered listing price is zero, so the price signal is less useful."
                ),
                rank=len(reasons) + 1,
            )
        )
    if not reasons:
        reasons.append(
            SignalReason(
                feature_key="dev_behavioural_baseline",
                direction="lowers",
                display_text="No basic seller-field warning was found in test mode.",
                rank=1,
            )
        )
    missing = sum(1 for value in provided if not value)
    summary = "Basic visible seller fields were checked."
    if missing:
        summary += f" {missing} optional field(s) were unavailable and treated as unknown."
    return SignalOutput(
        signal=SignalName.BEHAVIOURAL,
        probability=_bounded(score),
        available=True,
        status_word="development check",
        summary=summary,
        reasons=reasons[:3],
        latency_ms=round((time.perf_counter() - started) * 1000),
    )
