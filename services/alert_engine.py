"""Multi-user alert execution pipeline."""

from __future__ import annotations

import logging

from config.config import AppConfig
from database.supabase_repository import SupabaseRepository
from filters.discount_filter import (
    boost_cross_store_scores,
    enrich_products,
    filter_products,
    sort_and_limit_products,
)
from notifier.telegram_notifier import TelegramNotifier
from scraper.paris_scraper import ParisScraper


LOGGER = logging.getLogger(__name__)


def run_alert_cycle(config: AppConfig) -> dict[str, int]:
    """Scrape watched queries, match subscriptions, and send alerts."""

    repository = SupabaseRepository(config)
    notifier = TelegramNotifier(bot_token=config.telegram_bot_token, timeout=config.request_timeout)
    scraper = ParisScraper(config)

    subscriptions = repository.get_active_subscriptions()
    if not subscriptions:
        LOGGER.info("No active subscriptions found.")
        return {"subscriptions": 0, "products_scanned": 0, "alerts_sent": 0}

    queries = sorted({subscription.search_query for subscription in subscriptions})
    products_by_query: dict[str, list] = {}
    all_products_by_id: dict[str, object] = {}

    for query in queries:
        products = boost_cross_store_scores(enrich_products(scraper._scrape_search_query(query)))
        products_by_query[query] = products
        for product in products:
            all_products_by_id[product.product_id] = product

    existing_state = repository.get_existing_product_state(list(all_products_by_id.keys()))
    availability_cache: dict[str, tuple[bool, bool]] = {}
    alerts_sent = 0

    for subscription in subscriptions:
        query_products = products_by_query.get(subscription.search_query, [])
        historical_min_prices = {
            product_id: _to_int_or_none(state.get("historical_min_price"))
            for product_id, state in existing_state.items()
        }
        filtered_products = filter_products(
            products=query_products,
            min_discount=subscription.min_discount,
            allowed_categories=["tecnologia", "electrodomesticos", "bicicletas", "menaje", "ropa", "custom"],
            historical_min_prices=historical_min_prices,
            include_keywords_any=subscription.include_keywords_any,
            include_keywords_all=subscription.include_keywords_all,
            exclude_keywords=subscription.exclude_keywords,
        )

        sent_product_ids = repository.get_sent_product_ids(subscription.user_id, subscription.id)
        ranked_products = sort_and_limit_products(
            [product for product in filtered_products if product.product_id not in sent_product_ids],
            max(len(filtered_products), config.max_alerts_per_run),
        )

        chosen_products = []
        for product in ranked_products:
            if product.product_id not in availability_cache:
                availability_cache[product.product_id] = scraper.get_product_page_state(product.url)
            page_available, in_stock = availability_cache[product.product_id]
            if not page_available:
                continue
            if subscription.require_in_stock and not in_stock:
                continue

            chosen_products.append(product)
            if len(chosen_products) >= config.max_alerts_per_run:
                break

        for product in chosen_products:
            if notifier.send_product_alert(subscription.telegram_chat_id, product, subscription.label):
                repository.record_sent_alert(subscription.user_id, subscription.id, product)
                alerts_sent += 1

    repository.persist_products(
        products=list(all_products_by_id.values()),
        existing_state=existing_state,
        availability_by_product_id={
            product_id: in_stock
            for product_id, (_, in_stock) in availability_cache.items()
        },
    )

    return {
        "subscriptions": len(subscriptions),
        "products_scanned": len(all_products_by_id),
        "alerts_sent": alerts_sent,
    }


def _to_int_or_none(value: object) -> int | None:
    """Normalize nullable numeric values from PostgREST."""

    if value is None:
        return None
    return int(value)
