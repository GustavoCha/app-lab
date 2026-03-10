"""Simple JSON-based price history storage."""

from __future__ import annotations

import json
import logging
from pathlib import Path


LOGGER = logging.getLogger(__name__)


class PriceHistoryStore:
    """Persist the last N prices per product URL."""

    def __init__(self, path: Path, keep_last: int = 10) -> None:
        self.path = path
        self.keep_last = keep_last

    def load(self) -> dict[str, list[int]]:
        """Load history data from disk."""

        if not self.path.exists():
            return {}

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            LOGGER.warning("Could not read price history file %s: %s", self.path, exc)
            return {}

        history: dict[str, list[int]] = {}
        for url, prices in data.items():
            if isinstance(url, str) and isinstance(prices, list):
                cleaned_prices = [int(price) for price in prices if isinstance(price, (int, float))]
                history[url] = cleaned_prices[-self.keep_last :]
        return history

    def get_previous_min_prices(self) -> dict[str, int | None]:
        """Return the historical minimum price before the current run."""

        history = self.load()
        return {url: (min(prices) if prices else None) for url, prices in history.items()}

    def update_prices(self, current_prices: dict[str, int]) -> None:
        """Append latest prices and persist the updated file."""

        history = self.load()
        for url, price in current_prices.items():
            prices = history.setdefault(url, [])
            prices.append(price)
            history[url] = prices[-self.keep_last :]

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(history, ensure_ascii=True, indent=2, sort_keys=True),
            encoding="utf-8",
        )
