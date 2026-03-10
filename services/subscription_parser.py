"""Parse Telegram commands into subscription configs."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ParsedSubscriptionCommand:
    """Structured representation of a /watch command."""

    query: str
    label: str
    min_discount: float
    require_in_stock: bool
    include_keywords_any: list[str] = field(default_factory=list)
    include_keywords_all: list[str] = field(default_factory=list)
    exclude_keywords: list[str] = field(default_factory=list)


def parse_watch_command(command_text: str, default_min_discount: float) -> ParsedSubscriptionCommand:
    """Parse `/watch query | key=value` command syntax."""

    payload = command_text.strip()
    if not payload:
        raise ValueError("Uso: /watch televisor oled | min=25 | exclude=soporte,cable")

    sections = [section.strip() for section in payload.split("|") if section.strip()]
    query = sections[0]
    options: dict[str, str] = {}
    for section in sections[1:]:
        if "=" not in section:
            continue
        key, value = section.split("=", 1)
        options[key.strip().lower()] = value.strip()

    include_all = _parse_csv_or_default(options.get("all"), default=query.split())
    include_any = _parse_csv_or_default(options.get("any"), default=[])
    exclude = _parse_csv_or_default(options.get("exclude"), default=[])
    label = options.get("label", query).strip() or query
    min_discount = float(options.get("min", default_min_discount))
    require_in_stock = options.get("stock", "true").strip().lower() not in {"0", "false", "no"}

    return ParsedSubscriptionCommand(
        query=query,
        label=label,
        min_discount=min_discount,
        require_in_stock=require_in_stock,
        include_keywords_any=include_any,
        include_keywords_all=[token.lower() for token in include_all],
        exclude_keywords=[token.lower() for token in exclude],
    )


def build_help_text() -> str:
    """Return Telegram help text."""

    return (
        "Comandos disponibles:\n\n"
        "/watch <busqueda>\n"
        "Ejemplo: /watch televisor oled | min=25 | exclude=soporte,cable\n\n"
        "/list\n"
        "Muestra tus suscripciones activas.\n\n"
        "/delete <id>\n"
        "Elimina una suscripcion.\n\n"
        "/help\n"
        "Muestra esta ayuda."
    )


def _parse_csv_or_default(value: str | None, default: list[str]) -> list[str]:
    """Parse comma-separated keyword lists."""

    if value is None:
        return [item.strip() for item in default if item.strip()]
    return [item.strip() for item in value.split(",") if item.strip()]
