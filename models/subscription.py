"""Subscription model for multi-user alerts."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Subscription:
    """A user-defined product watch configuration."""

    id: int
    user_id: str
    telegram_chat_id: str
    search_query: str
    label: str
    min_discount: float
    require_in_stock: bool
    enabled: bool = True
    include_keywords_any: list[str] = field(default_factory=list)
    include_keywords_all: list[str] = field(default_factory=list)
    exclude_keywords: list[str] = field(default_factory=list)

    @classmethod
    def from_record(cls, record: dict[str, object], chat_id: str) -> "Subscription":
        """Build a subscription from a Supabase row."""

        return cls(
            id=int(record["id"]),
            user_id=str(record["user_id"]),
            telegram_chat_id=str(chat_id),
            search_query=str(record["search_query"]),
            label=str(record.get("label") or record["search_query"]),
            min_discount=float(record.get("min_discount") or 0),
            require_in_stock=bool(record.get("require_in_stock", True)),
            enabled=bool(record.get("enabled", True)),
            include_keywords_any=_as_string_list(record.get("include_keywords_any")),
            include_keywords_all=_as_string_list(record.get("include_keywords_all")),
            exclude_keywords=_as_string_list(record.get("exclude_keywords")),
        )


def _as_string_list(value: object) -> list[str]:
    """Normalize JSON arrays from storage."""

    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []
