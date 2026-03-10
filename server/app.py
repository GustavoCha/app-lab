"""Flask app for Vercel routes."""

from __future__ import annotations

from flask import Flask, jsonify, request

from config.config import load_config
from database.supabase_repository import SupabaseRepository
from notifier.telegram_notifier import TelegramNotifier
from services.alert_engine import run_alert_cycle
from services.telegram_bot_service import TelegramBotService


app = Flask(__name__)


@app.get("/api/health")
def health() -> object:
    """Simple health endpoint."""

    return jsonify({"ok": True})


@app.post("/api/telegram-webhook")
def telegram_webhook() -> object:
    """Telegram webhook endpoint."""

    config = load_config()
    if config.telegram_webhook_secret:
        header_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if header_secret != config.telegram_webhook_secret:
            return jsonify({"ok": False, "error": "unauthorized"}), 401

    repository = SupabaseRepository(config)
    notifier = TelegramNotifier(bot_token=config.telegram_bot_token, timeout=config.request_timeout)
    service = TelegramBotService(config, repository, notifier)
    payload = request.get_json(silent=True) or {}
    result = service.handle_update(payload)
    return jsonify(result)


@app.get("/api/cron/run-scraper")
def run_scraper() -> object:
    """Protected cron endpoint used by Vercel Cron."""

    config = load_config()
    if config.cron_secret:
        auth_header = request.headers.get("Authorization", "")
        if auth_header != f"Bearer {config.cron_secret}":
            return jsonify({"ok": False, "error": "unauthorized"}), 401

    stats = run_alert_cycle(config)
    return jsonify({"ok": True, "stats": stats})
