"""Paris.cl scraper with API discovery and HTML fallbacks."""

from __future__ import annotations

import codecs
import json
import logging
import re
from typing import Any
from urllib.parse import parse_qsl, quote_plus, urlencode, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

from config.config import AppConfig
from models.product import Product
from utils.normalization import fix_text_encoding, normalize_product_name


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
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "es-CL,es;q=0.9,en;q=0.8",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
                "Upgrade-Insecure-Requests": "1",
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

        products: dict[str, Product] = {}
        for page_number in range(1, self.config.pages_per_category + 1):
            page_url = ""
            html = None
            for candidate_url in self._build_search_urls(query, page_number):
                page_url = candidate_url
                html = self._fetch(candidate_url)
                if html:
                    break
            if not html or not page_url:
                continue

            page_products = self._parse_constructor_cards(html, page_url, "custom")
            if not page_products:
                page_products = self._parse_next_data_products(html, "custom")
            if not page_products:
                api_products: dict[str, Product] = {}
                for api_url in self._discover_api_urls(html, page_url):
                    for product in self._parse_api_products(api_url, "custom"):
                        api_products[product.url] = product
                html_products = self._parse_html_products(html, page_url, "custom")
                page_products = list(api_products.values()) + html_products

            unique_page_products = 0
            for product in page_products:
                if product.url not in products:
                    unique_page_products += 1
                products[product.url] = product

            LOGGER.info(
                "Search query '%s': page %s scanned, %s products found",
                query,
                page_number,
                len(page_products),
            )

            if not page_products or unique_page_products == 0:
                break

        LOGGER.info(
            "Search query '%s': scraped %s unique products using sort=%s",
            query,
            len(products),
            self.config.best_discount_sort,
        )
        return self._sort_products_by_discount(products.values())

    def _scrape_category(self, category: str) -> list[Product]:
        """Scrape a single category with resilient fallbacks."""

        urls = list(self.config.category_urls.get(category, []))
        search_query = self.config.search_query_by_category.get(category, category)
        for search_url in reversed(self._build_search_urls(search_query, 1)):
            if search_url not in urls:
                urls.insert(0, search_url)
        products: dict[str, Product] = {}

        for base_url in urls:
            for page_number in range(1, self.config.pages_per_category + 1):
                page_url = ""
                html = None
                for candidate_url in self._build_paged_urls(base_url, page_number):
                    page_url = candidate_url
                    html = self._fetch(candidate_url)
                    if html:
                        break
                if not html or not page_url:
                    continue

                constructor_products = self._parse_constructor_cards(html, page_url, category)
                next_data_products = self._parse_next_data_products(html, category) if not constructor_products else []
                api_products: dict[str, Product] = {}
                if not constructor_products and not next_data_products:
                    for api_url in self._discover_api_urls(html, page_url):
                        for product in self._parse_api_products(api_url, category):
                            api_products[product.url] = product
                html_products = (
                    self._parse_html_products(html, page_url, category)
                    if not constructor_products and not next_data_products
                    else []
                )
                page_products = constructor_products + next_data_products + list(api_products.values()) + html_products
                for product in page_products:
                    products[product.url] = product

                LOGGER.info(
                    "Category '%s': page %s scanned, %s products found",
                    category,
                    page_number,
                    len(page_products),
                )

                if not page_products:
                    break

            if products:
                break

        LOGGER.info("Category '%s': scraped %s products", category, len(products))
        return self._sort_products_by_discount(products.values())

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
        image_url = self._extract_image_url_from_mapping(data)

        category_name = self._map_category(category, str(data.get("productType", {}).get("key", "")))
        return self._build_product(
            product_id=f"{self.STORE_NAME}:{key or slug}",
            name=str(data.get("name", "")).strip(),
            price_now=current_price,
            price_before=int(regular_price) if isinstance(regular_price, int) else 0,
            category=category_name,
            url=url,
            image_url=image_url,
        )

    def _build_search_urls(self, query: str, page_number: int) -> list[str]:
        """Build candidate search URLs, preferring the most compatible variant first."""

        base = f"{self.BASE_URL}/search/?q={quote_plus(query)}"
        urls = [
            self._merge_query_params(
                base,
                {
                    "q": query,
                    "page": str(page_number),
                },
            )
        ]
        if self.config.best_discount_sort:
            urls.append(
                self._merge_query_params(
                    base,
                    {
                        "q": query,
                        "page": str(page_number),
                        "srule": self.config.best_discount_sort,
                    },
                )
            )
        return urls

    def _build_paged_urls(self, base_url: str, page_number: int) -> list[str]:
        """Build candidate category URLs with and without explicit sorting."""

        urls = [
            self._merge_query_params(
                base_url,
                {
                    "page": str(page_number),
                },
            )
        ]
        if self.config.best_discount_sort:
            urls.append(
                self._merge_query_params(
                    base_url,
                    {
                        "page": str(page_number),
                        "srule": self.config.best_discount_sort,
                    },
                )
            )
        return urls

    def _fetch(self, url: str) -> str | None:
        """Fetch a page with retry logic."""

        for attempt in range(1, self.config.request_retries + 1):
            try:
                response = self.session.get(
                    url,
                    timeout=self.config.request_timeout,
                    headers={
                        "Referer": f"{self.BASE_URL}/",
                    },
                )
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
            response = self.session.get(
                api_url,
                timeout=self.config.request_timeout,
                headers={
                    "Referer": f"{self.BASE_URL}/",
                    "Accept": "application/json,text/plain,*/*",
                },
            )
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

    def _parse_constructor_cards(self, html: str, page_url: str, category: str) -> list[Product]:
        """Parse server-rendered product cards used by the live Paris search pages."""

        soup = BeautifulSoup(html, "html.parser")
        products: dict[str, Product] = {}

        for node in soup.select("[data-cnstrc-item-id]"):
            product = self._product_from_constructor_card(node, page_url, category)
            if product:
                products[product.url] = product

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
        image_node = node.select_one("img[src], img[data-src], img[srcset]")
        image_url = self._extract_image_url_from_img(image_node, page_url)
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
            image_url=image_url,
        )

    def _product_from_constructor_card(self, node: Any, page_url: str, category: str) -> Product | None:
        """Build a product from Paris server-rendered Constructor cards."""

        product_id = str(node.get("data-cnstrc-item-id", "")).strip()
        name = str(node.get("data-cnstrc-item-name", "")).strip()
        link_node = node.select_one("a[href]")
        url = urljoin(page_url, link_node.get("href", "")) if link_node else ""
        image_node = node.select_one("img[src], img[data-src], img[srcset]")
        image_url = self._extract_image_url_from_img(image_node, page_url)

        current_price = 0
        previous_price = 0
        price_blocks = node.select("[data-testid='paris-pod-price']")
        if price_blocks:
            current_candidates = self._extract_display_prices(price_blocks[0].get_text(" ", strip=True))
            if current_candidates:
                current_price = current_candidates[-1]
        if len(price_blocks) > 1:
            previous_candidates = self._extract_display_prices(price_blocks[-1].get_text(" ", strip=True))
            if previous_candidates:
                previous_price = previous_candidates[-1]

        if current_price <= 0:
            current_price = self._parse_price(node.get("data-cnstrc-item-price"))
        if previous_price <= 0 or previous_price <= current_price:
            previous_price = max(self._extract_price_candidates(node.get_text(" ", strip=True)), default=0)

        if current_price <= 0 or previous_price <= 0:
            return None

        return self._build_product(
            product_id=f"{self.STORE_NAME}:{product_id or url or name}",
            name=name,
            price_now=current_price,
            price_before=previous_price,
            category=category,
            url=url,
            image_url=image_url,
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
        image_url: str = "",
    ) -> Product | None:
        """Validate and build a product object."""

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

    def _extract_image_url_from_mapping(self, data: dict[str, Any]) -> str:
        """Extract a best-effort image URL from a structured payload."""

        candidates: list[Any] = [
            data.get("image"),
            data.get("imageUrl"),
            data.get("image_url"),
        ]

        master_variant = data.get("masterVariant")
        if isinstance(master_variant, dict):
            candidates.append(master_variant.get("images"))

        for candidate in candidates:
            image_url = self._extract_image_candidate(candidate)
            if image_url:
                return image_url
        return ""

    def _extract_image_candidate(self, candidate: Any) -> str:
        """Normalize image payloads from several shapes into a single URL."""

        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
        if isinstance(candidate, dict):
            for key in ("url", "src", "imageUrl", "link"):
                value = candidate.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        if isinstance(candidate, list):
            for item in candidate:
                image_url = self._extract_image_candidate(item)
                if image_url:
                    return image_url
        return ""

    def _extract_image_url_from_img(self, node: Any, page_url: str) -> str:
        """Extract an image URL from an HTML img tag."""

        if not node:
            return ""

        src = str(node.get("src") or node.get("data-src") or "").strip()
        if not src:
            srcset = str(node.get("srcset") or "").strip()
            if srcset:
                src = srcset.split(",", 1)[0].strip().split(" ", 1)[0]

        return urljoin(page_url, src) if src else ""

    @staticmethod
    def _merge_query_params(url: str, updates: dict[str, str]) -> str:
        """Merge URL query params while preserving the original path."""

        parts = urlsplit(url)
        params = dict(parse_qsl(parts.query, keep_blank_values=True))
        params.update({key: value for key, value in updates.items() if value})
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), parts.fragment))

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

    @classmethod
    def _extract_price_candidates(cls, value: str) -> list[int]:
        """Extract every price-looking token from a text block."""

        return [cls._parse_price(match) for match in re.findall(r"\$\s*[\d\.\,]+", value or "")]

    @classmethod
    def _extract_display_prices(cls, value: str) -> list[int]:
        """Extract prices that belong to the main display, excluding unit-price text in parentheses."""

        cleaned = re.sub(r"\([^)]*\)", " ", value or "")
        return cls._extract_price_candidates(cleaned)

    @staticmethod
    def _sort_products_by_discount(products: Any) -> list[Product]:
        """Return products sorted by highest discount, then by highest previous price."""

        return sorted(
            list(products),
            key=lambda product: (
                ((product.price_before - product.price_now) / product.price_before) if product.price_before else 0,
                product.price_before,
            ),
            reverse=True,
        )

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
