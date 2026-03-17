"""Parse Telegram commands into subscription configs."""

from __future__ import annotations

from dataclasses import dataclass, field

from utils.normalization import normalize_keywords


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
    repeated_options: dict[str, list[str]] = {
        "any": [],
        "all": [],
        "exclude": [],
    }
    for section in sections[1:]:
        if "=" not in section:
            continue
        key, value = section.split("=", 1)
        normalized_key = key.strip().lower()
        normalized_value = value.strip()
        if normalized_key in repeated_options:
            repeated_options[normalized_key].append(normalized_value)
            continue
        options[normalized_key] = normalized_value

    include_all = normalize_keywords(
        _parse_repeated_csv_or_default(repeated_options["all"], default=query.split())
    )
    include_any = normalize_keywords(
        _parse_repeated_csv_or_default(repeated_options["any"], default=[])
    )
    exclude = normalize_keywords(
        _parse_repeated_csv_or_default(repeated_options["exclude"], default=[])
    )
    label = options.get("label", query).strip() or query
    min_discount = float(options.get("min", default_min_discount))
    require_in_stock = options.get("stock", "true").strip().lower() not in {"0", "false", "no"}

    return ParsedSubscriptionCommand(
        query=query,
        label=label,
        min_discount=min_discount,
        require_in_stock=require_in_stock,
        include_keywords_any=include_any,
        include_keywords_all=include_all,
        exclude_keywords=exclude,
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


def _parse_repeated_csv_or_default(values: list[str], default: list[str]) -> list[str]:
    """Parse one or more comma-separated option occurrences."""

    if not values:
        return [item.strip() for item in default if item.strip()]

    parsed: list[str] = []
    for value in values:
        parsed.extend(item.strip() for item in value.split(",") if item.strip())
    return parsed
