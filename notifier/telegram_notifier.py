"""Telegram notification client."""

from __future__ import annotations

import logging

import requests

from models.product import Product


LOGGER = logging.getLogger(__name__)


class TelegramNotifier:
    """Minimal Telegram Bot API wrapper."""

    def __init__(self, bot_token: str, chat_id: str = "", timeout: int = 20) -> None:
        self.bot_token = bot_token
        self.default_chat_id = chat_id
        self.timeout = timeout
        self.base_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self.session = requests.Session()
        self.session.trust_env = False

    def send_message(self, chat_id: str, text: str, disable_preview: bool = True) -> bool:
        """Send a plain Telegram message."""

        payload = {
            "chat_id": chat_id or self.default_chat_id,
            "text": text,
            "disable_web_page_preview": disable_preview,
        }

        try:
            response = self.session.post(self.base_url, json=payload, timeout=self.timeout)
            response.raise_for_status()
            body = response.json()
            if not body.get("ok", False):
                LOGGER.error("Telegram API returned an error: %s", body)
                return False
            return True
        except requests.RequestException as exc:
            LOGGER.exception("Telegram notification failed: %s", exc)
            return False

    def send_product_alert(self, chat_id: str, product: Product, label: str = "") -> bool:
        """Send a formatted alert message for a product."""

        return self.send_message(
            chat_id=chat_id,
            text=self._build_message(product, label),
            disable_preview=False,
        )

    @staticmethod
    def _build_message(product: Product, label: str) -> str:
        """Format the Telegram alert body."""

        subscription_line = f"Suscripcion: {label}\n" if label else ""
        return (
            f"🔥 OFERTA {int(round(product.discount_percentage))}%\n\n"
            f"{subscription_line}"
            f"Producto: {product.name}\n"
            f"Categoria: {product.category}\n"
            f"Precio actual: ${product.price_now:,.0f}\n"
            f"Precio anterior: ${product.price_before:,.0f}\n"
            f"Score: {product.score:.2f}\n\n"
            f"Link:\n{product.url}"
        ).replace(",", ".")
