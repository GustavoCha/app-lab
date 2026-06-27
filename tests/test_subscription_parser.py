"""Tests for services/subscription_parser.py."""

from __future__ import annotations

import pytest

from services.subscription_parser import (
    ParsedSubscriptionCommand,
    build_help_text,
    parse_watch_command,
)


class TestParseWatchCommand:
    """Test the parse_watch_command function."""

    DEFAULT_MIN_DISCOUNT = 60.0

    def test_simple_query(self) -> None:
        result = parse_watch_command("televisor oled", self.DEFAULT_MIN_DISCOUNT)
        assert result.query == "televisor oled"
        assert result.min_discount == self.DEFAULT_MIN_DISCOUNT
        assert result.label == "televisor oled"
        assert result.exclude_keywords == []

    def test_with_min_discount(self) -> None:
        result = parse_watch_command("televisor oled | min=25", self.DEFAULT_MIN_DISCOUNT)
        assert result.query == "televisor oled"
        assert result.min_discount == 25.0

    def test_with_exclude(self) -> None:
        result = parse_watch_command("televisor oled | exclude=soporte,cable", self.DEFAULT_MIN_DISCOUNT)
        assert result.query == "televisor oled"
        assert "soporte" in result.exclude_keywords
        assert "cable" in result.exclude_keywords

    def test_with_label(self) -> None:
        result = parse_watch_command('televisor oled | label=Mi TV', self.DEFAULT_MIN_DISCOUNT)
        assert result.label == "Mi TV"

    def test_with_include_any(self) -> None:
        result = parse_watch_command("notebook | any=lenovo,hp", self.DEFAULT_MIN_DISCOUNT)
        assert result.query == "notebook"
        assert "lenovo" in result.include_keywords_any
        assert "hp" in result.include_keywords_any

    def test_with_include_all(self) -> None:
        result = parse_watch_command("celular | all=samsung,galaxy", self.DEFAULT_MIN_DISCOUNT)
        assert result.query == "celular"
        assert "samsung" in result.include_keywords_all
        assert "galaxy" in result.include_keywords_all

    def test_stock_false(self) -> None:
        result = parse_watch_command("televisor | stock=false", self.DEFAULT_MIN_DISCOUNT)
        assert result.require_in_stock is False

    def test_stock_true_by_default(self) -> None:
        result = parse_watch_command("televisor", self.DEFAULT_MIN_DISCOUNT)
        assert result.require_in_stock is True

    def test_full_command(self) -> None:
        result = parse_watch_command(
            'iphone 17 | min=15 | exclude=funda,cable | label=iPhone 17 | stock=false',
            self.DEFAULT_MIN_DISCOUNT,
        )
        assert result.query == "iphone 17"
        assert result.min_discount == 15.0
        assert result.exclude_keywords == ["funda", "cable"]
        assert result.label == "iPhone 17"
        assert result.require_in_stock is False

    def test_empty_raises_error(self) -> None:
        with pytest.raises(ValueError, match="Uso:"):
            parse_watch_command("", self.DEFAULT_MIN_DISCOUNT)

    def test_whitespace_only_raises_error(self) -> None:
        with pytest.raises(ValueError, match="Uso:"):
            parse_watch_command("   ", self.DEFAULT_MIN_DISCOUNT)

    def test_repeated_options_merge(self) -> None:
        result = parse_watch_command(
            "zapatillas | exclude=rojo | exclude=azul",
            self.DEFAULT_MIN_DISCOUNT,
        )
        assert "rojo" in result.exclude_keywords
        assert "azul" in result.exclude_keywords


class TestParsedSubscriptionCommand:
    """Test the ParsedSubscriptionCommand dataclass."""

    def test_default_values(self) -> None:
        cmd = ParsedSubscriptionCommand(query="test", label="test", min_discount=10.0, require_in_stock=True)
        assert cmd.require_in_stock is True
        assert cmd.include_keywords_any == []
        assert cmd.include_keywords_all == []
        assert cmd.exclude_keywords == []


class TestBuildHelpText:
    """Test build_help_text output."""

    def test_contains_commands(self) -> None:
        text = build_help_text()
        assert "/watch" in text
        assert "/list" in text
        assert "/delete" in text
        assert "/help" in text
        assert "/pause" in text
        assert "/resume" in text
        assert "/edit" in text
