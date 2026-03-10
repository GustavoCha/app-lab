"""Supabase-backed persistence layer."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import requests

from config.config import AppConfig
from models.product import Product
from models.subscription import Subscription


LOGGER = logging.getLogger(__name__)


class SupabaseRepository:
    """Thin PostgREST client for the bot data model."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.base_url = f"{config.supabase_url}/rest/v1"
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update(
            {
                "apikey": config.supabase_service_role_key,
                "Authorization": f"Bearer {config.supabase_service_role_key}",
                "Content-Type": "application/json",
            }
        )

    def upsert_user(
        self,
        telegram_chat_id: str,
        username: str = "",
        first_name: str = "",
        last_name: str = "",
    ) -> dict[str, object]:
        """Create or update a Telegram user."""

        payload = [
            {
                "telegram_chat_id": telegram_chat_id,
                "username": username or None,
                "first_name": first_name or None,
                "last_name": last_name or None,
                "is_active": True,
            }
        ]
        rows = self._request(
            "POST",
            "users",
            params={"on_conflict": "telegram_chat_id", "select": "*"},
            json_body=payload,
            prefer="resolution=merge-duplicates,return=representation",
        )
        return rows[0] if rows else {}

    def create_subscription(
        self,
        user_id: str,
        search_query: str,
        label: str,
        min_discount: float,
        require_in_stock: bool,
        include_keywords_any: list[str],
        include_keywords_all: list[str],
        exclude_keywords: list[str],
    ) -> dict[str, object]:
        """Create a new user subscription."""

        rows = self._request(
            "POST",
            "subscriptions",
            params={"select": "*"},
            json_body=[
                {
                    "user_id": user_id,
                    "search_query": search_query,
                    "label": label,
                    "min_discount": min_discount,
                    "require_in_stock": require_in_stock,
                    "include_keywords_any": include_keywords_any,
                    "include_keywords_all": include_keywords_all,
                    "exclude_keywords": exclude_keywords,
                    "enabled": True,
                }
            ],
            prefer="return=representation",
        )
        return rows[0] if rows else {}

    def list_user_subscriptions(self, user_id: str) -> list[dict[str, object]]:
        """Return subscriptions belonging to a user."""

        return self._request(
            "GET",
            "subscriptions",
            params={
                "user_id": f"eq.{user_id}",
                "order": "id.asc",
                "select": "*",
            },
        )

    def delete_subscription(self, user_id: str, subscription_id: int) -> bool:
        """Delete one subscription owned by a user."""

        self._request(
            "DELETE",
            "subscriptions",
            params={
                "id": f"eq.{subscription_id}",
                "user_id": f"eq.{user_id}",
                "select": "id",
            },
            prefer="return=representation",
        )
        return True

    def get_active_subscriptions(self) -> list[Subscription]:
        """Load all subscriptions for active users."""

        subscriptions = self._request(
            "GET",
            "subscriptions",
            params={
                "enabled": "eq.true",
                "order": "id.asc",
                "select": "*",
            },
        )
        if not subscriptions:
            return []

        user_ids = sorted({str(row["user_id"]) for row in subscriptions})
        users = self._request(
            "GET",
            "users",
            params={
                "id": self._format_in_filter(user_ids),
                "is_active": "eq.true",
                "select": "id,telegram_chat_id,first_name,username",
            },
        )
        users_by_id = {str(row["id"]): row for row in users}

        result: list[Subscription] = []
        for row in subscriptions:
            user = users_by_id.get(str(row["user_id"]))
            if not user:
                continue
            result.append(
                Subscription.from_record(
                    row,
                    chat_id=str(user["telegram_chat_id"]),
                )
            )
        return result

    def get_existing_product_state(self, product_ids: list[str]) -> dict[str, dict[str, object]]:
        """Load stored product metadata for a batch of product ids."""

        if not product_ids:
            return {}

        rows = self._request(
            "GET",
            "products",
            params={
                "product_id": self._format_in_filter(product_ids),
                "select": "product_id,historical_min_price,last_price_now,last_in_stock",
            },
        )
        return {str(row["product_id"]): row for row in rows}

    def get_sent_product_ids(self, user_id: str, subscription_id: int) -> set[str]:
        """Return product ids already alerted for one subscription."""

        rows = self._request(
            "GET",
            "sent_alerts",
            params={
                "user_id": f"eq.{user_id}",
                "subscription_id": f"eq.{subscription_id}",
                "select": "product_id",
            },
        )
        return {str(row["product_id"]) for row in rows}

    def record_sent_alert(self, user_id: str, subscription_id: int, product: Product) -> None:
        """Persist a sent alert entry."""

        self._request(
            "POST",
            "sent_alerts",
            json_body=[
                {
                    "user_id": user_id,
                    "subscription_id": subscription_id,
                    "product_id": product.product_id,
                }
            ],
            prefer="return=minimal",
        )

    def persist_products(
        self,
        products: list[Product],
        existing_state: dict[str, dict[str, object]],
        availability_by_product_id: dict[str, bool],
    ) -> None:
        """Upsert latest product snapshot and append price history."""

        if not products:
            return

        now = datetime.now(timezone.utc).isoformat()
        product_rows: list[dict[str, object]] = []
        history_rows: list[dict[str, object]] = []

        for product in products:
            previous = existing_state.get(product.product_id, {})
            previous_min = previous.get("historical_min_price")
            previous_min_value = int(previous_min) if previous_min is not None else product.price_now
            historical_min = min(previous_min_value, product.price_now)

            product_rows.append(
                {
                    "product_id": product.product_id,
                    "store": product.store,
                    "name": product.name,
                    "normalized_name": product.normalized_name,
                    "category": product.category,
                    "url": product.url,
                    "last_price_now": product.price_now,
                    "last_price_before": product.price_before,
                    "last_discount_percentage": product.discount_percentage,
                    "last_score": product.score,
                    "historical_min_price": historical_min,
                    "last_in_stock": availability_by_product_id.get(product.product_id),
                    "last_seen_at": now,
                }
            )
            history_rows.append(
                {
                    "product_id": product.product_id,
                    "price_now": product.price_now,
                    "price_before": product.price_before,
                    "discount_percentage": product.discount_percentage,
                    "captured_at": now,
                }
            )

        self._request(
            "POST",
            "products",
            params={"on_conflict": "product_id", "select": "product_id"},
            json_body=product_rows,
            prefer="resolution=merge-duplicates,return=minimal",
        )
        self._request(
            "POST",
            "price_history",
            json_body=history_rows,
            prefer="return=minimal",
        )

    def _request(
        self,
        method: str,
        table: str,
        params: dict[str, str] | None = None,
        json_body: list[dict[str, object]] | None = None,
        prefer: str | None = None,
    ) -> list[dict[str, Any]]:
        """Perform a PostgREST request."""

        headers = {}
        if prefer:
            headers["Prefer"] = prefer

        response = self.session.request(
            method=method,
            url=f"{self.base_url}/{table}",
            params=params,
            json=json_body,
            headers=headers,
            timeout=self.config.request_timeout,
        )
        response.raise_for_status()

        if not response.content:
            return []

        payload = response.json()
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            return [payload]

        LOGGER.warning("Unexpected response payload from Supabase: %s", payload)
        return []

    @staticmethod
    def _format_in_filter(values: list[str]) -> str:
        """Encode values for a PostgREST in() filter."""

        quoted = ",".join(f"\"{value}\"" for value in values)
        return f"in.({quoted})"
