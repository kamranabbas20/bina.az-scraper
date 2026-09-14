import datetime as dt
import re
import unittest

from bina.demo import synthetic_listings
from bina.models import Listing
from bina.report import MIN_PER_GROUP, Dataset, build_report
from bina.stats import median, nice_ticks, nice_ticks_between, quantile

SINCE = dt.date(2025, 9, 14)
UNTIL = dt.date(2026, 9, 14)


class DatasetTests(unittest.TestCase):
    def test_drops_rows_without_price_or_area(self):
        data = Dataset(
            [
                Listing("1", price=100000.0, area=80.0, currency="AZN"),
                Listing("2", price=None, area=80.0),
                Listing("3", price=100000.0, area=None, currency="AZN"),
            ]
        )
        self.assertEqual(len(data), 1)
        self.assertEqual(data.excluded["no price"], 1)
        self.assertEqual(data.excluded["no area"], 1)

    def test_drops_other_currencies(self):
        data = Dataset([Listing("1", price=90000.0, area=80.0, currency="USD")])
        self.assertEqual(len(data), 0)
        self.assertEqual(data.excluded["priced in USD"], 1)

    def test_drops_implausible_values(self):
        data = Dataset(
            [
                Listing("1", price=5.0, area=80.0, currency="AZN"),
                Listing("2", price=100000.0, area=4.0, currency="AZN"),
            ]
        )
        self.assertEqual(len(data), 0)
        self.assertEqual(sum(data.excluded.values()), 2)

    def test_enforces_the_date_range(self):
        data = Dataset(
            [
                Listing("in", price=1e5, area=80.0, currency="AZN", posted_at=dt.date(2026, 1, 1)),
                Listing("out", price=1e5, area=80.0, currency="AZN", posted_at=dt.date(2020, 1, 1)),
            ],
            since=SINCE,
            until=UNTIL,
        )
        self.assertEqual([row.listing_id for row in data.rows], ["in"])
        self.assertEqual(data.excluded["posted before the range"], 1)

    def test_months_are_gap_filled(self):
        data = Dataset(
            [
                Listing("a", price=1e5, area=80.0, currency="AZN", posted_at=dt.date(2026, 1, 5)),
                Listing("b", price=1e5, area=80.0, currency="AZN", posted_at=dt.date(2026, 4, 5)),
            ]
        )
        keys = [key for key, _ in data.by_month()]
        self.assertEqual(keys, ["2026-01", "2026-02", "2026-03", "2026-04"])
        self.assertEqual([len(rows) for _, rows in data.by_month()], [1, 0, 0, 1])

    def test_districts_ordered_by_listing_count(self):
        rows = [
            Listing(str(i), price=1e5, area=80.0, currency="AZN", district="Nəsimi")
            for i in range(5)
        ] + [Listing("x", price=1e5, area=80.0, currency="AZN", district="Xəzər")]
        data = Dataset(rows)
        self.assertEqual([name for name, _ in data.by_district()], ["Nəsimi", "Xəzər"])


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.html = build_report(
            synthetic_listings(count=600, since=SINCE, until=UNTIL, seed=1),
            since=SINCE,
            until=UNTIL,
        )

    def test_is_a_complete_document(self):
        self.assertTrue(self.html.startswith("<!doctype html>"))
        self.assertIn("</html>", self.html)

    def test_has_every_section(self):
        for title in (
            "Median price per m² by district",
            "Listings by room count",
            "Listings posted per month",
            "Median price per m² by month",
            "Area against price",
            "How to read this",
        ):
            self.assertIn(title, self.html, title)

    def test_charts_rendered_rather_than_empty(self):
        self.assertNotIn('class="empty"', self.html)
        self.assertGreaterEqual(self.html.count("<svg"), 5)

    def test_every_chart_has_a_table_view(self):
        self.assertEqual(self.html.count("Show data"), self.html.count("<svg"))

    def test_states_the_snapshot_caveat(self):
        self.assertIn("no archive", self.html)

    def test_theme_tokens_defined_for_both_modes(self):
        self.assertIn("prefers-color-scheme: dark", self.html)
        self.assertIn(':root[data-theme="dark"]', self.html)
        # Every series colour is defined on bare :root as well.
        for role in ("--series-1", "--series-2", "--series-3"):
            self.assertGreaterEqual(self.html.count(role + ":"), 3)

    def test_no_dual_axis_or_external_requests(self):
        self.assertNotIn("http://", self.html.replace("http://www.w3.org", ""))
        self.assertNotIn("<script src", self.html)

    def test_empty_input_does_not_crash(self):
        html = build_report([], since=SINCE, until=UNTIL)
        self.assertIn('class="empty"', html)
        self.assertIn("0 listings", html)

    def test_escapes_untrusted_text(self):
        # Enough rows to clear MIN_PER_GROUP, so the hostile district really
        # reaches the district chart, its table view and the listings table.
        rows = [
            Listing(
                str(index),
                price=1e5,
                area=80.0,
                rooms=3,
                currency="AZN",
                district="<script>alert(1)</script>",
                location_raw='"><img onerror=x>',
                posted_at=dt.date(2026, 1, 1),
            )
            for index in range(MIN_PER_GROUP)
        ]
        html = build_report(rows, since=SINCE, until=UNTIL)
        self.assertIn("Median price per m² by district", html)
        self.assertNotIn('class="empty"', html.split("Listings by room count")[0])
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertNotIn('"><img onerror=x>', html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)

    def test_numbers_are_grouped_for_reading(self):
        self.assertTrue(re.search(r"\d\s\d{3}", self.html))


class StatsTests(unittest.TestCase):
    def test_median_odd_and_even(self):
        self.assertEqual(median([3, 1, 2]), 2)
        self.assertEqual(median([1, 2, 3, 4]), 2.5)

    def test_median_ignores_none(self):
        self.assertEqual(median([1, None, 3]), 2)

    def test_median_of_nothing(self):
        self.assertIsNone(median([]))
        self.assertIsNone(median([None]))

    def test_quantile(self):
        self.assertEqual(quantile([1, 2, 3, 4, 5], 0.0), 1)
        self.assertEqual(quantile([1, 2, 3, 4, 5], 0.5), 3)
        self.assertEqual(quantile([1, 2, 3, 4, 5], 1.0), 5)

    def test_ticks_cover_the_maximum(self):
        for maximum in (1, 7, 93, 1250, 185000, 0.4):
            ticks = nice_ticks(maximum)
            self.assertEqual(ticks[0], 0.0)
            self.assertGreaterEqual(ticks[-1], maximum, maximum)
            self.assertLessEqual(len(ticks), 12, maximum)

    def test_ticks_handle_zero(self):
        self.assertEqual(nice_ticks(0), [0.0, 1.0])

    def test_non_zero_scale_brackets_the_data(self):
        ticks = nice_ticks_between(1950, 2260)
        self.assertLessEqual(ticks[0], 1950)
        self.assertGreaterEqual(ticks[-1], 2260)
        self.assertGreater(ticks[0], 0)  # does not collapse to a zero baseline

    def test_non_zero_scale_handles_a_flat_series(self):
        ticks = nice_ticks_between(2000, 2000)
        self.assertGreater(ticks[-1], ticks[0])


if __name__ == "__main__":
    unittest.main()
