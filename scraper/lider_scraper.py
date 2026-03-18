"""Lider.cl scraper using Next.js SSR payloads."""

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


class LiderScraper:
    """Scrape Lider search results from embedded Next.js data."""

    STORE_NAME = "lider"
    BASE_URL = "https://www.lider.cl"
    USER_AGENT = "Mozilla/5.0"

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def _scrape_search_query(self, query: str) -> list[Product]:
        """Scrape products for one Lider free-text search query."""

        html = self._fetch(self._build_search_url(query))
        if not html:
            return []

        next_payload = self._extract_next_data(html)
        if not next_payload:
            return []

        search_result = (
            next_payload.get("props", {})
            .get("pageProps", {})
            .get("initialData", {})
            .get("searchResult", {})
        )
        item_stacks = search_result.get("itemStacks", [])
        if not isinstance(item_stacks, list):
            return []

        products: dict[str, Product] = {}
        for stack in item_stacks:
            if not isinstance(stack, dict):
                continue
            for item in stack.get("items", []):
                if not isinstance(item, dict):
                    continue
                product = self._product_from_search_item(item)
                if product:
                    products[product.url] = product

        LOGGER.info("Lider query '%s': scraped %s products", query, len(products))
        return list(products.values())

    def get_product_page_state(self, url: str) -> tuple[bool, bool]:
        """Return page availability and stock status from a Lider PDP."""

        html = self._fetch(url)
        if not html:
            return False, False

        next_payload = self._extract_next_data(html)
        if not next_payload:
            return False, False

        product = (
            next_payload.get("props", {})
            .get("pageProps", {})
            .get("initialData", {})
            .get("data", {})
            .get("product", {})
        )
        if not isinstance(product, dict):
            return False, False

        availability = product.get("availabilityStatusV2") or {}
        if isinstance(availability, dict):
            value = str(availability.get("value") or "").strip().upper()
            if value == "IN_STOCK":
                return True, True
            if value:
                return True, False

        can_add_to_cart = product.get("showAtc")
        if isinstance(can_add_to_cart, bool):
            return True, can_add_to_cart

        return True, False

    def _product_from_search_item(self, item: dict[str, Any]) -> Product | None:
        """Build a Product from a Lider search result item."""

        canonical_url = str(item.get("canonicalUrl") or "").strip()
        full_url = urljoin(self.BASE_URL, canonical_url)
        name = fix_text_encoding(str(item.get("name") or "").strip())
        image_info = item.get("imageInfo") or {}
        image_url = ""
        if isinstance(image_info, dict):
            image_url = str(image_info.get("thumbnailUrl") or "").strip()

        price_info = item.get("priceInfo") or {}
        if not isinstance(price_info, dict):
            return None

        price_now = self._parse_price(price_info.get("linePrice") or price_info.get("itemPrice"))
        price_before = self._parse_price(price_info.get("wasPrice") or price_info.get("itemPrice"))
        category = self._extract_category(item.get("category"))
        product_id = str(item.get("usItemId") or item.get("id") or full_url).strip()

        return self._build_product(
            product_id=f"{self.STORE_NAME}:{product_id}",
            name=name,
            price_now=price_now,
            price_before=price_before,
            category=category,
            url=full_url,
            image_url=image_url,
        )

    def _build_search_url(self, query: str) -> str:
        """Build the Lider search URL."""

        return f"{self.BASE_URL}/search?q={quote_plus(query)}"

    def _fetch(self, url: str) -> str | None:
        """Fetch one Lider page with retry logic."""

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
                    "Lider fetch failed (%s/%s) for %s: %s",
                    attempt,
                    self.config.request_retries,
                    url,
                    exc,
                )
        return None

    @staticmethod
    def _extract_next_data(html: str) -> dict[str, Any]:
        """Extract __NEXT_DATA__ from a Lider page."""

        soup = BeautifulSoup(html, "html.parser")
        script = soup.find("script", id="__NEXT_DATA__")
        if not script:
            return {}
        try:
            payload = json.loads(script.get_text())
        except ValueError:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _extract_category(value: object) -> str:
        """Map Lider category path into one of the configured canonical groups."""

        if not isinstance(value, dict):
            return "custom"

        names = []
        for item in value.get("path", []):
            if isinstance(item, dict):
                name = str(item.get("name") or "").strip().lower()
                if name:
                    names.append(name)
        haystack = " ".join(names)

        if any(term in haystack for term in ["tecno", "telefon", "videojuego", "audio", "comput"]):
            return "tecnologia"
        if any(term in haystack for term in ["electro", "linea blanca", "clima"]):
            return "electrodomesticos"
        if any(term in haystack for term in ["bicic", "deporte"]):
            return "bicicletas"
        if any(term in haystack for term in ["hogar", "cocina", "menaje"]):
            return "menaje"
        if any(term in haystack for term in ["vestuario", "moda", "ropa", "calzado"]):
            return "ropa"
        return "custom"

    @staticmethod
    def _parse_price(value: object) -> int:
        """Normalize Lider price strings into integer CLP values."""

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
        cleaned_url = urljoin(self.BASE_URL, url).strip() if url else ""
        cleaned_image_url = urljoin(self.BASE_URL, image_url).strip() if image_url else ""
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
        )
