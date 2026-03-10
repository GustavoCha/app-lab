"""Paris.cl scraper with API discovery and HTML fallbacks."""

from __future__ import annotations

import codecs
import json
import logging
import re
from typing import Any
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

from config.config import AppConfig
from models.product import Product
from utils.normalization import normalize_product_name


LOGGER = logging.getLogger(__name__)


class ParisScraper:
    """Scrape discounted products from Paris.cl."""

    STORE_NAME = "paris"
    BASE_URL = "https://www.paris.cl"
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    )
    UNAVAILABLE_MARKERS = (
        "Estamos mejorando tu experiencia",
        "Muy pronto esta p",
    )

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update(
            {
                "User-Agent": self.USER_AGENT,
                "Accept-Language": "es-CL,es;q=0.9,en;q=0.8",
            }
        )

    def scrape(self) -> list[Product]:
        """Scrape all configured categories."""

        all_products: dict[str, Product] = {}
        if self.config.watch_queries:
            for query in self.config.watch_queries:
                for product in self._scrape_search_query(query):
                    all_products[product.product_id] = product
            return list(all_products.values())

        for category in self.config.allowed_categories:
            for product in self._scrape_category(category):
                all_products[product.product_id] = product
        return list(all_products.values())

    def get_product_page_state(self, url: str) -> tuple[bool, bool]:
        """Return page availability and stock status for a product detail page."""

        html = self._fetch(url)
        if not html:
            return False, False

        if any(marker in html for marker in self.UNAVAILABLE_MARKERS):
            return False, False

        return True, self._extract_stock_status_from_html(html)

    def _scrape_search_query(self, query: str) -> list[Product]:
        """Scrape products for a specific free-text search query."""

        page_url = f"{self.BASE_URL}/search/?q={quote_plus(query)}"
        html = self._fetch(page_url)
        if not html:
            return []

        products = self._parse_next_data_products(html, "custom")
        LOGGER.info("Search query '%s': parsed %s products", query, len(products))
        return products

    def _scrape_category(self, category: str) -> list[Product]:
        """Scrape a single category with resilient fallbacks."""

        urls = list(self.config.category_urls.get(category, []))
        search_query = self.config.search_query_by_category.get(category, category)
        search_url = f"{self.BASE_URL}/search/?q={search_query}"
        if search_url not in urls:
            urls.insert(0, search_url)
        products: dict[str, Product] = {}

        for base_url in urls:
            for page_number in range(self.config.pages_per_category):
                page_url = self._build_paged_url(base_url, page_number)
                html = self._fetch(page_url)
                if not html:
                    continue

                next_data_products = self._parse_next_data_products(html, category)
                for product in next_data_products:
                    products[product.url] = product
                if next_data_products:
                    LOGGER.info(
                        "Category '%s': parsed %s products from Next.js flight data",
                        category,
                        len(next_data_products),
                    )
                    return list(products.values())

                for api_url in self._discover_api_urls(html, page_url):
                    for product in self._parse_api_products(api_url, category):
                        products[product.url] = product
                if products:
                    LOGGER.info("Category '%s': parsed from API strategy", category)
                    return list(products.values())

                for product in self._parse_html_products(html, page_url, category):
                    products[product.url] = product

            if products:
                break

        LOGGER.info("Category '%s': scraped %s products", category, len(products))
        return list(products.values())

    def _parse_next_data_products(self, html: str, category: str) -> list[Product]:
        """Extract products from the Next.js flight data embedded in the page."""

        soup = BeautifulSoup(html, "html.parser")
        for script in soup.find_all("script"):
            script_text = script.get_text()
            payload = self._extract_json_object(script_text, "initialProductListData")
            if not payload:
                continue

            products = []
            for item in payload.get("products", []):
                if not isinstance(item, dict):
                    continue
                product = self._product_from_search_payload(item, category)
                if product:
                    products.append(product)
            if products:
                return products
        return []

    def _product_from_search_payload(self, data: dict[str, Any], category: str) -> Product | None:
        """Build a product from the search payload used by paris.cl."""

        prices = data.get("masterVariant", {}).get("prices", {})
        regular_price = prices.get("regular", {}).get("value", {}).get("centAmount", 0)

        offer_candidates = [
            prices.get("offer", {}).get("value", {}).get("centAmount", 0),
            prices.get("paymentMethod", {}).get("value", {}).get("centAmount", 0),
        ]
        current_price = min([value for value in offer_candidates if isinstance(value, int) and value > 0], default=0)

        slug = str(data.get("slug", "")).strip()
        key = str(data.get("key", "")).strip()
        url = ""
        if slug:
            url = f"{self.BASE_URL}/{slug}.html"
        elif key:
            url = f"{self.BASE_URL}/{key}.html"

        category_name = self._map_category(category, str(data.get("productType", {}).get("key", "")))
        return self._build_product(
            product_id=f"{self.STORE_NAME}:{key or slug}",
            name=str(data.get("name", "")).strip(),
            price_now=current_price,
            price_before=int(regular_price) if isinstance(regular_price, int) else 0,
            category=category_name,
            url=url,
        )

    def _build_paged_url(self, base_url: str, page_number: int) -> str:
        """Build a category page URL with simple pagination heuristics."""

        if page_number == 0:
            return base_url
        separator = "&" if "?" in base_url else "?"
        start = page_number * self.config.page_size
        return f"{base_url}{separator}start={start}&sz={self.config.page_size}"

    def _fetch(self, url: str) -> str | None:
        """Fetch a page with retry logic."""

        for attempt in range(1, self.config.request_retries + 1):
            try:
                response = self.session.get(url, timeout=self.config.request_timeout)
                response.raise_for_status()
                return response.text
            except requests.RequestException as exc:
                LOGGER.warning(
                    "Fetch failed (%s/%s) for %s: %s",
                    attempt,
                    self.config.request_retries,
                    url,
                    exc,
                )
        return None

    def _discover_api_urls(self, html: str, page_url: str) -> list[str]:
        """Look for internal API endpoints or embedded JSON routes."""

        discovered: set[str] = set()
        patterns = [
            r"https://[^\"']+/api/[^\"']+",
            r"/api/[^\"']+",
            r"/on/demandware\.store/[^\"']+",
            r"/s/Search[^\"']+",
        ]

        for pattern in patterns:
            for match in re.findall(pattern, html):
                discovered.add(urljoin(page_url, match))

        soup = BeautifulSoup(html, "html.parser")
        for script in soup.find_all("script"):
            script_text = script.get_text(" ", strip=True)
            if "api" not in script_text.lower():
                continue
            for pattern in patterns:
                for match in re.findall(pattern, script_text):
                    discovered.add(urljoin(page_url, match))

        return sorted(discovered)

    def _parse_api_products(self, api_url: str, category: str) -> list[Product]:
        """Attempt to parse products from a discovered JSON endpoint."""

        try:
            response = self.session.get(api_url, timeout=self.config.request_timeout)
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            return []

        products = self._collect_products_from_json(payload, category)
        LOGGER.info("Parsed %s products from API %s", len(products), api_url)
        return products

    def _collect_products_from_json(self, payload: Any, category: str) -> list[Product]:
        """Walk arbitrary JSON payloads and extract product-like records."""

        results: dict[str, Product] = {}

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                product = self._product_from_mapping(node, category)
                if product:
                    results[product.url] = product
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(payload)
        return list(results.values())

    def _parse_html_products(self, html: str, page_url: str, category: str) -> list[Product]:
        """Parse product cards or embedded structured data from HTML."""

        soup = BeautifulSoup(html, "html.parser")
        products: dict[str, Product] = {}

        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            product = self._product_from_json_ld(script.string or "", category)
            if product:
                products[product.url] = product

        selectors = [
            "[data-product-id]",
            "[data-testid='product-card']",
            ".product-card",
            ".product-tile",
            ".grid-tile",
        ]
        for selector in selectors:
            for node in soup.select(selector):
                product = self._product_from_html_node(node, page_url, category)
                if product:
                    products[product.url] = product
            if products:
                break

        return list(products.values())

    def _product_from_json_ld(self, raw_json: str, category: str) -> Product | None:
        """Build a product from JSON-LD blocks."""

        try:
            payload = json.loads(raw_json)
        except ValueError:
            return None

        if isinstance(payload, list):
            for item in payload:
                product = self._product_from_mapping(item, category)
                if product:
                    return product
            return None

        return self._product_from_mapping(payload, category)

    def _product_from_html_node(self, node: Any, page_url: str, category: str) -> Product | None:
        """Build a product from a parsed HTML card."""

        name_node = node.select_one("a[title], .product-name, .name, h2, h3")
        price_now_node = node.select_one("[data-price], .sales, .price-sales, .best-price, .price")
        price_before_node = node.select_one(
            ".list-price, .price-standard, .old-price, .strike-through, [data-list-price]"
        )
        link_node = node.select_one("a[href]")

        name = ""
        if name_node:
            name = name_node.get("title") or name_node.get_text(" ", strip=True)
        url = urljoin(page_url, link_node.get("href", "")) if link_node else ""
        price_now = self._parse_price(
            (price_now_node.get("data-price") if price_now_node else "")
            or (price_now_node.get_text(" ", strip=True) if price_now_node else "")
        )
        price_before = self._parse_price(
            (price_before_node.get("data-list-price") if price_before_node else "")
            or (price_before_node.get_text(" ", strip=True) if price_before_node else "")
        )

        return self._build_product(
            product_id=f"{self.STORE_NAME}:{url or name}",
            name=name,
            price_now=price_now,
            price_before=price_before,
            category=category,
            url=url,
        )

    def _product_from_mapping(self, data: dict[str, Any], category: str) -> Product | None:
        """Build a product from a generic mapping."""

        name = self._first_string(
            data,
            ["name", "productName", "displayName", "product_name", "title"],
        )
        url = self._first_string(data, ["url", "link", "productUrl", "pdpUrl", "href"])
        offers = data.get("offers")

        price_now = self._extract_price_now(data, offers)
        price_before = self._extract_price_before(data, offers)
        nested_category = self._first_string(data, ["category", "department", "breadcrumb"])
        resolved_category = self._map_category(category, nested_category)

        product_id = self._first_string(data, ["id", "key", "sku", "productId"]) or url or name
        return self._build_product(
            product_id=f"{self.STORE_NAME}:{product_id}",
            name=name,
            price_now=price_now,
            price_before=price_before,
            category=resolved_category,
            url=url,
        )

    def _extract_price_now(self, data: dict[str, Any], offers: Any) -> int:
        """Extract current price from different payload shapes."""

        candidates = [
            data.get("price_now"),
            data.get("currentPrice"),
            data.get("salePrice"),
            data.get("price"),
            data.get("bestPrice"),
        ]
        if isinstance(offers, list):
            candidates.extend(offer.get("price") for offer in offers if isinstance(offer, dict))
        elif isinstance(offers, dict):
            candidates.extend([offers.get("price"), offers.get("lowPrice")])

        for candidate in candidates:
            parsed = self._parse_price(candidate)
            if parsed > 0:
                return parsed
        return 0

    def _extract_price_before(self, data: dict[str, Any], offers: Any) -> int:
        """Extract previous price from different payload shapes."""

        candidates = [
            data.get("price_before"),
            data.get("listPrice"),
            data.get("regularPrice"),
            data.get("referencePrice"),
            data.get("oldPrice"),
            data.get("highPrice"),
        ]
        if isinstance(offers, list):
            offer_prices = [
                self._parse_price(offer.get("price"))
                for offer in offers
                if isinstance(offer, dict) and offer.get("price") is not None
            ]
            if offer_prices:
                candidates.append(max(offer_prices))
        elif isinstance(offers, dict):
            candidates.extend([offers.get("highPrice"), offers.get("listPrice")])

        parsed_candidates = [self._parse_price(candidate) for candidate in candidates]
        valid_candidates = [value for value in parsed_candidates if value > 0]
        return max(valid_candidates, default=0)

    def _build_product(
        self,
        product_id: str,
        name: str,
        price_now: int,
        price_before: int,
        category: str,
        url: str,
    ) -> Product | None:
        """Validate and build a product object."""

        cleaned_name = name.strip()
        cleaned_url = urljoin(self.BASE_URL, url).strip() if url else ""
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
        )

    @staticmethod
    def _first_string(data: dict[str, Any], keys: list[str]) -> str:
        """Return the first non-empty string-like value for the provided keys."""

        for key in keys:
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @staticmethod
    def _parse_price(value: Any) -> int:
        """Normalize Chilean prices into integers."""

        if value is None:
            return 0
        if isinstance(value, (int, float)):
            return int(value)

        digits = re.sub(r"[^\d]", "", str(value))
        return int(digits) if digits else 0

    @staticmethod
    def _map_category(default_category: str, discovered_category: str) -> str:
        """Map a discovered category back to one of the configured groups."""

        discovered = discovered_category.lower()
        category_aliases = {
            "tecnologia": ["tecnologia", "computacion", "tv", "audio", "gaming", "telefonia"],
            "electrodomesticos": ["electrodomesticos", "electro", "lavado", "climatizacion"],
            "bicicletas": ["bicicletas", "mountain bike", "urbanas", "deportes"],
            "menaje": ["menaje", "hogar", "cocina"],
            "ropa": ["ropa", "vestuario", "moda", "zapatillas"],
            "custom": ["custom"],
        }

        for canonical, aliases in category_aliases.items():
            if any(alias in discovered for alias in aliases):
                return canonical
        return default_category

    @staticmethod
    def _extract_json_object(script_text: str, marker: str) -> dict[str, Any] | None:
        """Extract and decode a JSON object embedded inside a script string."""

        marker_index = script_text.find(marker)
        if marker_index == -1:
            return None

        start = script_text.find("{", marker_index)
        if start == -1:
            return None

        depth = 0
        end = None
        for position in range(start, len(script_text)):
            character = script_text[position]
            if character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
                if depth == 0:
                    end = position + 1
                    break

        if end is None:
            return None

        raw_object = script_text[start:end]
        try:
            decoded = codecs.decode(raw_object, "unicode_escape")
            payload = json.loads(decoded)
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
            return None

        if isinstance(payload, dict):
            return payload
        return None

    @staticmethod
    def _extract_stock_status_from_html(html: str) -> bool:
        """Read stock state from JSON-LD offers on the product page."""

        soup = BeautifulSoup(html, "html.parser")
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            raw_json = script.string or script.get_text()
            if not raw_json.strip():
                continue

            try:
                payload = json.loads(raw_json)
            except ValueError:
                continue

            offers = payload.get("offers") if isinstance(payload, dict) else None
            if isinstance(offers, dict):
                offers = [offers]
            if not isinstance(offers, list):
                continue

            for offer in offers:
                if not isinstance(offer, dict):
                    continue
                availability = str(offer.get("availability", "")).lower()
                if "instock" in availability:
                    return True
                if "outofstock" in availability:
                    return False

        return False
