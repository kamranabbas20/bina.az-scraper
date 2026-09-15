"""Every CSS selector the scraper depends on, in one place.

bina.az is a server-rendered Rails app and its class names shift from time to
time. Each entry is a *list* of candidate selectors tried in order, so a
markup change usually means adding one string here rather than touching the
parsers. ``python -m bina_scraper verify-selectors <saved.html>`` reports which
candidates actually matched, which is the fastest way to repair this file.

SELECTOR_REVISION is stamped into every scraped record, so a dataset can be
traced back to the selector set that produced it.
"""

from __future__ import annotations

SELECTOR_REVISION = "2025-09-15"

BASE_URL = "https://bina.az"

# Search-result paths per deal type.
SEARCH_PATHS = {
    "sale": "/alqi-satqi",
    "rent": "/kiraye",
    "rent_daily": "/gunluk-kiraye",
}

LISTING = {
    # One card in the search results.
    "card": [
        "div.items-i",
        "div.items_list div.items-i",
        "article.items-i",
    ],
    # The card's link to the detail page; the item id is parsed out of the href.
    "card_link": ["a.item_link", "a[href*='/items/']"],
    "card_title": [".card_params .name", ".card_body .name", "h3"],
    "card_price": [".price-val", ".card_price .price-val", ".price"],
    "card_currency": [".price-cur"],
    # The "3 otaq / 90 m² / 9/16" strip. Read positionally is fragile, so the
    # parser matches each item on its unit instead.
    "card_params": [".name_location li", ".card_params ul li", ".params li"],
    "card_location": [".card_location", ".card_params .card_location"],
    "card_footer": [".card_footer", ".card_params .card_footer"],
    "card_photo": ["img"],
    "card_badges": [".label", ".card_labels span"],
    # Next-page link; absence of it is how pagination terminates. Every
    # candidate must exclude the disabled state, or the last page links to
    # itself and the crawl re-fetches it.
    "pagination_next": [
        "a.next_page:not(.disabled)",
        ".pagination a[rel='next']:not(.disabled)",
        "nav.pagination a.next:not(.disabled)",
    ],
}

DETAIL = {
    "title": ["h1.product-title", ".product-title", "h1"],
    "price": [".product-price__i--bold", ".price-val", ".product-price .price"],
    "price_currency": [".product-price__i--bold .price-cur", ".price-cur"],
    # Property rows render as name/value pairs.
    "property_row": [".product-properties__i", ".product-properties li"],
    "property_name": [".product-properties__i-name", ".name"],
    "property_value": [".product-properties__i-value", ".value"],
    "description": [".product-description__content", ".product-description"],
    "amenity": [".product-extras__i", ".product-extras li"],
    "photo": [
        ".product-photos__slider-nav img",
        ".product-photos img",
        "figure img",
    ],
    "seller_name": [".product-owner__info-name", ".product-owner__info .name"],
    "seller_type": [".product-owner__info-region", ".product-owner__info .region"],
    "stats_row": [".product-statistics__i", ".product-statistics li"],
    "breadcrumb": [".breadcrumbs__i", ".breadcrumb li"],
    # Coordinates live as data attributes on the map container.
    "map": ["#item_map", ".map[data-lat]", "[data-lat][data-lng]"],
}

# Detail-page property labels mapped to Listing field names. Keys are in the
# folded form produced by normalize.fold(), so "Sahə", "sahe" and "SAHƏ" all
# resolve to the same entry. Unmapped labels still land in Listing.properties,
# so nothing is lost when bina.az adds a row.
PROPERTY_LABELS = {
    "kateqoriya": "category",
    "sahe": "area_m2",
    "torpaq sahesi": "land_area_sot",
    "otaq sayi": "rooms",
    "mertebe": "floor",
    "cixaris": "has_bill_of_sale",
    "ipoteka": "has_mortgage",
    "temir": "has_repair",
    "yerlesme": "address",
    "unvan": "address",
}

# Labels whose values are "var"/"yoxdur" booleans.
BOOLEAN_FIELDS = {"has_bill_of_sale", "has_mortgage", "has_repair"}

# Seller-type keywords, in folded form (normalize.fold()).
AGENT_WORDS = ("vasiteci", "agent", "agentlik", "makler")
OWNER_WORDS = ("mulkiyyetci", "sahibi", "owner")

# Deal-type keywords found in breadcrumbs, in folded form. Order matters:
# "Günlük kirayə" contains "kiraye" too, so the more specific word comes first.
DEAL_TYPE_WORDS = (
    ("gunluk", "rent_daily"),
    ("kiraye", "rent"),
    ("alqi-satqi", "sale"),
    ("satqi", "sale"),
)
