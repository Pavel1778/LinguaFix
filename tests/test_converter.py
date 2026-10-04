"""Tests for :mod:`linguafix.converter`."""

from __future__ import annotations

from pathlib import Path

import pytest

from linguafix.converter import LayoutConverter

# (us text, ru text) pairs typed on the same physical keys.
US_TO_RU_CASES = [
    ("ghbdtn", "привет"),
    ("Ghbdtn", "Привет"),
    ("GHBDTN", "ПРИВЕТ"),
    ("vbh", "мир"),
    ("rfr", "как"),
    ("ytn", "нет"),
    ("lf", "да"),
    ("yf", "на"),
    ("nfr", "так"),
    ("rjulf", "когда"),
    ("yfgbcfk", "написал"),
    ("ntrcn", "текст"),
    ("ckjdj", "слово"),
    ("rjvgm.nth", "компьютер"),
    ("ghjuhfvvf", "программа"),
    ("rkfdbfnehf", "клавиатура"),
    ("hfpkj;bnm", "разложить"),
    ("gbcmvj", "письмо"),
    ("jib,rf", "ошибка"),
    ("dct", "все"),
    ("rfrjq", "какой"),
    ("xtkjdtr", "человек"),
    ("ltym", "день"),
    (";bpym", "жизнь"),
    ("dhtvz", "время"),
    ("ghbdtn vbh", "привет мир"),
    ("z", "я"),
    ("b", "и"),
    ("rjv", "ком"),
    ("gj;fkeqcnf", "пожалуйста"),
    ("cgfcb,j", "спасибо"),
    ("nfr;t", "также"),
    ("gjybvfybt", "понимание"),
]

# Individual punctuation mappings from US to RU.
US_TO_RU_PUNCT = [
    (".", "ю"),
    (",", "б"),
    (";", "ж"),
    ("`", "ё"),
    ("[", "х"),
    ("]", "ъ"),
    ("'", "э"),
    ("/", "."),
    ("?", ","),
    ("&", "?"),
    ("^", ":"),
    ("$", ";"),
    ("#", "№"),
    ("@", '"'),
    ("~", "Ё"),
]


@pytest.mark.parametrize(("us_text", "ru_text"), US_TO_RU_CASES)
def test_us_to_ru(converter: LayoutConverter, us_text: str, ru_text: str) -> None:
    assert converter.convert(us_text, "us", "ru") == ru_text


@pytest.mark.parametrize(("us_text", "ru_text"), US_TO_RU_CASES)
def test_ru_to_us_is_inverse(converter: LayoutConverter, us_text: str, ru_text: str) -> None:
    assert converter.convert(ru_text, "ru", "us") == us_text


@pytest.mark.parametrize(("us_char", "ru_char"), US_TO_RU_PUNCT)
def test_punctuation_us_to_ru(converter: LayoutConverter, us_char: str, ru_char: str) -> None:
    assert converter.convert(us_char, "us", "ru") == ru_char


@pytest.mark.parametrize(("us_char", "ru_char"), US_TO_RU_PUNCT)
def test_punctuation_ru_to_us(converter: LayoutConverter, ru_char: str, us_char: str) -> None:
    assert converter.convert(ru_char, "ru", "us") == us_char


def test_round_trip_preserves_text(converter: LayoutConverter) -> None:
    for us_text, _ in US_TO_RU_CASES:
        ru = converter.convert(us_text, "us", "ru")
        assert converter.convert(ru, "ru", "us") == us_text


def test_same_layout_is_identity(converter: LayoutConverter) -> None:
    assert converter.convert("hello", "us", "us") == "hello"


def test_unknown_layout_returns_input(converter: LayoutConverter) -> None:
    assert converter.convert("hello", "us", "xx") == "hello"
    assert converter.convert("hello", "xx", "us") == "hello"


def test_digits_and_spaces_pass_through(converter: LayoutConverter) -> None:
    assert converter.convert("123 456", "us", "ru") == "123 456"


def test_german_layout_available(converter: LayoutConverter) -> None:
    assert "de" in converter.available_layouts
    assert converter.alphabet("de") == "latin"
    # German QWERTZ swaps the physical Y and Z positions.
    assert converter.convert("z", "us", "de") == "y"
    assert converter.convert("y", "us", "de") == "z"
    assert converter.convert("q", "us", "de") == "q"


def test_alphabet_classification(converter: LayoutConverter) -> None:
    assert converter.alphabet("us") == "latin"
    assert converter.alphabet("ru") == "cyrillic"


def test_custom_layout_file(tmp_path: Path) -> None:
    import json

    payload = {
        "layouts": {
            "aa": {"name": "A", "alphabet": "latin", "map": {"a": "x", "b": "y"}},
            "bb": {"name": "B", "alphabet": "latin", "map": {"a": "p", "b": "q"}},
        }
    }
    path = tmp_path / "custom.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    converter = LayoutConverter(str(path))
    assert converter.convert("ab", "aa", "bb") == "pq"


def test_missing_layout_file_is_tolerated() -> None:
    converter = LayoutConverter("/nonexistent/path/layouts.json")
    assert converter.available_layouts == []
    assert converter.convert("abc", "us", "ru") == "abc"


def test_corrupted_layout_file_is_tolerated(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    converter = LayoutConverter(str(path))
    assert converter.available_layouts == []
