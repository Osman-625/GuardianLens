# Language scope check for listing text. The prototype supports English, Malay, and a mix of the
# two (all written in the Latin script); text that is mostly in another script is refused. The
# English and Malay marker words only label the text as "en", "ms", or "mixed"; they do not decide
# whether it is accepted.
from __future__ import annotations

import re

# The scripts used to measure how much of a text is outside the supported language scope: Chinese
# (Han), Japanese (kana), Korean, Thai, Tamil, Devanagari, Arabic (Jawi), and Cyrillic. Only these
# are listed, not "every non-Latin letter", so a seller's decorative Unicode lettering is not
# mistaken for another language.
_OTHER_SCRIPT = re.compile(
    "[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"  # Han
    "\u3040-\u30ff"  # Hiragana and Katakana
    "\u1100-\u11ff\uac00-\ud7af"  # Hangul
    "\u0e00-\u0e7f"  # Thai
    "\u0b80-\u0bff"  # Tamil
    "\u0900-\u097f"  # Devanagari
    "\u0600-\u06ff\u0750-\u077f"  # Arabic
    "\u0400-\u04ff]"  # Cyrillic
)
# Common words that mark a text as Malay or as English ("original" appears in both).
_MALAY_MARKERS = {
    "barang",
    "murah",
    "boleh",
    "saya",
    "jual",
    "harga",
    "nego",
    "cod",
    "pos",
    "keadaan",
    "original",
    "baru",
    "terpakai",
}
_ENGLISH_MARKERS = {
    "sale",
    "price",
    "condition",
    "original",
    "used",
    "new",
    "delivery",
    "seller",
    "warranty",
    "available",
}


def detect_supported_language(text: str) -> str:
    """Labels a listing's language: "unsupported", "mixed", "ms", or "en".

    "unsupported" means at least a fifth of the non-space characters are in another script (see
    _OTHER_SCRIPT). Otherwise the
    marker words decide: both kinds give "mixed", only Malay gives "ms", and anything else "en".
    """
    compact = "".join(text.split())
    if compact:
        other_script_ratio = len(_OTHER_SCRIPT.findall(compact)) / len(compact)
        if other_script_ratio >= 0.2:
            return "unsupported"

    words = {part.lower() for part in re.findall(r"[A-Za-z]+", text)}
    has_ms = bool(words & _MALAY_MARKERS)
    has_en = bool(words & _ENGLISH_MARKERS)
    if has_ms and has_en:
        return "mixed"
    if has_ms:
        return "ms"
    return "en"
