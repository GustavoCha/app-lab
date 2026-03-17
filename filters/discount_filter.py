"""Filtering, scoring, and selection logic for deals."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Iterable

from models.product import Product
from utils.normalization import normalize_keywords


@dataclass(slots=True)
class FilterStats:
    """Counters describing why products were excluded."""

    products_scanned: int = 0
    offers_found: int = 0
    filtered_by_category: int = 0
    filtered_by_price: int = 0
    filtered_by_discount: int = 0
    filtered_by_keywords: int = 0
    filtered_by_invalid_price: int = 0

    def to_dict(self) -> dict[str, int]:
        """Expose counters as a plain dictionary."""

        return {key: int(value) for key, value in asdict(self).items()}


def compute_discount_percentage(price_now: int, price_before: int) -> float:
    """Compute discount percentage using the requested formula."""

    if price_now <= 0 or price_before <= 0 or price_now >= price_before:
        return 0.0
    return 100 - ((price_now / price_before) * 100)


def compute_deal_score(discount_percentage: float, price_before: int) -> float:
    """Compute a score that prioritizes stronger deals on higher ticket items."""

    if discount_percentage <= 0 or price_before <= 1:
        return 0.0
    return discount_percentage * math.log(price_before)


def enrich_products(products: Iterable[Product]) -> list[Product]:
    """Attach discount and score values to products."""

    enriched: list[Product] = []
    for product in products:
        discount = compute_discount_percentage(product.price_now, product.price_before)
        score = compute_deal_score(discount, product.price_before)
        enriched.append(
            product.copy_with(
                discount_percentage=round(discount, 2),
                score=round(score, 4),
            )
        )
    return enriched


def boost_cross_store_scores(products: Iterable[Product]) -> list[Product]:
    """Increase score when the same normalized product appears across stores."""

    products_list = list(products)
    store_counts_by_name: dict[str, set[str]] = {}
    for product in products_list:
        store_counts_by_name.setdefault(product.normalized_name, set()).add(product.store)

    boosted: list[Product] = []
    for product in products_list:
        distinct_store_count = len(store_counts_by_name.get(product.normalized_name, set()))
        multiplier = 1 + (0.15 * max(0, distinct_store_count - 1))
        boosted.append(product.copy_with(score=round(product.score * multiplier, 4)))
    return boosted


def filter_products(
    products: Iterable[Product],
    min_discount: float,
    min_price: int,
    allowed_categories: list[str],
    include_keywords_any: list[str],
    include_keywords_all: list[str],
    exclude_keywords: list[str],
) -> tuple[list[Product], FilterStats]:
    """Keep only products that match category, price, discount, and keywords."""

    allowed = {category.strip().lower() for category in allowed_categories}
    include_any_terms = normalize_keywords(include_keywords_any)
    include_all_terms = normalize_keywords(include_keywords_all)
    exclude_terms = normalize_keywords(exclude_keywords)
    filtered: list[Product] = []
    stats = FilterStats()

    for product in products:
        stats.products_scanned += 1

        if product.category.lower() not in allowed:
            stats.filtered_by_category += 1
            continue
        if product.price_before <= 0 or product.price_now <= 0:
            stats.filtered_by_invalid_price += 1
            continue
        if product.price_now < min_price:
            stats.filtered_by_price += 1
            continue
        if product.discount_percentage < min_discount:
            stats.filtered_by_discount += 1
            continue
        if not _matches_keyword_rules(product, include_any_terms, include_all_terms, exclude_terms):
            stats.filtered_by_keywords += 1
            continue

        filtered.append(product)

    stats.offers_found = len(filtered)
    return filtered, stats


def _matches_keyword_rules(
    product: Product,
    include_keywords_any: list[str],
    include_keywords_all: list[str],
    exclude_keywords: list[str],
) -> bool:
    """Apply user-controlled include/exclude keyword rules."""

    haystack = product.normalized_name

    if include_keywords_all and not all(_keyword_matches(haystack, keyword) for keyword in include_keywords_all):
        return False
    if include_keywords_any and not any(_keyword_matches(haystack, keyword) for keyword in include_keywords_any):
        return False
    if exclude_keywords and any(_keyword_matches(haystack, keyword) for keyword in exclude_keywords):
        return False
    return True


def _keyword_matches(haystack: str, keyword: str) -> bool:
    """Match normalized words or phrases against the normalized product name."""

    normalized = " ".join(keyword.strip().split())
    if not normalized:
        return False
    return normalized in haystack


def sort_and_limit_products(products: Iterable[Product], limit: int) -> list[Product]:
    """Order products by score and keep the highest-value alerts."""

    products_list = list(products)
    same_name_frequency = Counter(product.normalized_name for product in products_list)

    rescored = [
        product.copy_with(
            score=round(product.score + (same_name_frequency[product.normalized_name] - 1) * 5, 4)
        )
        for product in products_list
    ]

    return sorted(
        rescored,
        key=lambda item: (item.score, item.discount_percentage, item.price_before),
        reverse=True,
    )[:limit]
