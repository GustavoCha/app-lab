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

    def load(self) -> dict[str, dict[str, object]]:
        """Load seen product entries from disk."""

        if not self.path.exists():
            return {}

        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            LOGGER.warning("Could not read seen products file %s: %s", self.path, exc)
            return {}

        if isinstance(payload, dict):
            migrated: dict[str, dict[str, object]] = {}
            changed = False
            for key, value in payload.items():
                entry = value if isinstance(value, dict) else {}
                stable_key = str(entry.get("product_id", "")).strip()
                if not stable_key:
                    token = _extract_legacy_product_token(key)
                    stable_key = f"paris:{token}" if token else key
                    if entry:
                        entry = {**entry, "product_id": stable_key}
                    changed = True
                migrated[stable_key] = entry

            if changed:
                self.path.write_text(
                    json.dumps(migrated, ensure_ascii=True, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
            return migrated
        return {}

    def has_seen(self, product_url: str) -> bool:
        """Check whether a product URL already triggered an alert."""

        seen = self.load()
        if product_url in seen:
            return True

        legacy_match = _extract_legacy_product_token(product_url)
        if not legacy_match:
            return False

        for key, value in seen.items():
            if legacy_match == _extract_legacy_product_token(key):
                return True
            if isinstance(value, dict):
                stored_id = str(value.get("product_id", ""))
                if stored_id.endswith(legacy_match):
                    return True
        return False

    def has_seen_product(self, product: Product) -> bool:
        """Check duplicates using stable product identifiers and legacy URL entries."""

        seen = self.load()
        if product.product_id in seen or product.url in seen:
            return True

        legacy_match = _extract_legacy_product_token(product.url)
        for key, value in seen.items():
            if key == product.product_id or key == product.url:
                return True
            if legacy_match and legacy_match == _extract_legacy_product_token(key):
                return True
            if isinstance(value, dict):
                if value.get("url") == product.url or value.get("product_id") == product.product_id:
                    return True
        return False

    def mark_as_seen(self, product: Product) -> None:
        """Persist a sent product URL."""

        seen = self.load()
        seen[product.product_id] = {
            "product_id": product.product_id,
            "name": product.name,
            "store": product.store,
            "url": product.url,
            "price_now": product.price_now,
            "discount_percentage": product.discount_percentage,
            "alerted_at": datetime.now(timezone.utc).isoformat(),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(seen, ensure_ascii=True, indent=2, sort_keys=True),
            encoding="utf-8",
        )


def _extract_legacy_product_token(value: str) -> str:
    """Extract a product token from current or legacy product URLs."""

    cleaned = value.rsplit("/", 1)[-1]
    if cleaned.endswith(".html"):
        cleaned = cleaned[:-5]
    if "-" in cleaned:
        cleaned = cleaned.split("-")[-1]
    return cleaned.strip()
