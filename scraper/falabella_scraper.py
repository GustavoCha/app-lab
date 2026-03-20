"""Falabella scraper using Next.js SSR payloads and browser impersonation."""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import quote_plus

from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests

from config.config import AppConfig
from models.product import Product
from utils.normalization import fix_text_encoding, normalize_product_name


LOGGER = logging.getLogger(__name__)


class FalabellaScraper:
    """Scrape Falabella search results while excluding marketplace/international offers."""

    STORE_NAME = "falabella"
    BASE_URL = "https://www.falabella.com/falabella-cl"
    USER_AGENT = "Mozilla/5.0"
    SELLER_IDS = {"FALABELLA_CHILE"}
    SELLER_NAMES = {"FALABELLA"}

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def _scrape_search_query(self, query: str) -> list[Product]:
        """Scrape one Falabella free-text query across several pages."""

        products: dict[str, Product] = {}
        for page in range(1, self.config.pages_per_category + 1):
            html = self._fetch(self._build_search_url(query, page))
            if not html:
                continue

            next_payload = self._extract_next_data(html)
            if not next_payload:
                continue

            page_props = next_payload.get("props", {}).get("pageProps", {})
            results = page_props.get("results", [])
            if not isinstance(results, list):
                continue

            page_new_products = 0
            for item in results:
                if not isinstance(item, dict):
                    continue
                product = self._product_from_search_item(item)
                if not product:
                    continue
                if product.product_id in products:
                    continue
                products[product.product_id] = product
                page_new_products += 1

            LOGGER.info(
                "Falabella query '%s': page %s scanned, %s accepted products found",
                query,
                page,
                page_new_products,
            )

            pagination = page_props.get("pagination", {})
            current_page = int(pagination.get("currentPage") or page)
            total_per_page = int(pagination.get("totalPerPage") or 0)
            if page_new_products == 0 or current_page >= total_per_page:
                break

        LOGGER.info("Falabella query '%s': scraped %s products", query, len(products))
        return list(products.values())

    def get_product_page_state(self, url: str) -> tuple[bool, bool]:
        """Return PDP availability and stock for a Falabella product."""

        html = self._fetch(url)
        if not html:
            return False, False

        next_payload = self._extract_next_data(html)
        if not next_payload:
            return False, False

        product_data = next_payload.get("props", {}).get("pageProps", {}).get("productData", {})
        if not isinstance(product_data, dict) or not product_data:
            return False, False

        if self._is_international_product_data(product_data):
            return False, False

        variants = product_data.get("variants", [])
        if not isinstance(variants, list) or not variants:
            return True, False

        for variant in variants:
            if not isinstance(variant, dict):
                continue
            if not self._variant_sold_by_falabella(variant):
                continue
            if bool(variant.get("isPurchaseable")):
                return True, True

        return True, False

    def _product_from_search_item(self, item: dict[str, Any]) -> Product | None:
        """Build a normalized product from one Falabella search result card."""

        if not self._is_falabella_offer(item):
            return None

        seller_id = str(item.get("sellerId") or "").strip().upper()
        seller_name = fix_text_encoding(str(item.get("sellerName") or "").strip()).upper()
        if seller_id not in self.SELLER_IDS and seller_name not in self.SELLER_NAMES:
            return None

        name = fix_text_encoding(str(item.get("displayName") or "").strip())
        full_url = str(item.get("url") or "").strip()
        product_id = str(item.get("productId") or item.get("skuId") or full_url).strip()
        category = self._extract_category(item.get("merchantCategoryId"))
        image_url = self._extract_image_url(item)
        price_now, price_before = self._extract_prices(item.get("prices"))
        availability = bool(item.get("availability", True))
        in_stock_hint = self._search_item_is_purchaseable(item)

        return self._build_product(
            product_id=f"{self.STORE_NAME}:{product_id}",
            name=name,
            price_now=price_now,
            price_before=price_before,
            category=category,
            url=full_url,
            image_url=image_url,
            page_available_hint=availability,
            in_stock_hint=in_stock_hint,
        )

    def _build_search_url(self, query: str, page: int) -> str:
        """Build a Falabella search URL."""

        return f"{self.BASE_URL}/search?Ntt={quote_plus(query)}&page={page}"

    def _fetch(self, url: str) -> str | None:
        """Fetch one Falabella page using a browser-like TLS fingerprint."""

        for attempt in range(1, self.config.request_retries + 1):
            try:
                response = curl_requests.get(
                    url,
                    impersonate="chrome124",
                    timeout=self.config.request_timeout,
                    headers={"User-Agent": self.USER_AGENT},
                )
                response.raise_for_status()
                return response.text
            except Exception as exc:  # pragma: no cover - network variability
                LOGGER.warning(
                    "Falabella fetch failed (%s/%s) for %s: %s",
                    attempt,
                    self.config.request_retries,
                    url,
                    exc,
                )
        return None

    @staticmethod
    def _extract_next_data(html: str) -> dict[str, Any]:
        """Extract __NEXT_DATA__ from a Falabella page."""

        soup = BeautifulSoup(html, "html.parser")
        script = soup.find("script", id="__NEXT_DATA__")
        if not script:
            return {}
        try:
            payload = json.loads(script.get_text())
        except ValueError:
            return {}
        return payload if isinstance(payload, dict) else {}

    @classmethod
    def _is_falabella_offer(cls, item: dict[str, Any]) -> bool:
        """Keep only products sold directly by Falabella and not marked as international."""

        seller_id = str(item.get("sellerId") or "").strip().upper()
        seller_name = fix_text_encoding(str(item.get("sellerName") or "").strip()).upper()
        if seller_id not in cls.SELLER_IDS and seller_name not in cls.SELLER_NAMES:
            return False

        haystack_parts = []
        for key in ("badges", "multipurposeBadges", "meatStickers", "promotions"):
            value = item.get(key)
            haystack_parts.append(json.dumps(value, ensure_ascii=False))
        haystack = fix_text_encoding(" ".join(haystack_parts)).lower()
        return "internacional" not in haystack and "international" not in haystack

    @classmethod
    def _variant_sold_by_falabella(cls, variant: dict[str, Any]) -> bool:
        """Check whether a PDP variant belongs to Falabella's own offering."""

        offerings = variant.get("offerings", [])
        if not isinstance(offerings, list):
            return False

        for offering in offerings:
            if not isinstance(offering, dict):
                continue
            seller_id = str(offering.get("sellerId") or "").strip().upper()
            seller_name = fix_text_encoding(str(offering.get("sellerName") or "").strip()).upper()
            if seller_id in cls.SELLER_IDS or seller_name in cls.SELLER_NAMES:
                return True
        return False

    @staticmethod
    def _is_international_product_data(product_data: dict[str, Any]) -> bool:
        """Detect explicit international shipping markers in the PDP payload."""

        if bool(product_data.get("internationalShipping")):
            return True

        haystack = fix_text_encoding(json.dumps(product_data.get("additionalPDPLabels"), ensure_ascii=False)).lower()
        return "internacional" in haystack or "international" in haystack

    @staticmethod
    def _search_item_is_purchaseable(item: dict[str, Any]) -> bool:
        """Infer stock from search-card shipping signals."""

        badges_haystack = fix_text_encoding(
            json.dumps(item.get("meatStickers") or [], ensure_ascii=False)
        ).lower()
        if "agotado" in badges_haystack or "sin stock" in badges_haystack:
            return False
        availability = item.get("availability")
        if isinstance(availability, bool):
            return availability
        return True

    @staticmethod
    def _extract_image_url(item: dict[str, Any]) -> str:
        """Extract the first useful image URL from Falabella media blocks."""

        media_urls = item.get("mediaUrls")
        if isinstance(media_urls, list):
            for media in media_urls:
                if isinstance(media, str) and media.strip():
                    return media.strip()

        media = item.get("media")
        if isinstance(media, dict):
            for key in ("url", "imageUrl"):
                value = media.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return ""

    @staticmethod
    def _extract_prices(prices: object) -> tuple[int, int]:
        """Map Falabella price rows into current and reference price."""

        if not isinstance(prices, list):
            return 0, 0

        current_price = 0
        reference_price = 0
        for price in prices:
            if not isinstance(price, dict):
                continue
            numeric = FalabellaScraper._parse_price(price.get("price"))
            price_type = str(price.get("type") or "").strip()
            crossed = bool(price.get("crossed"))
            if crossed or price_type == "normalPrice":
                reference_price = max(reference_price, numeric)
                continue
            if price_type in {"internetPrice", "eventPrice", "cmrPrice"}:
                if current_price == 0:
                    current_price = numeric
                else:
                    current_price = min(current_price, numeric)

        if current_price == 0 and reference_price > 0:
            current_price = reference_price
        return current_price, reference_price

    @staticmethod
    def _extract_category(value: object) -> str:
        """Map merchant category text into one of the canonical groups."""

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
        """Normalize Falabella price formats into integer CLP values."""

        if value is None:
            return 0
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, list):
            parsed_values = [
                int(digits)
                for part in value
                if (digits := re.sub(r"[^\d]", "", str(part)))
            ]
            return min(parsed_values) if parsed_values else 0
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
        page_available_hint: bool | None = None,
        in_stock_hint: bool | None = None,
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
            page_available_hint=page_available_hint,
            in_stock_hint=in_stock_hint,
        )
