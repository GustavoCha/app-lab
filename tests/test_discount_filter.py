"""Tests for filters/discount_filter.py."""

from __future__ import annotations

import pytest

from filters.discount_filter import (
    compute_discount_percentage,
    compute_deal_score,
    enrich_products,
    filter_products,
    sort_and_limit_products,
    boost_cross_store_scores,
)
from models.product import Product


def _make_product(
    product_id: str = "test:1",
    name: str = "Test Product",
    price_now: int = 50000,
    price_before: int = 100000,
    category: str = "tecnologia",
    store: str = "paris",
    normalized_name: str = "test product",
    discount_percentage: float = 0.0,
    score: float = 0.0,
) -> Product:
    """Helper to build a Product with defaults."""
    return Product(
        product_id=product_id,
        name=name,
        price_now=price_now,
        price_before=price_before,
        category=category,
        url=f"https://example.com/{product_id}",
        store=store,
        normalized_name=normalized_name,
        image_url="",
        page_available_hint=None,
        in_stock_hint=None,
        discount_percentage=discount_percentage,
        score=score,
    )


class TestComputeDiscountPercentage:
    """Test the discount percentage formula."""

    def test_50_percent_discount(self) -> None:
        result = compute_discount_percentage(50000, 100000)
        assert result == 50.0

    def test_25_percent_discount(self) -> None:
        result = compute_discount_percentage(75000, 100000)
        assert result == 25.0

    def test_zero_discount(self) -> None:
        result = compute_discount_percentage(100000, 100000)
        assert result == 0.0

    def test_no_discount_higher_current(self) -> None:
        result = compute_discount_percentage(120000, 100000)
        assert result == 0.0

    def test_zero_prices(self) -> None:
        assert compute_discount_percentage(0, 100000) == 0.0
        assert compute_discount_percentage(50000, 0) == 0.0

    def test_small_discount(self) -> None:
        result = compute_discount_percentage(95000, 100000)
        assert result == 5.0


class TestComputeDealScore:
    """Test the deal score computation."""

    def test_basic_score(self) -> None:
        score = compute_deal_score(50.0, 100000)
        assert score > 0
        import math
        assert score == pytest.approx(50.0 * math.log(100000))

    def test_zero_discount_returns_zero(self) -> None:
        assert compute_deal_score(0, 100000) == 0.0

    def test_low_price_still_scores(self) -> None:
        score = compute_deal_score(50.0, 50000)
        assert score > 0


class TestEnrichProducts:
    """Test enrich_products computation."""

    def test_enriches_discount_and_score(self) -> None:
        products = [_make_product(price_now=50000, price_before=100000)]
        enriched = enrich_products(products)
        assert len(enriched) == 1
        assert enriched[0].discount_percentage == 50.0
        assert enriched[0].score > 0


class TestBoostCrossStoreScores:
    """Test cross-store score boosting."""

    def test_single_store_no_boost(self) -> None:
        products = [
            _make_product(product_id="paris:1", store="paris", normalized_name="tv samsung"),
        ]
        # enrich first so scores are set
        enriched = enrich_products(products)
        boosted = boost_cross_store_scores(enriched)
        assert boosted[0].score == enriched[0].score  # no boost for single store

    def test_two_stores_gets_boost(self) -> None:
        products = [
            _make_product(product_id="paris:1", store="paris", price_now=50000, price_before=100000, normalized_name="tv samsung"),
            _make_product(product_id="lider:1", store="lider", price_now=55000, price_before=100000, normalized_name="tv samsung"),
        ]
        enriched = enrich_products(products)
        boosted = boost_cross_store_scores(enriched)
        # With 2 stores: multiplier = 1 + (0.15 * 1) = 1.15
        assert boosted[0].score == round(enriched[0].score * 1.15, 4)


