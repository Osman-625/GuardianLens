# Language scope tests: the prototype supports English and Malay (Latin script). Text that is mostly
# in another script is refused, whichever script it is; ordinary and decorated Latin text is not.
from __future__ import annotations

import pytest

from api.services.language import detect_supported_language


@pytest.mark.parametrize(
    "text",
    [
        "出售手机 全新手机，价格便宜，请联系卖家",  # Chinese
        "புதிய தொலைபேசி விற்பனைக்கு உள்ளது நல்ல நிலை",  # Tamil
        "ขายโทรศัพท์มือถือใหม่ สภาพดี ราคาถูก",  # Thai
        "新品スマートフォン 売ります 状態良好です",  # Japanese (kana and kanji)
        "새 스마트폰 판매합니다 상태 좋음",  # Korean
        "بيع هاتف جديد بحالة ممتازة وبسعر مناسب",  # Arabic
        "Продам новый телефон в отличном состоянии",  # Cyrillic
    ],
)
def test_text_mostly_in_another_script_is_unsupported(text: str) -> None:
    """A listing written mostly in Chinese, Tamil, Thai, Japanese, Korean, Arabic or Cyrillic."""
    assert detect_supported_language(text) == "unsupported"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Used laptop in good condition, charger included", "en"),
        ("Barang murah, boleh nego, saya jual cepat", "ms"),
        ("Phone original, harga murah, delivery available", "mixed"),
        ("Cafe table, naive design, resume stand (café, naïve, résumé)", "en"),
        ("🔥🔥 𝗜𝗣𝗛𝗢𝗡𝗘 𝟭𝟰 𝗣𝗿𝗼 𝗠𝗮𝘅, used, price RM 3,200 🔥🔥", "en"),  # decorative lettering
        ("iPhone 14 Pro 256GB 九成新", "en"),  # a few Chinese words in an English listing
        ("", "en"),
    ],
)
def test_latin_text_is_supported_and_labelled(text: str, expected: str) -> None:
    """English, Malay, mixed, accented, decorated, and mostly-Latin text keeps being accepted."""
    assert detect_supported_language(text) == expected
