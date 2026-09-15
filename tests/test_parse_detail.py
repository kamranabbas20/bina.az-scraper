from bina_scraper.parse.detail import parse_detail

URL = "https://bina.az/items/4471693"


def test_core_fields(item_html):
    listing = parse_detail(item_html, URL)
    assert listing.item_id == "4471693"
    assert listing.title.startswith("3 otaqlı yeni tikili")
    assert (listing.price, listing.currency) == (185000.0, "AZN")
    assert listing.category == "Yeni tikili"
    assert listing.rooms == 3
    assert listing.area_m2 == 90.0
    assert (listing.floor, listing.floors_total) == (9, 16)


def test_boolean_properties(item_html):
    listing = parse_detail(item_html, URL)
    assert listing.has_bill_of_sale is True
    assert listing.has_mortgage is False
    assert listing.has_repair is True


def test_location_is_split(item_html):
    listing = parse_detail(item_html, URL)
    assert listing.city == "Bakı"
    assert listing.district == "Nərimanov"
    assert listing.metro == "28 May"
    assert (listing.latitude, listing.longitude) == (40.4093, 49.8671)


def test_photos_deduped_and_absolute(item_html):
    listing = parse_detail(item_html, URL)
    assert listing.photo_urls == [
        "https://bina.az/photos/4471693/1.jpg",
        "https://bina.az/photos/4471693/2.jpg",
        "https://bina.az/photos/4471693/3.jpg",
    ]
    assert listing.photo_count == 3


def test_amenities_description_and_seller(item_html):
    listing = parse_detail(item_html, URL)
    assert listing.amenities == ["Kombi", "Mebel", "Kondisioner"]
    assert "Metroya 5 dəqiqə" in listing.description
    assert listing.seller_name == "Elçin"
    assert listing.seller_type == "agent"


def test_statistics(item_html):
    listing = parse_detail(item_html, URL)
    assert listing.view_count == 1284
    assert listing.listed_at == "2025-09-15T00:00:00"
    assert listing.updated_at is not None


def test_unmapped_properties_are_kept(item_html):
    """An unmodelled label must survive in .properties rather than vanish."""
    listing = parse_detail(item_html, URL)
    assert listing.properties["Qazanc növü"] == "Naməlum"
    assert listing.properties["_selector_revision"]


def test_deal_type_from_breadcrumbs(item_html):
    assert parse_detail(item_html, URL).deal_type == "sale"
    rent = parse_detail(item_html, "https://bina.az/kiraye/items/4471693")
    assert rent.deal_type == "rent"


def test_missing_markup_degrades_to_none():
    """A changed page must cost fields, not raise."""
    listing = parse_detail("<html><body><h1>Boş</h1></body></html>", URL)
    assert listing.item_id == "4471693"
    assert listing.price is None
    assert listing.rooms is None
    assert listing.photo_urls == []


def test_id_falls_back_to_url_then_argument():
    listing = parse_detail("<html></html>", "https://bina.az/x", item_id="99")
    assert listing.item_id == "99"
    assert parse_detail("<html></html>", "https://bina.az/x").item_id == ""


def test_daily_rent_beats_plain_rent(item_html):
    """"/gunluk-kiraye" contains "kiraye"; the specific match must win."""
    from_url = parse_detail(item_html, "https://bina.az/gunluk-kiraye/items/1")
    assert from_url.deal_type == "rent_daily"

    html = item_html.replace("Alqı-satqı", "Günlük kirayə")
    from_crumbs = parse_detail(html, "https://bina.az/items/1")
    assert from_crumbs.deal_type == "rent_daily"


def test_dotted_capital_i_label_matches(item_html):
    """"İpoteka".lower() is not "ipoteka"; folding must bridge that."""
    listing = parse_detail(item_html, URL)
    assert listing.has_mortgage is False
    assert "İpoteka" in listing.properties
