from datetime import date

import pytest

from bina_scraper.parse import normalize as nz


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("185 000 AZN", (185000.0, "AZN")),
        ("185 000 AZN", (185000.0, "AZN")),  # non-breaking space
        ("1 250 000 USD", (1250000.0, "USD")),
        ("950 ₼", (950.0, "AZN")),
        ("2 400 €", (2400.0, "EUR")),
        ("Razılaşma ilə", (None, None)),
        (None, (None, None)),
    ],
)
def test_parse_price(raw, expected):
    assert nz.parse_price(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [("90 m²", 90.0), ("90,5 m²", 90.5), ("1 200 m²", 1200.0), ("", None), (None, None)],
)
def test_parse_area(raw, expected):
    assert nz.parse_area(raw) == expected


def test_parse_rooms_and_floor():
    assert nz.parse_rooms("3 otaqlı") == 3
    assert nz.parse_floor("9/16") == (9, 16)
    assert nz.parse_floor("9 / 16") == (9, 16)
    assert nz.parse_floor("5") == (5, None)
    assert nz.parse_floor("mərtəbəsiz") == (None, None)


def test_parse_bool():
    assert nz.parse_bool("var") is True
    assert nz.parse_bool("yoxdur") is False
    assert nz.parse_bool("Naməlum") is None


def test_parse_az_date_absolute():
    assert nz.parse_az_date("15 sentyabr 2025") == "2025-09-15T00:00:00"
    assert nz.parse_az_date("15 sentyabr 2025, 14:32") == "2025-09-15T14:32:00"


def test_parse_az_date_relative():
    today = date(2025, 9, 15)
    assert nz.parse_az_date("Bugün, 09:12", today=today) == "2025-09-15T09:12:00"
    assert nz.parse_az_date("Dünən, 23:40", today=today) == "2025-09-14T23:40:00"


def test_parse_az_date_rejects_garbage():
    assert nz.parse_az_date("bir müddət əvvəl") is None
    assert nz.parse_az_date("32 sentyabr 2025") is None


def test_item_id_from_url():
    assert nz.item_id_from_url("https://bina.az/items/4471693") == "4471693"
    assert nz.item_id_from_url("/items/4471693?from=list") == "4471693"
    assert nz.item_id_from_url("/promo/banner") is None
    assert nz.item_id_from_url(None) is None


def test_split_location():
    assert nz.split_location("Bakı, Nərimanov r., 28 May m.") == {
        "city": "Bakı",
        "district": "Nərimanov",
        "metro": "28 May",
        "address": None,
    }
    assert nz.split_location("Bakı, Xətai r.")["metro"] is None
    assert nz.split_location(None)["city"] is None


def test_clean_text_collapses_whitespace():
    assert nz.clean_text("  3   otaq \n ") == "3 otaq"
    assert nz.clean_text("   ") is None
