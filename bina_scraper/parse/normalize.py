"""Turn bina.az's Azerbaijani display strings into typed values."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta

# bina.az writes thousands with a non-breaking or thin space: "185 000 AZN".
_SPACE_RE = re.compile(r"[\s    ]+")
_NUM_RE = re.compile(r"-?\d+(?:[.,]\d+)?")

# Keys are folded (see fold()): "iyun" and "iyul" are already ASCII, but
# folding keeps this table usable for any month name that gains a diacritic.
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

# Azerbaijani letters folded to ASCII for matching. Case-insensitive compares
# are not enough on their own: "İpoteka".lower() is "i\u0307poteka" (an i plus a
# combining dot), which matches neither "ipoteka" nor "İpoteka", and the dotless
# "ı" in "Alqı-satqı" never equals an ASCII "i".
_FOLD_MAP = str.maketrans(
    {
        "ə": "e", "Ə": "e",
        "ı": "i", "I": "i",
        "İ": "i", "i": "i",
        "ş": "s", "Ş": "s",
        "ç": "c", "Ç": "c",
        "ö": "o", "Ö": "o",
        "ü": "u", "Ü": "u",
        "ğ": "g", "Ğ": "g",
        "\u0307": "",  # combining dot above, left behind by .lower() on "İ"
    }
)

# Values bina.az uses for yes/no property rows, in folded form.
_TRUE_WORDS = {"var", "beli", "yes", "true"}
_FALSE_WORDS = {"yoxdur", "yox", "xeyr", "no", "false"}


def clean_text(value: str | None) -> str | None:
    """Collapse whitespace and strip; empty becomes None."""
    if value is None:
        return None
    text = unicodedata.normalize("NFC", value)
    text = _SPACE_RE.sub(" ", text).strip()
    return text or None


def fold(value: str | None) -> str:
    """Lowercase and strip Azerbaijani diacritics, for keyword matching.

    "İpoteka" -> "ipoteka", "Alqı-satqı" -> "alqi-satqi". Use this on both sides
    of any comparison against a bina.az label or keyword.
    """
    text = clean_text(value)
    if text is None:
        return ""
    return unicodedata.normalize("NFC", text).translate(_FOLD_MAP).lower()


def _first_number(value: str) -> float | None:
    match = _NUM_RE.search(value)
    if not match:
        return None
    return float(match.group(0).replace(",", "."))


def parse_number(value: str | None) -> float | None:
    """Read a number out of a display string, dropping grouping spaces.

    "185 000" -> 185000.0, "90,5 m²" -> 90.5, "" -> None.
    """
    text = clean_text(value)
    if text is None:
        return None
    # Drop grouping separators between digits ("185 000" / "185,000") but keep
    # a decimal comma ("90,5") intact.
    text = re.sub(r"(?<=\d)[  ,](?=\d{3}\b)", "", text)
    return _first_number(text)


def parse_price(value: str | None) -> tuple[float | None, str | None]:
    """Split "185 000 AZN" into (185000.0, "AZN")."""
    text = clean_text(value)
    if text is None:
        return None, None
    amount = parse_number(text)
    currency = None
    upper = text.upper()
    for code in ("AZN", "USD", "EUR"):
        if code in upper:
            currency = code
            break
    else:
        if "₼" in text:
            currency = "AZN"
        elif "$" in text:
            currency = "USD"
        elif "€" in text:
            currency = "EUR"
    return amount, currency


def parse_area(value: str | None) -> float | None:
    """"90 m²" -> 90.0. Also accepts "90.5 kv.m"."""
    return parse_number(value)


def parse_rooms(value: str | None) -> int | None:
    """"3 otaq" / "3 otaqlı" -> 3."""
    number = parse_number(value)
    return int(number) if number is not None else None


def parse_floor(value: str | None) -> tuple[int | None, int | None]:
    """"9/16" -> (9, 16). A bare "9" -> (9, None)."""
    text = clean_text(value)
    if text is None:
        return None, None
    numbers = [int(float(n.replace(",", "."))) for n in _NUM_RE.findall(text)]
    if not numbers:
        return None, None
    if len(numbers) == 1:
        return numbers[0], None
    return numbers[0], numbers[1]


def parse_bool(value: str | None) -> bool | None:
    """Read bina.az's "var" / "yoxdur" property values."""
    text = clean_text(value)
    if text is None:
        return None
    folded = fold(text)
    if folded in _TRUE_WORDS:
        return True
    if folded in _FALSE_WORDS:
        return False
    return None


def parse_az_date(value: str | None, *, today: date | None = None) -> str | None:
    """Parse bina.az date strings to an ISO 8601 string.

    Handles "15 sentyabr 2025", "15 sentyabr 2025, 14:32", "Bugün, 09:12" and
    "Dünən, 23:40". Returns None when nothing recognisable is present, so a
    format change degrades to a missing field rather than a wrong one.
    """
    text = clean_text(value)
    if text is None:
        return None
    lowered = fold(text)
    today = today or date.today()

    time_match = re.search(r"\b(\d{1,2}):(\d{2})\b", lowered)
    hour, minute = (int(time_match.group(1)), int(time_match.group(2))) if time_match else (0, 0)
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        hour, minute = 0, 0

    if "bugun" in lowered:
        return datetime.combine(today, datetime.min.time()).replace(hour=hour, minute=minute).isoformat()
    if "dunen" in lowered:
        day = today - timedelta(days=1)
        return datetime.combine(day, datetime.min.time()).replace(hour=hour, minute=minute).isoformat()

    match = re.search(r"\b(\d{1,2})\s+([^\W\d_]+)\s+(\d{4})\b", lowered, flags=re.UNICODE)
    if match:
        day_num, month_name, year = int(match.group(1)), match.group(2), int(match.group(3))
        month = AZ_MONTHS.get(month_name)
        if month:
            try:
                return datetime(year, month, day_num, hour, minute).isoformat()
            except ValueError:
                return None

    iso = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", lowered)
    if iso:
        try:
            return datetime(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)), hour, minute).isoformat()
        except ValueError:
            return None
    return None


def item_id_from_url(url: str | None) -> str | None:
    """Pull the numeric id out of "/items/4471693" or its absolute form."""
    if not url:
        return None
    match = re.search(r"/items/(\d+)", url)
    return match.group(1) if match else None


def split_location(location: str | None) -> dict[str, str | None]:
    """Split "Bakı, Nərimanov r., 28 May m." into parts.

    bina.az writes the district with a "r." suffix and the metro with "m.", and
    the leading part is the city. Anything else is kept in ``address``.
    """
    text = clean_text(location)
    if text is None:
        return {"city": None, "district": None, "metro": None, "address": None}

    parts = [p.strip() for p in text.split(",") if p.strip()]
    city = district = metro = None
    rest: list[str] = []
    for index, part in enumerate(parts):
        lowered = part.lower()
        if lowered.endswith(" r.") or lowered.endswith(" rayonu"):
            district = re.sub(r"\s+(r\.|rayonu)$", "", part, flags=re.IGNORECASE)
        elif lowered.endswith(" m.") or lowered.endswith(" metrosu"):
            metro = re.sub(r"\s+(m\.|metrosu)$", "", part, flags=re.IGNORECASE)
        elif index == 0:
            city = part
        else:
            rest.append(part)
    return {
        "city": city,
        "district": district,
        "metro": metro,
        "address": ", ".join(rest) or None,
    }
