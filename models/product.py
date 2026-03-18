"""Shared product schema used by every scraper."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace


@dataclass(slots=True)
class Product:
    """Normalized product data for downstream processing."""

    product_id: str
    name: str
    price_now: int
    price_before: int
    category: str
    url: str
    store: str
    normalized_name: str
    image_url: str = ""
    page_available_hint: bool | None = None
    in_stock_hint: bool | None = None
    discount_percentage: float = 0.0
    score: float = 0.0

    def to_dict(self) -> dict[str, object]:
        """Convert model into a plain dictionary."""

        return asdict(self)

    def copy_with(self, **changes: object) -> "Product":
        """Create a modified copy of the product."""

        return replace(self, **changes)
