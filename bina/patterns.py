"""Text patterns for reading bina.az pages.

Everything site-specific lives here so that a markup change is a one-file fix.
The extraction is deliberately driven by *visible text* (``3 otaq``, ``85 m²``,
``185 000 AZN``) with CSS class names used only as hints, because bina.az
renames classes far more often than it changes the words it prints.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Optional

# --- listing identity -------------------------------------------------------

# Detail-page URLs look like /items/4612345 (optionally with a locale prefix
# such as /ru/items/4612345 and/or a query string).
ITEM_HREF = re.compile(r"/items/(\d+)")

# --- numbers ----------------------------------------------------------------

# Thousands are printed with spaces, including non-breaking and narrow ones.
_SPACES = "    "
_NUM = rf"\d[\d{_SPACES}]*(?:[.,]\d+)?"

CURRENCIES = {
    "AZN": "AZN",
    "₼": "AZN",
    "MANAT": "AZN",
    "USD": "USD",
    "$": "USD",
    "EUR": "EUR",
    "€": "EUR",
}

PRICE = re.compile(rf"({_NUM})\s*(AZN|₼|USD|\$|EUR|€)", re.IGNORECASE)

# "3 otaq", "3 otaqlı" (az) / "3 комн" (ru).
ROOMS = re.compile(r"(\d{1,2})\s*(?:otaq|комн)", re.IGNORECASE)

# "85 m²", "85.5 m2", "85 кв.м".
AREA = re.compile(rf"({_NUM})\s*(?:m²|m2|кв\.?\s*м|kv\.?\s*m)", re.IGNORECASE)

# "5/12 mərtəbə", "5 mərtəbə", "5/12 этаж".
FLOOR_OF = re.compile(r"(\d{1,3})\s*/\s*(\d{1,3})\s*(?:mərtəbə|этаж)", re.IGNORECASE)
FLOOR_ONLY = re.compile(r"(\d{1,3})\s*(?:mərtəbə|этаж)", re.IGNORECASE)

# --- location ---------------------------------------------------------------

# bina.az prints locations as "Nəsimi r.", "Xətai m.", "Bakı", "Masazır q.".
DISTRICT = re.compile(r"([\wĀ-ӿ'’\-]+(?:\s+[\wĀ-ӿ'’\-]+)?)\s+r\.")
METRO = re.compile(r"([\wĀ-ӿ'’\-]+(?:\s+[\wĀ-ӿ'’\-]+)?)\s+m\.")
SETTLEMENT = re.compile(r"([\wĀ-ӿ'’\-]+(?:\s+[\wĀ-ӿ'’\-]+)?)\s+q\.")

# --- dates ------------------------------------------------------------------

AZ_MONTHS = {
    "yanvar": 1,
    "fevral": 2,
    "mart": 3,
    "aprel": 4,
    "may": 5,
    "iyun": 6,
    "iyul": 7,
    "avqust": 8,
    "sentyabr": 9,
    "oktyabr": 10,
    "noyabr": 11,
    "dekabr": 12,
}

RU_MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}

MONTHS = {**AZ_MONTHS, **RU_MONTHS}

_MONTH_ALT = "|".join(sorted(MONTHS, key=len, reverse=True))

# "12 sentyabr 2026", "12 sentyabr" (current year implied), "12 сентября 2026".
TEXTUAL_DATE = re.compile(rf"(\d{{1,2}})\s+({_MONTH_ALT})(?:\s+(\d{{4}}))?", re.IGNORECASE)

# "14.09.2026" / "2026-09-14".
NUMERIC_DATE = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b")
ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")

TODAY_WORDS = ("bugün", "сегодня", "today")
YESTERDAY_WORDS = ("dünən", "вчера", "yesterday")

# Labels that precede a date on a detail page. Order matters: the date a
# listing was *created* is what a time series should use; "updated" (bina.az
# bumps listings) is the fallback, and is flagged as such in the database.
CREATED_LABELS = ("elan yaradıldı", "yaradıldı", "создано", "дата создания")
UPDATED_LABELS = ("yeniləndi", "yenilənib", "обновлено", "обновлён", "обновлен")


def clean_number(raw: str) -> Optional[float]:
    """Turn a printed number (``185 000``, ``85,5``) into a float."""
    text = raw
    for space in _SPACES:
        text = text.replace(space, "")
    text = text.replace(",", ".")
    # A price like "1.250.000" uses dots as thousands separators.
    if text.count(".") > 1:
        text = text.replace(".", "")
    try:
        return float(text)
    except ValueError:
        return None


def parse_date(text: str, today: Optional[dt.date] = None) -> Optional[dt.date]:
    """Find the first date in ``text``, or ``None``.

    Handles the textual Azerbaijani/Russian form bina.az uses, numeric forms,
    and the relative words "today"/"yesterday".
    """
    today = today or dt.date.today()
    lowered = text.lower()

    if any(word in lowered for word in TODAY_WORDS):
        return today
    if any(word in lowered for word in YESTERDAY_WORDS):
        return today - dt.timedelta(days=1)

    match = ISO_DATE.search(text)
    if match:
        return _safe_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))

    match = TEXTUAL_DATE.search(lowered)
    if match:
        day = int(match.group(1))
        month = MONTHS[match.group(2)]
        year = int(match.group(3)) if match.group(3) else today.year
        date = _safe_date(year, month, day)
        # bina.az omits the year on recent listings. A date that lands in the
        # future can only mean the previous year.
        if date and not match.group(3) and date > today:
            date = _safe_date(year - 1, month, day)
        return date

    match = NUMERIC_DATE.search(text)
    if match:
        return _safe_date(int(match.group(3)), int(match.group(2)), int(match.group(1)))

    return None


def _safe_date(year: int, month: int, day: int) -> Optional[dt.date]:
    try:
        return dt.date(year, month, day)
    except ValueError:
        return None
