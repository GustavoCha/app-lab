"""Telegram webhook command handling."""

from __future__ import annotations

from typing import Any

from config.config import AppConfig
from database.supabase_repository import SupabaseRepository
from notifier.telegram_notifier import TelegramNotifier
from services.subscription_parser import build_help_text, parse_watch_command


class TelegramBotService:
    """Process inbound Telegram updates and manage subscriptions."""

    def __init__(self, config: AppConfig, repository: SupabaseRepository, notifier: TelegramNotifier) -> None:
        self.config = config
        self.repository = repository
        self.notifier = notifier

    def handle_update(self, update: dict[str, Any]) -> dict[str, object]:
        """Process one Telegram webhook payload."""

        message = update.get("message") or update.get("edited_message")
        if not isinstance(message, dict):
            return {"ok": True, "ignored": True}

        chat = message.get("chat", {})
        text = str(message.get("text") or "").strip()
        chat_id = str(chat.get("id") or "").strip()
        if not chat_id or not text.startswith("/"):
            return {"ok": True, "ignored": True}

        from_user = message.get("from", {}) if isinstance(message.get("from"), dict) else {}
        user = self.repository.upsert_user(
            telegram_chat_id=chat_id,
            username=str(from_user.get("username") or ""),
            first_name=str(from_user.get("first_name") or ""),
            last_name=str(from_user.get("last_name") or ""),
        )
        user_id = str(user.get("id") or "")
        if not user_id:
            self.notifier.send_message(chat_id, "No pude registrar tu usuario. Intenta de nuevo.")
            return {"ok": False}

        command, _, command_payload = text.partition(" ")
        command = command.lower()

        if command == "/start":
            self.notifier.send_message(chat_id, "Bot listo.\n\n" + build_help_text())
            return {"ok": True}
        if command == "/help":
            self.notifier.send_message(chat_id, build_help_text())
            return {"ok": True}
        if command == "/list":
            subscriptions = self.repository.list_user_subscriptions(user_id)
            if not subscriptions:
                self.notifier.send_message(chat_id, "No tienes suscripciones activas.")
                return {"ok": True}

            lines = ["Tus suscripciones:"]
            for subscription in subscriptions:
                lines.append(
                    f"#{subscription['id']} - {subscription.get('label') or subscription['search_query']} "
                    f"(min {subscription.get('min_discount', self.config.min_discount)}%)"
                )
            self.notifier.send_message(chat_id, "\n".join(lines))
            return {"ok": True}
        if command == "/delete":
            if not command_payload.strip().isdigit():
                self.notifier.send_message(chat_id, "Uso: /delete 12")
                return {"ok": True}
            subscription_id = int(command_payload.strip())
            self.repository.delete_subscription(user_id, subscription_id)
            self.notifier.send_message(chat_id, f"Suscripcion #{subscription_id} eliminada.")
            return {"ok": True}
        if command == "/watch":
            try:
                parsed = parse_watch_command(command_payload, self.config.min_discount)
            except ValueError as exc:
                self.notifier.send_message(chat_id, str(exc))
                return {"ok": True}

            created = self.repository.create_subscription(
                user_id=user_id,
                search_query=parsed.query,
                label=parsed.label,
                min_discount=parsed.min_discount,
                require_in_stock=parsed.require_in_stock,
                include_keywords_any=parsed.include_keywords_any,
                include_keywords_all=parsed.include_keywords_all,
                exclude_keywords=parsed.exclude_keywords,
            )
            subscription_id = created.get("id", "?")
            self.notifier.send_message(
                chat_id,
                (
                    f"Suscripcion creada #{subscription_id}\n"
                    f"Busqueda: {parsed.query}\n"
                    f"Min descuento: {parsed.min_discount}%\n"
                    f"Stock requerido: {'si' if parsed.require_in_stock else 'no'}"
                ),
            )
            return {"ok": True}

        self.notifier.send_message(chat_id, build_help_text())
        return {"ok": True}
