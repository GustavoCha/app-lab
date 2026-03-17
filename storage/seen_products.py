"""Simple JSON-based duplicate prevention store."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from models.product import Product


LOGGER = logging.getLogger(__name__)


class SeenProductsStore:
    """Track products that already triggered an alert."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._cache: dict[str, dict[str, object]] | None = None

    def load(self) -> dict[str, dict[str, object]]:
        """Load seen product entries from disk."""

        if self._cache is not None:
            return self._cache

        if not self.path.exists():
            self._cache = {}
            return self._cache

        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            LOGGER.warning("Could not read seen products file %s: %s", self.path, exc)
            self._cache = {}
            return self._cache

        if not isinstance(payload, dict):
            self._cache = {}
            return self._cache

        migrated: dict[str, dict[str, object]] = {}
        changed = False
        for key, value in payload.items():
            entry = value if isinstance(value, dict) else {}
            stable_key = str(entry.get("url", "")).strip() or str(key).strip()
            if not stable_key:
                continue

            normalized_entry = {
                "product_id": str(entry.get("product_id", "")).strip(),
                "name": str(entry.get("name", "")).strip(),
                "store": str(entry.get("store", "")).strip(),
                "url": stable_key,
                "price_now": entry.get("price_now"),
                "discount_percentage": entry.get("discount_percentage"),
                "alerted_at": entry.get("alerted_at"),
            }
            if stable_key != key or entry.get("url") != stable_key:
                changed = True
            migrated[stable_key] = normalized_entry

        if changed:
            self._write(migrated)
        else:
            self._cache = migrated

        return self._cache or {}

    def has_seen(self, product_url: str) -> bool:
        """Check whether a product URL already triggered an alert."""

        return product_url in self.load()

    def has_seen_product(self, product: Product) -> bool:
        """Check duplicates using the product URL and legacy product tokens."""

        seen = self.load()
        if product.url in seen:
            return True

        legacy_match = _extract_legacy_product_token(product.url)
        if not legacy_match:
            return False

        for key, value in seen.items():
            if legacy_match == _extract_legacy_product_token(key):
                return True
            if isinstance(value, dict) and legacy_match == _extract_legacy_product_token(str(value.get("url", ""))):
                return True
        return False

    def mark_as_seen(self, product: Product) -> None:
        """Persist a sent product URL."""

        seen = self.load()
        seen[product.url] = {
            "product_id": product.product_id,
            "name": product.name,
            "store": product.store,
            "url": product.url,
            "price_now": product.price_now,
            "discount_percentage": product.discount_percentage,
            "alerted_at": datetime.now(timezone.utc).isoformat(),
        }
        self._write(seen)

    def _write(self, payload: dict[str, dict[str, object]]) -> None:
        """Persist the in-memory state to disk."""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        self._cache = payload


def _extract_legacy_product_token(value: str) -> str:
    """Extract a product token from current or legacy product URLs."""

    cleaned = value.rsplit("/", 1)[-1]
    if cleaned.endswith(".html"):
        cleaned = cleaned[:-5]
    if "-" in cleaned:
        cleaned = cleaned.split("-")[-1]
    return cleaned.strip()
