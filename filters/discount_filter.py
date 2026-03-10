"""Filtering, scoring, and selection logic for deals."""

from __future__ import annotations

import math
from collections import Counter
from typing import Iterable

from models.product import Product


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
    allowed_categories: list[str],
    historical_min_prices: dict[str, int | None],
    include_keywords_any: list[str],
    include_keywords_all: list[str],
    exclude_keywords: list[str],
) -> list[Product]:
    """Keep only products that match category and real-deal criteria."""

    allowed = {category.strip().lower() for category in allowed_categories}
    include_any_terms = [term.strip().lower() for term in include_keywords_any if term.strip()]
    include_all_terms = [term.strip().lower() for term in include_keywords_all if term.strip()]
    exclude_terms = [term.strip().lower() for term in exclude_keywords if term.strip()]
    filtered: list[Product] = []

    for product in products:
        if product.category.lower() not in allowed:
            continue
        if product.price_before <= 0 or product.price_now <= 0:
            continue

        historical_min = historical_min_prices.get(product.product_id)
        is_new_historical_low = historical_min is None or product.price_now < historical_min
        meets_discount = product.discount_percentage >= min_discount

        if not _matches_keyword_rules(product, include_any_terms, include_all_terms, exclude_terms):
            continue

        if is_new_historical_low or meets_discount:
            filtered.append(product)

    return filtered


def _matches_keyword_rules(
    product: Product,
    include_keywords_any: list[str],
    include_keywords_all: list[str],
    exclude_keywords: list[str],
) -> bool:
    """Apply user-controlled include/exclude keyword rules."""

    haystack = f"{product.name} {product.normalized_name} {product.category}".lower()

    if include_keywords_any and not any(keyword in haystack for keyword in include_keywords_any):
        return False
    if include_keywords_all and not all(keyword in haystack for keyword in include_keywords_all):
        return False
    if exclude_keywords and any(keyword in haystack for keyword in exclude_keywords):
        return False
    return True


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
