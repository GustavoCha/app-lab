"""Multi-user alert execution pipeline."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass

from config.config import AppConfig
from database.supabase_repository import SupabaseRepository
from filters.discount_filter import (
    FilterStats,
    boost_cross_store_scores,
    enrich_products,
    filter_products,
    sort_and_limit_products,
)
from models.product import Product
from models.subscription import Subscription
from notifier.telegram_notifier import TelegramNotifier
from scraper.lider_scraper import LiderScraper
from scraper.paris_scraper import ParisScraper


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class PendingAlert:
    """Candidate alert for one subscription and one product."""

    subscription: Subscription
    product: Product


def run_alert_cycle(config: AppConfig) -> dict[str, int]:
    """Scrape watched queries, match subscriptions, and send alerts."""

    repository = SupabaseRepository(config)
    notifier = TelegramNotifier(bot_token=config.telegram_bot_token, timeout=config.request_timeout)
    scrapers = {
        "paris": ParisScraper(config),
        "lider": LiderScraper(config),
    }

    subscriptions = repository.get_active_subscriptions()
    if not subscriptions:
        LOGGER.info("No active subscriptions found.")
        return {
            "subscriptions": 0,
            "products_scanned": 0,
            "offers_found": 0,
            "alerts_sent": 0,
            "duplicates_skipped": 0,
            "filtered_by_price": 0,
            "filtered_by_discount": 0,
        }

    queries = sorted({subscription.search_query for subscription in subscriptions})
    products_by_query: dict[str, list[Product]] = {}
    all_products_by_id: dict[str, Product] = {}
    aggregate_filter_stats = FilterStats()

    for query in queries:
        query_products: list[Product] = []
        for scraper in scrapers.values():
            query_products.extend(scraper._scrape_search_query(query))
        products = boost_cross_store_scores(enrich_products(query_products))
        products_by_query[query] = products
        for product in products:
            all_products_by_id[product.product_id] = product

    existing_state = repository.get_existing_product_state(list(all_products_by_id.keys()))
    availability_cache: dict[str, tuple[bool, bool]] = {}
    pending_alerts: list[PendingAlert] = []
    alerts_sent = 0
    duplicates_skipped = 0

    for subscription in subscriptions:
        query_products = products_by_query.get(subscription.search_query, [])
        filtered_products, filter_stats = filter_products(
            products=query_products,
            min_discount=subscription.min_discount,
            min_price=config.min_price,
            allowed_categories=["tecnologia", "electrodomesticos", "bicicletas", "menaje", "ropa", "custom"],
            search_query=subscription.search_query,
            include_keywords_any=subscription.include_keywords_any,
            include_keywords_all=subscription.include_keywords_all,
            exclude_keywords=subscription.exclude_keywords,
        )
        _merge_filter_stats(aggregate_filter_stats, filter_stats)

        sent_product_ids = repository.get_sent_product_ids(subscription.user_id, subscription.id)
        ranked_products = sort_and_limit_products(
            [product for product in filtered_products if product.product_id not in sent_product_ids],
            len(filtered_products),
        )

        for product in ranked_products:
            if product.discount_percentage < subscription.min_discount:
                aggregate_filter_stats.filtered_by_discount += 1
                continue
            if product.product_id not in availability_cache:
                if product.page_available_hint is not None and product.in_stock_hint is not None:
                    availability_cache[product.product_id] = (
                        product.page_available_hint,
                        product.in_stock_hint,
                    )
                else:
                    store_scraper = scrapers.get(product.store)
                    if not store_scraper:
                        continue
                    availability_cache[product.product_id] = store_scraper.get_product_page_state(product.url)
            page_available, in_stock = availability_cache[product.product_id]
            if not page_available:
                continue
            if subscription.require_in_stock and not in_stock:
                continue

            pending_alerts.append(PendingAlert(subscription=subscription, product=product))

    ranked_alerts = sorted(
        pending_alerts,
        key=lambda candidate: (
            candidate.product.score,
            candidate.product.discount_percentage,
            candidate.product.price_before,
        ),
        reverse=True,
    )

    offers_found = len(ranked_alerts)
    alerts_sent_by_user_store: dict[tuple[str, str], int] = defaultdict(int)
    for candidate in ranked_alerts:
        if alerts_sent >= config.max_alerts_per_run:
            break

        subscription = candidate.subscription
        product = candidate.product
        user_store_key = (subscription.user_id, product.store)
        if (
            alerts_sent_by_user_store[user_store_key]
            >= config.max_alerts_per_user_per_store_per_run
        ):
            continue
        if product.discount_percentage < subscription.min_discount:
            aggregate_filter_stats.filtered_by_discount += 1
            continue

        if notifier.send_product_alert(subscription.telegram_chat_id, product, subscription.label):
            repository.record_sent_alert(subscription.user_id, subscription.id, product)
            alerts_sent += 1
            alerts_sent_by_user_store[user_store_key] += 1

    repository.persist_products(
        products=list(all_products_by_id.values()),
        existing_state=existing_state,
        availability_by_product_id={
            product_id: in_stock
            for product_id, (_, in_stock) in availability_cache.items()
        },
    )

    stats = {
        "subscriptions": len(subscriptions),
        "products_scanned": len(all_products_by_id),
        "offers_found": offers_found,
        "alerts_sent": alerts_sent,
        "duplicates_skipped": duplicates_skipped,
        "filtered_by_price": aggregate_filter_stats.filtered_by_price,
        "filtered_by_discount": aggregate_filter_stats.filtered_by_discount,
    }
    LOGGER.info(
        "Cycle summary | products_scanned=%s offers_found=%s alerts_sent=%s duplicates_skipped=%s filtered_by_price=%s filtered_by_discount=%s",
        stats["products_scanned"],
        stats["offers_found"],
        stats["alerts_sent"],
        stats["duplicates_skipped"],
        stats["filtered_by_price"],
        stats["filtered_by_discount"],
    )
    return stats


def _merge_filter_stats(target: FilterStats, source: FilterStats) -> None:
    """Accumulate filter counters into a shared cycle total."""

    for field_name, value in source.to_dict().items():
        setattr(target, field_name, getattr(target, field_name) + value)
