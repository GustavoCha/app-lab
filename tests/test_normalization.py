"""Tests for utils/normalization.py."""

from __future__ import annotations

import pytest

from utils.normalization import fix_text_encoding, normalize_product_name, normalize_keywords


class TestFixTextEncoding:
    """Test the fix_text_encoding function."""

    def test_clean_text_passes_through(self) -> None:
        assert fix_text_encoding("televisor oled") == "televisor oled"

    def test_empty_string(self) -> None:
        assert fix_text_encoding("") == ""

    def test_whitespace_only(self) -> None:
        assert fix_text_encoding("   ") == ""

    def test_html_unescape(self) -> None:
        assert fix_text_encoding("smart tv &amp; sound") == "smart tv & sound"

    def test_non_breaking_space(self) -> None:
        assert fix_text_encoding("\xa0test") == "test"

    @pytest.mark.skip(reason="Requires specific mojibake input to trigger")
    def test_mojibake_repair(self) -> None:
        pass  # Real mojibake depends on exact byte sequences


class TestNormalizeProductName:
    """Test the normalize_product_name function."""

    def test_basic_normalization(self) -> None:
        result = normalize_product_name("Televisor OLED 55 Pulgadas")
        assert "televisor" in result
        assert "oled" in result
        assert "55" in result

    def test_removes_pulgadas(self) -> None:
        result = normalize_product_name('Smart TV 50" Pulgadas')
        assert "pulgadas" not in result
        assert "smart" in result
        assert "tv" in result

    def test_removes_accents(self) -> None:
        result = normalize_product_name("Teléfono móvil")
        assert "telefono" in result
        assert "movil" in result

    def test_strips_stop_words(self) -> None:
        result = normalize_product_name("Nuevo Samsung Galaxy Oferta")
        assert "nuevo" not in result
        assert "oferta" not in result
        assert "samsung" in result
        assert "galaxy" in result

    def test_deduplicates_consecutive_tokens(self) -> None:
        result = normalize_product_name("Samsung Samsung Galaxy")
        assert result == "samsung galaxy"

    def test_empty_returns_empty(self) -> None:
        assert normalize_product_name("") == ""

    def test_special_chars_removed(self) -> None:
        result = normalize_product_name("iPhone 15 Pro!!!")
        assert result == "iphone 15 pro"
        assert "!" not in result

    def test_mixed_case_and_spacing(self) -> None:
        result = normalize_product_name("  LAVADORA   SECADORA  ")
        assert result == "lavadora secadora"


class TestNormalizeKeywords:
    """Test the normalize_keywords function."""

    def test_basic_keywords(self) -> None:
        result = normalize_keywords(["Samsung", "LG"])
        assert result == ["samsung", "lg"]

    def test_deduplicates(self) -> None:
        result = normalize_keywords(["Samsung", "samsung", "SAMSUNG"])
        assert result == ["samsung"]

    def test_empty_list(self) -> None:
        assert normalize_keywords([]) == []

    def test_removes_empty_strings(self) -> None:
        result = normalize_keywords([" ", "samsung", ""])
        assert result == ["samsung"]
