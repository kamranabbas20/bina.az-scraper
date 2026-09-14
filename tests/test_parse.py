import datetime as dt
import unittest
from pathlib import Path

from bina import patterns as P
from bina.parse import parse_detail_page, parse_listing_page

FIXTURES = Path(__file__).parent / "fixtures"


def read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class ListingPageTests(unittest.TestCase):
    def setUp(self):
        self.listings, self.report = parse_listing_page(
            read("listing_page.html"), "https://bina.az", page=1
        )
        self.by_id = {listing.listing_id: listing for listing in self.listings}

    def test_finds_each_listing_once(self):
        # 4612345 appears in both the VIP block and the results list.
        self.assertEqual(sorted(self.by_id), ["4612345", "4700001", "4700002"])

    def test_ignores_item_paths_outside_anchors(self):
        # The <script> mentions /items/9999999; it is not a link.
        self.assertNotIn("9999999", self.by_id)

    def test_reads_the_four_reported_fields(self):
        listing = self.by_id["4612345"]
        self.assertEqual(listing.price, 185000.0)
        self.assertEqual(listing.currency, "AZN")
        self.assertEqual(listing.area, 96.0)
        self.assertEqual(listing.rooms, 3)
        self.assertEqual(listing.district, "Xətai")
        self.assertEqual(listing.metro, "Xətai")

    def test_floor_pair(self):
        listing = self.by_id["4612345"]
        self.assertEqual((listing.floor, listing.floors_total), (7, 16))

    def test_decimal_comma_area_and_space_thousands(self):
        listing = self.by_id["4700001"]
        self.assertEqual(listing.price, 1250000.0)
        self.assertEqual(listing.area, 310.5)
        self.assertEqual(listing.rooms, 5)

    def test_alternative_card_layout_and_manat_sign(self):
        listing = self.by_id["4700002"]
        self.assertEqual(listing.price, 78500.0)
        self.assertEqual(listing.currency, "AZN")
        self.assertEqual(listing.area, 54.0)
        self.assertEqual(listing.rooms, 2)
        self.assertEqual(listing.district, "Binəqədi")
        self.assertEqual(listing.metro, "Azadlıq prospekti")

    def test_urls_are_absolute(self):
        self.assertEqual(self.by_id["4700002"].url, "https://bina.az/items/4700002")

    def test_page_number_recorded(self):
        self.assertTrue(all(listing.source_page == 1 for listing in self.listings))

    def test_coverage_report_is_clean(self):
        self.assertEqual(self.report.cards_found, 3)
        self.assertEqual(self.report.notes, [])
        for name, ratio in self.report.coverage().items():
            self.assertEqual(ratio, 1.0, name)


class EmptyPageTests(unittest.TestCase):
    def test_page_without_listings_is_flagged(self):
        listings, report = parse_listing_page("<html><body><p>Just a moment…</p></body></html>")
        self.assertEqual(listings, [])
        self.assertTrue(report.notes)


class DetailPageTests(unittest.TestCase):
    def setUp(self):
        self.listing = parse_detail_page(read("detail_page.html"), "4612345")

    def test_prefers_the_creation_date_over_the_bump_date(self):
        self.assertEqual(self.listing.posted_at, dt.date(2026, 3, 3))
        self.assertEqual(self.listing.date_source, "created")

    def test_reads_fields_from_the_detail_page(self):
        self.assertEqual(self.listing.price, 185000.0)
        self.assertEqual(self.listing.area, 96.0)
        self.assertEqual(self.listing.rooms, 3)
        self.assertEqual(self.listing.district, "Xətai")
        self.assertTrue(self.listing.detail_fetched)

    def test_falls_back_to_the_bump_date(self):
        markup = read("detail_page.html").replace("Elan yaradıldı: 3 mart 2026", "")
        listing = parse_detail_page(markup, "4612345")
        self.assertEqual(listing.posted_at, dt.date(2026, 9, 12))
        self.assertEqual(listing.date_source, "updated")

    def test_listing_id_from_canonical_url(self):
        listing = parse_detail_page(read("detail_page.html"))
        self.assertEqual(listing.listing_id, "4612345")


class DateParsingTests(unittest.TestCase):
    TODAY = dt.date(2026, 9, 14)

    def parse(self, text):
        return P.parse_date(text, today=self.TODAY)

    def test_azerbaijani_month(self):
        self.assertEqual(self.parse("12 sentyabr 2026"), dt.date(2026, 9, 12))

    def test_russian_month(self):
        self.assertEqual(self.parse("3 марта 2026"), dt.date(2026, 3, 3))

    def test_missing_year_defaults_to_this_year(self):
        self.assertEqual(self.parse("2 mart"), dt.date(2026, 3, 2))

    def test_missing_year_in_the_future_rolls_back(self):
        # A "20 dekabr" seen in September cannot be three months from now.
        self.assertEqual(self.parse("20 dekabr"), dt.date(2025, 12, 20))

    def test_relative_words(self):
        self.assertEqual(self.parse("Bugün 14:20"), self.TODAY)
        self.assertEqual(self.parse("Dünən"), dt.date(2026, 9, 13))

    def test_numeric_forms(self):
        self.assertEqual(self.parse("14.09.2026"), dt.date(2026, 9, 14))
        self.assertEqual(self.parse("2026-01-31"), dt.date(2026, 1, 31))

    def test_rejects_impossible_dates(self):
        self.assertIsNone(self.parse("31 fevral 2026"))

    def test_no_date(self):
        self.assertIsNone(self.parse("Baxışların sayı: 1 284"))


class NumberTests(unittest.TestCase):
    def test_space_thousands(self):
        self.assertEqual(P.clean_number("1 250 000"), 1250000.0)

    def test_non_breaking_space(self):
        self.assertEqual(P.clean_number("185 000"), 185000.0)

    def test_decimal_comma(self):
        self.assertEqual(P.clean_number("310,5"), 310.5)

    def test_dot_thousands(self):
        self.assertEqual(P.clean_number("1.250.000"), 1250000.0)

    def test_garbage(self):
        self.assertIsNone(P.clean_number("--"))


if __name__ == "__main__":
    unittest.main()
