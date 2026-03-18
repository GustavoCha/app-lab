"""Telegram webhook command handling."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from config.config import AppConfig
from database.supabase_repository import SupabaseRepository
from notifier.telegram_notifier import TelegramNotifier
from services.subscription_parser import ParsedSubscriptionCommand, build_help_text, parse_watch_command


@dataclass(slots=True)
class ConversationState:
    """Small helper model for user conversational flows."""

    flow: str
    step: str
    payload: dict[str, object]


class TelegramBotService:
    """Process inbound Telegram updates and manage subscriptions."""

    MENU_ADD = "Agregar alerta"
    MENU_LIST = "Ver mis alertas"
    MENU_DELETE = "Eliminar alerta"
    MENU_HELP = "Ayuda"
    MENU_CANCEL = "Cancelar"
    MENU_SKIP_EXCLUDE = "Ninguna"
    DISCOUNT_PRESETS = ("20", "30", "40", "50", "60")

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
        if not chat_id or not text:
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

        normalized_text = text.casefold()
        state = self._load_state(user_id)
        if normalized_text == self.MENU_CANCEL.casefold():
            self.repository.clear_conversation_state(user_id)
            self.notifier.send_message(chat_id, "Operacion cancelada.", reply_markup=self._main_menu_markup())
            return {"ok": True}

        if state is not None and not text.startswith("/"):
            return self._handle_conversation_input(chat_id, user_id, text, state)

        command, _, command_payload = text.partition(" ")
        command = command.lower()

        if command == "/start":
            self.repository.clear_conversation_state(user_id)
            self.notifier.send_message(
                chat_id,
                "Bot listo.\n\nSelecciona una opcion del menu.",
                reply_markup=self._main_menu_markup(),
            )
            return {"ok": True}
        if command == "/help":
            self.notifier.send_message(chat_id, build_help_text(), reply_markup=self._main_menu_markup())
            return {"ok": True}
        if command == "/list":
            self._send_subscription_list(chat_id, user_id)
            return {"ok": True}
        if command == "/delete":
            if not command_payload.strip().isdigit():
                self.notifier.send_message(chat_id, "Uso: /delete 12", reply_markup=self._main_menu_markup())
                return {"ok": True}
            subscription_id = int(command_payload.strip())
            deleted = self.repository.delete_subscription(user_id, subscription_id)
            self.notifier.send_message(
                chat_id,
                (
                    f"Suscripcion #{subscription_id} eliminada."
                    if deleted
                    else f"No encontre la suscripcion #{subscription_id}."
                ),
                reply_markup=self._main_menu_markup(),
            )
            return {"ok": True}
        if command == "/watch":
            try:
                parsed = parse_watch_command(command_payload, self.config.min_discount)
            except ValueError as exc:
                self.notifier.send_message(chat_id, str(exc), reply_markup=self._main_menu_markup())
                return {"ok": True}

            self._create_subscription_from_parsed(chat_id, user_id, parsed)
            return {"ok": True}

        if normalized_text == self.MENU_ADD.casefold():
            self.repository.upsert_conversation_state(
                user_id=user_id,
                flow="create_subscription",
                step="query",
                payload={},
            )
            self.notifier.send_message(
                chat_id,
                "Que producto o tipo de articulo quieres vigilar?\n\nEjemplo: smartwatch samsung",
                reply_markup=self._cancel_markup(),
            )
            return {"ok": True}
        if normalized_text == self.MENU_LIST.casefold():
            self._send_subscription_list(chat_id, user_id)
            return {"ok": True}
        if normalized_text == self.MENU_DELETE.casefold():
            subscriptions = self.repository.list_user_subscriptions(user_id)
            if not subscriptions:
                self.notifier.send_message(
                    chat_id,
                    "No tienes suscripciones activas.",
                    reply_markup=self._main_menu_markup(),
                )
                return {"ok": True}
            self.repository.upsert_conversation_state(
                user_id=user_id,
                flow="delete_subscription",
                step="pick_id",
                payload={},
            )
            self._send_subscription_list(
                chat_id,
                user_id,
                prefix="Estas son tus suscripciones. Escribe el numero que deseas eliminar.",
                reply_markup=self._delete_selection_markup(user_id),
            )
            return {"ok": True}
        if normalized_text == self.MENU_HELP.casefold():
            self.notifier.send_message(chat_id, build_help_text(), reply_markup=self._main_menu_markup())
            return {"ok": True}

        self.notifier.send_message(chat_id, "Selecciona una opcion del menu.", reply_markup=self._main_menu_markup())
        return {"ok": True}

    def _handle_conversation_input(
        self,
        chat_id: str,
        user_id: str,
        text: str,
        state: ConversationState,
    ) -> dict[str, object]:
        """Advance conversational flows using plain-text user replies."""

        if state.flow == "create_subscription":
            return self._handle_create_subscription_flow(chat_id, user_id, text, state)
        if state.flow == "delete_subscription":
            return self._handle_delete_subscription_flow(chat_id, user_id, text)

        self.repository.clear_conversation_state(user_id)
        self.notifier.send_message(chat_id, "Reinicie la conversacion. Intenta de nuevo.", reply_markup=self._main_menu_markup())
        return {"ok": True}

    def _handle_create_subscription_flow(
        self,
        chat_id: str,
        user_id: str,
        text: str,
        state: ConversationState,
    ) -> dict[str, object]:
        """Collect subscription fields in a guided Telegram flow."""

        payload = dict(state.payload)

        if state.step == "query":
            query = text.strip()
            if not query:
                self.notifier.send_message(chat_id, "Escribe una busqueda valida.", reply_markup=self._cancel_markup())
                return {"ok": True}

            payload["query"] = query
            self.repository.upsert_conversation_state(
                user_id=user_id,
                flow=state.flow,
                step="min_discount",
                payload=payload,
            )
            self.notifier.send_message(
                chat_id,
                f"Que descuento minimo esperas para '{query}'?\n\nEscribe solo un numero, por ejemplo 25.",
                reply_markup=self._discount_markup(),
            )
            return {"ok": True}

        if state.step == "min_discount":
            try:
                min_discount = float(text.strip().replace(",", "."))
            except ValueError:
                self.notifier.send_message(
                    chat_id,
                    "Escribe un numero valido. Ejemplo: 25",
                    reply_markup=self._discount_markup(),
                )
                return {"ok": True}

            payload["min_discount"] = min_discount
            self.repository.upsert_conversation_state(
                user_id=user_id,
                flow=state.flow,
                step="exclude_keywords",
                payload=payload,
            )
            self.notifier.send_message(
                chat_id,
                "Que palabras quieres excluir?\n\nEscribe palabras separadas por coma o 'ninguna'.",
                reply_markup=self._exclude_markup(),
            )
            return {"ok": True}

        if state.step == "exclude_keywords":
            raw_value = text.strip()
            exclude_keywords = []
            if raw_value.casefold() not in {
                self.MENU_SKIP_EXCLUDE.casefold(),
                "ninguno",
                "no",
                "-",
            }:
                exclude_keywords = [item.strip() for item in raw_value.split(",") if item.strip()]

            parsed = ParsedSubscriptionCommand(
                query=str(payload.get("query") or "").strip(),
                label=str(payload.get("query") or "").strip(),
                min_discount=float(payload.get("min_discount") or self.config.min_discount),
                require_in_stock=self.config.require_in_stock,
                include_keywords_any=[],
                include_keywords_all=str(payload.get("query") or "").strip().split(),
                exclude_keywords=exclude_keywords,
            )
            self.repository.clear_conversation_state(user_id)
            self._create_subscription_from_parsed(chat_id, user_id, parsed)
            return {"ok": True}

        self.repository.clear_conversation_state(user_id)
        self.notifier.send_message(chat_id, "No pude continuar la conversacion. Intenta de nuevo.", reply_markup=self._main_menu_markup())
        return {"ok": True}

    def _handle_delete_subscription_flow(self, chat_id: str, user_id: str, text: str) -> dict[str, object]:
        """Delete a subscription after the user picks an id from the list."""

        if not text.strip().isdigit():
            self.notifier.send_message(
                chat_id,
                "Escribe solo el numero de la suscripcion que quieres eliminar.",
                reply_markup=self._delete_selection_markup(user_id),
            )
            return {"ok": True}

        subscription_id = int(text.strip())
        deleted = self.repository.delete_subscription(user_id, subscription_id)
        self.repository.clear_conversation_state(user_id)
        self.notifier.send_message(
            chat_id,
            (
                f"Suscripcion #{subscription_id} eliminada."
                if deleted
                else f"No encontre la suscripcion #{subscription_id}."
            ),
            reply_markup=self._main_menu_markup(),
        )
        return {"ok": True}

    def _create_subscription_from_parsed(
        self,
        chat_id: str,
        user_id: str,
        parsed: ParsedSubscriptionCommand,
    ) -> None:
        """Persist a subscription and send a confirmation message."""

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
                f"Excluir: {', '.join(parsed.exclude_keywords) if parsed.exclude_keywords else 'ninguna'}\n"
                f"Stock requerido: {'si' if parsed.require_in_stock else 'no'}"
            ),
            reply_markup=self._main_menu_markup(),
        )

    def _send_subscription_list(
        self,
        chat_id: str,
        user_id: str,
        prefix: str = "Tus suscripciones:",
        reply_markup: dict[str, object] | None = None,
    ) -> None:
        """Send the current subscriptions owned by the user."""

        subscriptions = self.repository.list_user_subscriptions(user_id)
        if not subscriptions:
            self.notifier.send_message(
                chat_id,
                "No tienes suscripciones activas.",
                reply_markup=reply_markup or self._main_menu_markup(),
            )
            return

        lines = [prefix]
        for subscription in subscriptions:
            lines.append(
                f"#{subscription['id']} - {subscription.get('label') or subscription['search_query']} "
                f"(min {subscription.get('min_discount', self.config.min_discount)}%)"
            )
        self.notifier.send_message(chat_id, "\n".join(lines), reply_markup=reply_markup or self._main_menu_markup())

    def _load_state(self, user_id: str) -> ConversationState | None:
        """Load the persisted user conversation state."""

        state = self.repository.get_conversation_state(user_id)
        if not state:
            return None
        payload = state.get("payload")
        return ConversationState(
            flow=str(state.get("flow") or "").strip(),
            step=str(state.get("step") or "").strip(),
            payload=payload if isinstance(payload, dict) else {},
        )

    def _main_menu_markup(self) -> dict[str, object]:
        """Return the persistent main menu keyboard."""

        return {
            "keyboard": [
                [{"text": self.MENU_ADD}, {"text": self.MENU_LIST}],
                [{"text": self.MENU_DELETE}, {"text": self.MENU_HELP}],
            ],
            "resize_keyboard": True,
            "is_persistent": True,
        }

    def _cancel_markup(self) -> dict[str, object]:
        """Return a compact keyboard for active flows."""

        return {
            "keyboard": [
                [{"text": self.MENU_CANCEL}],
            ],
            "resize_keyboard": True,
            "is_persistent": True,
        }

    def _discount_markup(self) -> dict[str, object]:
        """Return preset discount choices plus cancel."""

        return {
            "keyboard": [
                [{"text": self.DISCOUNT_PRESETS[0]}, {"text": self.DISCOUNT_PRESETS[1]}, {"text": self.DISCOUNT_PRESETS[2]}],
                [{"text": self.DISCOUNT_PRESETS[3]}, {"text": self.DISCOUNT_PRESETS[4]}],
                [{"text": self.MENU_CANCEL}],
            ],
            "resize_keyboard": True,
            "is_persistent": True,
        }

    def _exclude_markup(self) -> dict[str, object]:
        """Return helper buttons for the exclude step."""

        return {
            "keyboard": [
                [{"text": self.MENU_SKIP_EXCLUDE}],
                [{"text": self.MENU_CANCEL}],
            ],
            "resize_keyboard": True,
            "is_persistent": True,
        }

    def _delete_selection_markup(self, user_id: str) -> dict[str, object]:
        """Return buttons with the user's subscription ids for guided deletion."""

        subscriptions = self.repository.list_user_subscriptions(user_id)
        id_buttons = [[{"text": str(subscription["id"])}] for subscription in subscriptions[:8]]
        id_buttons.append([{"text": self.MENU_CANCEL}])
        return {
            "keyboard": id_buttons,
            "resize_keyboard": True,
            "is_persistent": True,
        }
