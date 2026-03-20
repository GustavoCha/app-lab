"""Filtering, scoring, and selection logic for deals."""

from __future__ import annotations

import math
from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass
from typing import Iterable

from models.product import Product
from utils.normalization import normalize_keywords, normalize_product_name


ACCESSORY_TERMS = {
    "accesorio",
    "adaptador",
    "audifono",
    "bolso",
    "camara",
    "cable",
    "carcasa",
    "case",
    "control",
    "cover",
    "cuna",
    "dock",
    "estacion",
    "estuche",
    "funda",
    "grip",
    "headset",
    "joystick",
    "joy con",
    "lamina",
    "mica",
    "microsd",
    "memoria",
    "protector",
    "repuesto",
    "soporte",
    "stand",
    "tarjeta",
    "volante",
}
GAME_TERMS = {
    "juego",
    "game",
    "mario kart",
    "pokemon",
    "zelda",
    "fifa",
    "fc26",
    "minecraft",
    "metroid",
    "party",
    "sonic",
}
CORE_PRODUCT_TERMS = {
    "bundle",
    "consola",
    "pack",
    "pre cargada",
    "pre cargado",
}
CONSOLE_QUERY_TERMS = {
    "nintendo switch",
    "switch 2",
    "playstation",
    "ps5",
    "ps4",
    "xbox",
}
KEYWORD_TOKEN_EQUIVALENTS = {
    "televisor": {"televisor", "tv"},
    "tv": {"televisor", "tv"},
}


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
    search_query: str,
    include_keywords_any: list[str],
    include_keywords_all: list[str],
    exclude_keywords: list[str],
) -> tuple[list[Product], FilterStats]:
    """Keep only products that match category, price, discount, and keywords."""

    allowed = {category.strip().lower() for category in allowed_categories}
    normalized_query = normalize_product_name(search_query)
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
        if _looks_like_accessory_or_related(product, normalized_query):
            stats.filtered_by_keywords += 1
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


def _looks_like_accessory_or_related(product: Product, normalized_query: str) -> bool:
    """Exclude obvious accessories/games unless the query explicitly asks for them."""

    if not normalized_query:
        return False

    haystack = product.normalized_name
    if _query_targets_console_hardware(normalized_query):
        return _is_non_console_result_for_console_query(haystack, normalized_query)

    query_wants_accessory = any(term in normalized_query for term in ACCESSORY_TERMS)
    query_wants_game = any(term in normalized_query for term in GAME_TERMS)

    if query_wants_accessory or query_wants_game:
        return False

    is_accessory = any(term in haystack for term in ACCESSORY_TERMS)
    is_game = any(term in haystack for term in GAME_TERMS)
    looks_like_core_product = any(term in haystack for term in CORE_PRODUCT_TERMS)

    if looks_like_core_product:
        return False

    return is_accessory or is_game


def _query_targets_console_hardware(normalized_query: str) -> bool:
    """Detect searches that are clearly asking for a console rather than related products."""

    if any(term in normalized_query for term in GAME_TERMS):
        return False
    return any(term in normalized_query for term in CONSOLE_QUERY_TERMS)


def _is_non_console_result_for_console_query(haystack: str, normalized_query: str) -> bool:
    """Keep only console hardware, bundles, or exact console matches for console queries."""

    model_matches_query = normalized_query in haystack or "switch 2" in haystack
    has_query_phrase = normalized_query in haystack
    looks_like_console = any(term in haystack for term in CORE_PRODUCT_TERMS)
    is_accessory = any(term in haystack for term in ACCESSORY_TERMS)
    is_game = any(term in haystack for term in GAME_TERMS)

    if looks_like_console and model_matches_query:
        return False
    if has_query_phrase and not is_game and not is_accessory:
        return False
    if is_accessory or is_game:
        return True
    return True


def _keyword_matches(haystack: str, keyword: str) -> bool:
    """Match normalized words or phrases against the normalized product name."""

    normalized = " ".join(keyword.strip().split())
    if not normalized or not haystack:
        return False

    haystack_tokens = haystack.split()
    keyword_tokens = normalized.split()
    if not keyword_tokens:
        return False

    if len(keyword_tokens) == 1:
        token = keyword_tokens[0]
        equivalents = KEYWORD_TOKEN_EQUIVALENTS.get(token, {token})
        return any(haystack_token in equivalents for haystack_token in haystack_tokens)

    normalized_haystack = " ".join(haystack_tokens)
    normalized_keyword = " ".join(keyword_tokens)
    if normalized_keyword in normalized_haystack:
        return True

    for start in range(0, len(haystack_tokens) - len(keyword_tokens) + 1):
        window = haystack_tokens[start:start + len(keyword_tokens)]
        if all(
            window_token in KEYWORD_TOKEN_EQUIVALENTS.get(keyword_token, {keyword_token})
            for window_token, keyword_token in zip(window, keyword_tokens)
        ):
            return True
    return False


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

    ranked = sorted(
        rescored,
        key=lambda item: (item.score, item.discount_percentage, item.price_before),
        reverse=True,
    )
    return _interleave_by_store(ranked, limit)


def _interleave_by_store(products: list[Product], limit: int) -> list[Product]:
    """Mix stores fairly so one source does not consume every top slot."""

    buckets: dict[str, deque[Product]] = defaultdict(deque)
    store_order: list[str] = []
    for product in products:
        if product.store not in buckets:
            store_order.append(product.store)
        buckets[product.store].append(product)

    mixed: list[Product] = []
    while store_order and len(mixed) < limit:
        next_round: list[str] = []
        for store in store_order:
            bucket = buckets[store]
            if not bucket:
                continue
            mixed.append(bucket.popleft())
            if bucket:
                next_round.append(store)
            if len(mixed) >= limit:
                break
        store_order = next_round

    return mixed
