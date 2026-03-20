"""Application configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"


@dataclass(slots=True)
class AppConfig:
    """Central application configuration."""

    telegram_bot_token: str
    supabase_url: str
    supabase_service_role_key: str
    telegram_chat_id: str = ""
    telegram_webhook_secret: str = ""
    cron_secret: str = ""
    min_discount: float = 60.0
    min_price: int = 30000
    max_alerts_per_run: int = 100
    max_alerts_per_user_per_run: int = 15
    max_alerts_per_user_per_store_per_run: int = 15
    request_timeout: int = 20
    request_retries: int = 3
    require_in_stock: bool = True
    page_size: int = 30
    pages_per_category: int = 5
    best_discount_sort: str = "best-discount desc"
    watch_queries: list[str] = field(default_factory=list)
    include_keywords_any: list[str] = field(default_factory=list)
    include_keywords_all: list[str] = field(default_factory=list)
    exclude_keywords: list[str] = field(default_factory=list)
    search_query_by_category: dict[str, str] = field(
        default_factory=lambda: {
            "tecnologia": "tecnologia",
            "electrodomesticos": "electrodomesticos",
            "bicicletas": "bicicletas",
            "menaje": "menaje",
            "ropa": "ropa",
        }
    )
    allowed_categories: list[str] = field(
        default_factory=lambda: [
            "tecnologia",
            "electrodomesticos",
            "bicicletas",
            "menaje",
            "ropa",
        ]
    )
    category_urls: dict[str, list[str]] = field(
        default_factory=lambda: {
            "tecnologia": [
                "https://www.paris.cl/search/?q=tecnologia",
                "https://www.paris.cl/tecnologia/",
                "https://www.paris.cl/electro/tecnologia/",
            ],
            "electrodomesticos": [
                "https://www.paris.cl/search/?q=electrodomesticos",
                "https://www.paris.cl/electrodomesticos/",
                "https://www.paris.cl/electro-hogar/",
            ],
            "bicicletas": [
                "https://www.paris.cl/search/?q=bicicletas",
                "https://www.paris.cl/deportes/bicicletas/",
                "https://www.paris.cl/bicicletas/",
            ],
            "menaje": [
                "https://www.paris.cl/search/?q=menaje",
                "https://www.paris.cl/hogar-y-deco/menaje/",
                "https://www.paris.cl/menaje/",
            ],
            "ropa": [
                "https://www.paris.cl/search/?q=ropa",
                "https://www.paris.cl/vestuario/",
                "https://www.paris.cl/moda/",
            ],
        }
    )

    @property
    def seen_products_path(self) -> Path:
        return DATA_DIR / "seen_products.json"

    @property
    def price_history_path(self) -> Path:
        return DATA_DIR / "price_history.json"


def load_config() -> AppConfig:
    """Load settings from environment variables and defaults."""

    load_dotenv()
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    supabase_url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    supabase_service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()

    if not telegram_bot_token:
        raise ValueError("Missing TELEGRAM_BOT_TOKEN environment variable.")
    if not supabase_url:
        raise ValueError("Missing SUPABASE_URL environment variable.")
    if not supabase_service_role_key:
        raise ValueError("Missing SUPABASE_SERVICE_ROLE_KEY environment variable.")

    return AppConfig(
        telegram_bot_token=telegram_bot_token,
        supabase_url=supabase_url,
        supabase_service_role_key=supabase_service_role_key,
        telegram_chat_id=telegram_chat_id,
        telegram_webhook_secret=os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip(),
        cron_secret=os.getenv("CRON_SECRET", "").strip(),
        min_discount=float(os.getenv("MIN_DISCOUNT", "60")),
        min_price=int(os.getenv("MIN_PRICE", "30000")),
        max_alerts_per_run=int(os.getenv("MAX_ALERTS_PER_RUN", "100")),
        max_alerts_per_user_per_run=int(os.getenv("MAX_ALERTS_PER_USER_PER_RUN", "15")),
        max_alerts_per_user_per_store_per_run=int(
            os.getenv("MAX_ALERTS_PER_USER_PER_STORE_PER_RUN", "15")
        ),
        request_timeout=int(os.getenv("REQUEST_TIMEOUT", "20")),
        request_retries=int(os.getenv("REQUEST_RETRIES", "3")),
        require_in_stock=_parse_bool(os.getenv("REQUIRE_IN_STOCK", "true")),
        page_size=int(os.getenv("PAGE_SIZE", "30")),
        pages_per_category=int(os.getenv("PAGES_PER_CATEGORY", "5")),
        best_discount_sort=os.getenv("BEST_DISCOUNT_SORT", "best-discount desc").strip()
        or "best-discount desc",
        watch_queries=_parse_pipe_list(os.getenv("WATCH_QUERIES", "")),
        include_keywords_any=_parse_pipe_list(os.getenv("INCLUDE_KEYWORDS_ANY", "")),
        include_keywords_all=_parse_pipe_list(os.getenv("INCLUDE_KEYWORDS_ALL", "")),
        exclude_keywords=_parse_pipe_list(os.getenv("EXCLUDE_KEYWORDS", "")),
    )


def _parse_pipe_list(value: str) -> list[str]:
    """Parse a pipe-separated env var into a clean list."""

    return [item.strip() for item in value.split("|") if item.strip()]


def _parse_bool(value: str) -> bool:
    """Parse common truthy values from environment variables."""

    return value.strip().lower() in {"1", "true", "yes", "on"}
