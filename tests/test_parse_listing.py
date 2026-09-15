from bina_scraper.parse.listing import find_next_page_url, parse_listing_page


def test_parses_every_real_card(listing_html):
    stubs = parse_listing_page(listing_html)
    # Four .items-i blocks: two real, one duplicate of the first, one ad.
    assert [s.item_id for s in stubs] == ["4471693", "4471694"]


def test_apartment_card_fields(listing_html):
    stub = parse_listing_page(listing_html)[0]
    assert stub.url == "https://bina.az/items/4471693"
    assert stub.title == "3 otaqlı yeni tikili"
    assert (stub.price, stub.currency) == (185000.0, "AZN")
    assert stub.rooms == 3
    assert stub.area_m2 == 90.0
    assert (stub.floor, stub.floors_total) == (9, 16)
    assert stub.location == "Bakı, Nərimanov r., 28 May m."
    assert stub.listed_at == "2025-09-15T00:00:00"
    assert stub.has_bill_of_sale is True
    assert stub.photo_url == "https://bina.az/photos/4471693/thumb.jpg"


def test_house_card_keeps_sot_out_of_area(listing_html):
    stub = parse_listing_page(listing_html)[1]
    assert (stub.price, stub.currency) == (1250000.0, "USD")
    assert stub.rooms == 6
    # "12 sot" is a land area and must not overwrite the 320 m² building area.
    assert stub.area_m2 == 320.0
    assert stub.floor is None
    # data-src images resolve against the base URL.
    assert stub.photo_url == "https://bina.az/photos/4471694/thumb.jpg"


def test_params_are_read_by_unit_not_position(listing_html):
    """A card missing the room count must not shift area into rooms."""
    html = listing_html.replace('<li class="name">6 otaq</li>', "")
    stub = [s for s in parse_listing_page(html) if s.item_id == "4471694"][0]
    assert stub.rooms is None
    assert stub.area_m2 == 320.0


def test_next_page_link(listing_html):
    assert find_next_page_url(listing_html) == "https://bina.az/alqi-satqi?page=2"


def test_last_page_has_no_next(listing_html):
    html = listing_html.replace('class="next_page"', 'class="next_page disabled"')
    assert find_next_page_url(html) is None


def test_empty_page_yields_nothing():
    assert parse_listing_page("<html><body>Nəticə tapılmadı</body></html>") == []