class TestFilterProducts:
    """Test filter_products logic."""

    MIN_DISCOUNT = 20.0
    MIN_PRICE = 30000
    ALLOWED_CATEGORIES = ["tecnologia", "electrodomesticos"]

    def test_passes_valid_product(self) -> None:
        products = [
            _make_product(
                price_now=50000,
                price_before=100000,
                discount_percentage=50.0,
                category="tecnologia",
            ),
        ]
        filtered, stats = filter_products(
            products, self.MIN_DISCOUNT, self.MIN_PRICE,
            self.ALLOWED_CATEGORIES, "tv", [], [], [],
        )
        assert len(filtered) == 1
        assert stats.offers_found == 1
        assert stats.filtered_by_category == 0

    def test_filters_by_category(self) -> None:
        products = [
            _make_product(
                category="ropa",
                price_now=50000,
                price_before=100000,
                discount_percentage=50.0,
            ),
        ]
        filtered, stats = filter_products(
            products, self.MIN_DISCOUNT, self.MIN_PRICE,
            self.ALLOWED_CATEGORIES, "tv", [], [], [],
        )
        assert len(filtered) == 0
        assert stats.filtered_by_category == 1

    def test_filters_by_price(self) -> None:
        products = [
            _make_product(
                price_now=10000,
                price_before=50000,
                discount_percentage=80.0,
                category="tecnologia",
            ),
        ]
        filtered, stats = filter_products(
            products, self.MIN_DISCOUNT, self.MIN_PRICE,
            self.ALLOWED_CATEGORIES, "tv", [], [], [],
        )
        assert len(filtered) == 0
        assert stats.filtered_by_price == 1

    def test_filters_by_discount(self) -> None:
        products = [
            _make_product(
                price_now=90000,
                price_before=100000,
                discount_percentage=10.0,
                category="tecnologia",
            ),
        ]
        filtered, stats = filter_products(
            products, self.MIN_DISCOUNT, self.MIN_PRICE,
            self.ALLOWED_CATEGORIES, "tv", [], [], [],
        )
        assert len(filtered) == 0
        assert stats.filtered_by_discount == 1

    def test_filters_by_exclude_keywords(self) -> None:
        products = [
            _make_product(
                name="Samsung Galaxy con Funda Protectora",
                normalized_name="samsung galaxy con funda protectora",
                discount_percentage=50.0,
                category="tecnologia",
            ),
        ]
        filtered, stats = filter_products(
            products, self.MIN_DISCOUNT, self.MIN_PRICE,
            self.ALLOWED_CATEGORIES, "samsung galaxy", [], [], ["funda"],
        )
        assert len(filtered) == 0

    def test_filters_by_include_all_keywords(self) -> None:
        no_match = [
            _make_product(
                name="Samsung TV",
                normalized_name="samsung tv",
                discount_percentage=50.0,
                category="tecnologia",
            ),
        ]
        filtered, _ = filter_products(
            no_match, self.MIN_DISCOUNT, self.MIN_PRICE,
            self.ALLOWED_CATEGORIES, "tv samsung", [], ["samsung", "tv", "oled"], [],
        )
        assert len(filtered) == 0  # missing "oled"

        match = [
            _make_product(
                name="Samsung TV OLED",
                normalized_name="samsung tv oled",
                discount_percentage=50.0,
                category="tecnologia",
            ),
        ]
        filtered, _ = filter_products(
            match, self.MIN_DISCOUNT, self.MIN_PRICE,
            self.ALLOWED_CATEGORIES, "tv samsung", [], ["samsung", "tv", "oled"], [],
        )
        assert len(filtered) == 1

    def test_empty_products(self) -> None:
        filtered, stats = filter_products(
            [], self.MIN_DISCOUNT, self.MIN_PRICE,
            self.ALLOWED_CATEGORIES, "tv", [], [], [],
        )
        assert len(filtered) == 0
        assert stats.products_scanned == 0


class TestSortAndLimitProducts:
    """Test sort_and_limit_products function."""

    def test_sorts_by_score_descending(self) -> None:
        products = [
            _make_product(
                product_id="test:1", score=10.0, discount_percentage=50.0,
                price_before=100000, store="paris",
            ),
            _make_product(
                product_id="test:2", score=20.0, discount_percentage=60.0,
                price_before=200000, store="lider",
            ),
        ]
        result = sort_and_limit_products(products, 10)
        assert result[0].product_id == "test:2"  # highest score first

    def test_respects_limit(self) -> None:
        products = [
            _make_product(product_id=f"test:{i}", score=float(i), store="paris")
            for i in range(1, 6)
        ]
        result = sort_and_limit_products(products, 3)
        assert len(result) == 3

    def test_interleaves_stores(self) -> None:
        products = [
            _make_product(product_id="paris:1", score=100.0, store="paris"),
            _make_product(product_id="lider:2", score=90.0, store="lider"),
            _make_product(product_id="falabella:3", score=80.0, store="falabella"),
        ]
        result = sort_and_limit_products(products, 3)
        assert len(result) == 3
        # Each store should appear in the results
        stores = {p.store for p in result}
        assert stores == {"paris", "lider", "falabella"}
