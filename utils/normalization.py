"""Name normalization helpers for cross-store comparison."""

from __future__ import annotations

import html
import re
import unicodedata


STOP_WORDS = {
    "nuevo",
    "nueva",
    "oferta",
    "promocion",
    "promo",
    "liquidacion",
}

MOJIBAKE_MARKERS = ("Ã", "Â", "Ð", "\ufffd")


def fix_text_encoding(value: str) -> str:
    """Repair common latin1/utf-8 mojibake found in scraped titles."""

    text = html.unescape((value or "").strip()).replace("\xa0", " ")
    if not text:
        return ""

    for _ in range(2):
        if not any(marker in text for marker in MOJIBAKE_MARKERS):
            break
        try:
            repaired = text.encode("latin1").decode("utf-8")
        except UnicodeError:
            break
        if repaired == text:
            break
        text = repaired

    return " ".join(text.split())


def normalize_product_name(name: str) -> str:
    """Normalize product names into a stable comparison key."""

    value = fix_text_encoding(name).lower()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.replace("pulgadas", "").replace("pulgada", "").replace("''", "")
    value = re.sub(r"[^a-z0-9\s]", " ", value)
    tokens = [token for token in value.split() if token and token not in STOP_WORDS]

    deduplicated: list[str] = []
    for token in tokens:
        if not deduplicated or deduplicated[-1] != token:
            deduplicated.append(token)

    return " ".join(deduplicated).strip()


def normalize_keywords(values: list[str]) -> list[str]:
    """Normalize keyword lists with the same rules used for product names."""

    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        candidate = normalize_product_name(value)
        if candidate and candidate not in seen:
            seen.add(candidate)
            normalized.append(candidate)
    return normalized
