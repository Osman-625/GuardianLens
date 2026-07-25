from __future__ import annotations

import re

_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
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
    compact = "".join(text.split())
    if compact:
        cjk_ratio = len(_CJK.findall(compact)) / len(compact)
        if cjk_ratio >= 0.2:
            return "unsupported"

    words = {part.lower() for part in re.findall(r"[A-Za-z]+", text)}
    has_ms = bool(words & _MALAY_MARKERS)
    has_en = bool(words & _ENGLISH_MARKERS)
    if has_ms and has_en:
        return "mixed"
    if has_ms:
        return "ms"
    return "en"
