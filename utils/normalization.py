"""Name normalization helpers for cross-store comparison."""

from __future__ import annotations

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


def normalize_product_name(name: str) -> str:
    """Normalize product names into a stable comparison key."""

    value = unicodedata.normalize("NFKD", name.lower())
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.replace("pulgadas", "").replace("pulgada", "").replace("''", "")
    value = re.sub(r"[^a-z0-9\s]", " ", value)
    tokens = [token for token in value.split() if token and token not in STOP_WORDS]

    deduplicated: list[str] = []
    for token in tokens:
        if not deduplicated or deduplicated[-1] != token:
            deduplicated.append(token)

    return " ".join(deduplicated).strip()
