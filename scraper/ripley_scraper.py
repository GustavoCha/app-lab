"""Ripley.cl scraper using Next.js SSR payloads."""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

from config.config import AppConfig
from models.product import Product
from utils.normalization import fix_text_encoding, normalize_product_name


LOGGER = logging.getLogger(__name__)


class RipleyScraper:
    """Scrape Ripley search results from embedded Next.js data."""

    STORE_NAME = "ripley"
    BASE_URL = "https://simple.ripley.cl"
    USER_AGENT = "Mozilla/5.0"

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def _scrape_search_query(self, query: str) -> list[Product]:
        """Scrape products for one Ripley free-text search query."""

        products: dict[str, Product] = {}
        for page in range(1, self.config.pages_per_category + 1):
            url = self._build_search_url(query, page)
            html = self._fetch(url)
            if not html:
                continue

            page_products = self._parse_page_products(html, url)
            if not page_products:
                continue

            page_new = 0
            for product in page_products:
                if product.product_id not in products:
                    products[product.product_id] = product
                    page_new += 1

            LOGGER.info(
                "Ripley query '%s': page %s scanned, %s products found",
                query,
                page,
                len(page_products),
            )

            if page_new == 0:
                break

        LOGGER.info("Ripley query '%s': scraped %s products", query, len(products))
        return list(products.values())

    def get_product_page_state(self, url: str) -> tuple[bool, bool]:
        """Return PDP availability and stock for a Ripley product."""

        html = self._fetch(url)
        if not html:
            return False, False

        next_payload = self._extract_next_data(html)
        if not next_payload:
            return False, False

        product_data = (
            next_payload.get("props", {})
            .get("pageProps", {})
            .get("product", {})
        )
        if not isinstance(product_data, dict) or not product_data:
            return False, False

        stock = product_data.get("stock", {})
        if isinstance(stock, dict):
            available_quantity = stock.get("quantity", 0)
            if isinstance(available_quantity, (int, float)) and available_quantity > 0:
                return True, True
            return bool(stock.get("available", False)), False

        if isinstance(stock, (int, float)) and stock > 0:
            return True, True

        return True, False

    def _parse_page_products(self, html: str, page_url: str) -> list[Product]:
        """Extract products from Ripley page using Next.js data or HTML parsing."""

        next_payload = self._extract_next_data(html)
        if next_payload:
            page_props = next_payload.get("props", {}).get("pageProps", {})
            results = page_props.get("results", [])
            if isinstance(results, list) and results:
                return [
                    product
                    for item in results
                    if isinstance(item, dict) and (product := self._product_from_search_item(item))
                ]

            catalog = page_props.get("catalog", {})
            items = catalog.get("items", [])
            if isinstance(items, list) and items:
                return [
                    product
                    for item in items
                    if isinstance(item, dict) and (product := self._product_from_search_item(item))
                ]

        return self._parse_html_products(html, page_url)

    def _product_from_search_item(self, item: dict[str, Any]) -> Product | None:
        """Build a normalized Product from a Ripley search result item."""

        name = fix_text_encoding(
            str(item.get("name") or item.get("displayName") or "").strip()
        )
        if not name:
            return None

        url = str(item.get("url") or item.get("canonicalUrl") or "").strip()
        full_url = urljoin(self.BASE_URL, url) if url else ""
        if not full_url:
            return None

        product_id = str(item.get("id") or item.get("skuId") or item.get("productId") or full_url).strip()

        prices = item.get("prices", {}) if isinstance(item.get("prices"), dict) else {}
        price_now = self._parse_price(prices.get("offerPrice") or prices.get("salePrice") or prices.get("price"))
        price_before = self._parse_price(prices.get("listPrice") or prices.get("regularPrice") or prices.get("oldPrice"))

        image_url = ""
        images = item.get("images", [])
        if isinstance(images, list) and images:
            first = images[0]
            if isinstance(first, dict):
                image_url = str(first.get("url") or first.get("src") or "").strip()
            elif isinstance(first, str):
                image_url = first.strip()
        if not image_url:
            image_url = str(item.get("image") or item.get("imageUrl") or "").strip()

        category = self._extract_category(item.get("category") or item.get("department"))

        return self._build_product(
            product_id=f"{self.STORE_NAME}:{product_id}",
            name=name,
            price_now=price_now,
            price_before=price_before,
            category=category,
            url=full_url,
            image_url=image_url,
        )

    def _build_search_url(self, query: str, page: int) -> str:
        """Build a Ripley search URL."""

        return f"{self.BASE_URL}/search?q={quote_plus(query)}&page={page}"

    def _fetch(self, url: str) -> str | None:
        """Fetch one Ripley page with retry logic."""

        for attempt in range(1, self.config.request_retries + 1):
            try:
                response = requests.get(
                    url,
                    timeout=self.config.request_timeout,
                    headers={"User-Agent": self.USER_AGENT},
                )
                response.raise_for_status()
                return response.text
            except requests.RequestException as exc:
                LOGGER.warning(
                    "Ripley fetch failed (%s/%s) for %s: %s",
                    attempt,
                    self.config.request_retries,
                    url,
                    exc,
                )
        return None

    @staticmethod
    def _extract_next_data(html: str) -> dict[str, Any]:
        """Extract __NEXT_DATA__ from a Ripley page."""

        soup = BeautifulSoup(html, "html.parser")
        script = soup.find("script", id="__NEXT_DATA__")
        if not script:
            return {}
        try:
            payload = json.loads(script.get_text())
        except ValueError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _parse_html_products(self, html: str, page_url: str) -> list[Product]:
        """Fallback: parse product cards from HTML when Next.js data is unavailable."""

        soup = BeautifulSoup(html, "html.parser")
        products: dict[str, Product] = {}

        selectors = [
            "[data-product-id]",
            "[data-testid='product-card']",
            ".product-card",
            ".product-item",
            ".catalog-product-item",
        ]
        for selector in selectors:
            for node in soup.select(selector):
                product = self._product_from_html_node(node, page_url)
                if product:
                    products[product.product_id] = product
            if products:
                break

        return list(products.values())

    def _product_from_html_node(self, node: Any, page_url: str) -> Product | None:
        """Build a product from a parsed HTML card."""

        name_node = node.select_one("a[title], .product-name, .name, h2, h3, [data-name]")
        link_node = node.select_one("a[href]")
        price_now_node = node.select_one("[data-price], .sale-price, .price, .offer-price")
        price_before_node = node.select_one(".list-price, .old-price, .regular-price, [data-list-price]")
        image_node = node.select_one("img[src], img[data-src]")

        name = ""
        if name_node:
            name = name_node.get("title") or name_node.get("data-name") or name_node.get_text(" ", strip=True)
        name = fix_text_encoding(name.strip())
        if not name:
            return None

        url = urljoin(page_url, link_node.get("href", "")) if link_node else ""
        if not url:
            return None

        product_id = str(node.get("data-product-id") or node.get("id") or url).strip()

        price_now = self._parse_price(
            (price_now_node.get("data-price") if price_now_node else "")
            or (price_now_node.get_text(" ", strip=True) if price_now_node else "")
        )
        price_before = self._parse_price(
            (price_before_node.get("data-list-price") if price_before_node else "")
            or (price_before_node.get_text(" ", strip=True) if price_before_node else "")
        )

        image_url = ""
        if image_node:
            image_url = str(image_node.get("src") or image_node.get("data-src") or "").strip()

        return self._build_product(
            product_id=f"{self.STORE_NAME}:{product_id}",
            name=name,
            price_now=price_now,
            price_before=price_before,
            category="custom",
            url=url,
            image_url=image_url,
        )

    @staticmethod
    def _extract_category(value: object) -> str:
        """Map Ripley category text into one of the canonical groups."""

        haystack = fix_text_encoding(str(value or "")).strip().lower()
        if any(term in haystack for term in ["videojuego", "tecno", "telefon", "audio", "comput"]):
            return "tecnologia"
        if any(term in haystack for term in ["electro", "linea blanca", "climatiz"]):
            return "electrodomesticos"
        if any(term in haystack for term in ["bicic", "deporte"]):
            return "bicicletas"
        if any(term in haystack for term in ["hogar", "cocina", "colchon", "mueble", "menaje"]):
            return "menaje"
        if any(term in haystack for term in ["vestuario", "moda", "ropa", "calzado"]):
            return "ropa"
        return "custom"

    @staticmethod
    def _parse_price(value: object) -> int:
        """Normalize Ripley price formats into integer CLP values."""

        if value is None:
            return 0
        if isinstance(value, (int, float)):
            return int(value)
        digits = re.sub(r"[^\d]", "", str(value))
        return int(digits) if digits else 0

    def _build_product(
        self,
        product_id: str,
        name: str,
        price_now: int,
        price_before: int,
        category: str,
        url: str,
        image_url: str = "",
    ) -> Product | None:
        """Validate and build a normalized Product."""

        cleaned_name = fix_text_encoding(name).strip()
        cleaned_url = url.strip()
        cleaned_image_url = image_url.strip()
        resolved_category = category.strip().lower() if category else "sin-categoria"

        if not cleaned_name or not cleaned_url:
            return None
        if price_now <= 0 or price_before <= 0:
            return None
        if price_now >= price_before:
            return None

        return Product(
            product_id=product_id or f"{self.STORE_NAME}:{cleaned_url}",
            name=cleaned_name,
            price_now=price_now,
            price_before=price_before,
            category=resolved_category,
            url=cleaned_url,
            store=self.STORE_NAME,
            normalized_name=normalize_product_name(cleaned_name),
            image_url=cleaned_image_url,
            page_available_hint=None,
            in_stock_hint=None,
        )
