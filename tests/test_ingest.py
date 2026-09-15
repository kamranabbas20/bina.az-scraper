"""Tests for `bina ingest` — the offline path, for machines with no access."""

from __future__ import annotations

import contextlib
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path

from bina.cli import main

FIXTURES = Path(__file__).parent / "fixtures"


class IngestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.db = self.dir / "ingest.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, argv) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(argv)
        return code, out.getvalue(), err.getvalue()

    def rows(self) -> list[sqlite3.Row]:
        db = sqlite3.connect(self.db)
        db.row_factory = sqlite3.Row
        try:
            return list(db.execute("SELECT * FROM listings ORDER BY listing_id"))
        finally:
            db.close()

    def test_ingests_a_directory_of_pages(self):
        code, out, _ = self.run_cli(["ingest", str(FIXTURES), "--db", str(self.db)])
        self.assertEqual(code, 0, out)
        self.assertIn("results pages      1 (3 cards)", out)
        self.assertIn("detail pages       1 (1 yielded a date)", out)
        self.assertEqual(len(self.rows()), 3)

    def test_detail_and_listing_data_merge_whichever_is_read_first(self):
        # Alphabetically the detail page is read before the results page, so
        # this is the order that would lose the date to a careless upsert.
        self.run_cli(["ingest", str(FIXTURES), "--db", str(self.db)])
        merged = {row["listing_id"]: row for row in self.rows()}["4612345"]
        self.assertEqual(merged["posted_at"], "2026-03-03")
        self.assertEqual(merged["date_source"], "created")
        self.assertEqual(merged["price"], 185000.0)
        self.assertEqual(merged["rooms"], 3)

    def test_recovers_the_listing_id_from_the_filename(self):
        # A page saved from a browser can lose its canonical link.
        markup = (FIXTURES / "detail_page.html").read_text(encoding="utf-8")
        stripped = markup.replace('<link rel="canonical" href="https://bina.az/items/4612345">', "")
        saved = self.dir / "item-4612345.html"
        saved.write_text(stripped, encoding="utf-8")

        code, out, _ = self.run_cli(["ingest", str(saved), "--db", str(self.db)])
        self.assertEqual(code, 0, out)
        self.assertIn("detail for 4612345", out)
        self.assertEqual(self.rows()[0]["listing_id"], "4612345")

    def test_counts_unrecognised_files_without_failing_the_run(self):
        (self.dir / "junk.html").write_text("<html><body><p>hello</p></body></html>", encoding="utf-8")
        (self.dir / "listing.html").write_text(
            (FIXTURES / "listing_page.html").read_text(encoding="utf-8"), encoding="utf-8"
        )
        code, out, err = self.run_cli(["ingest", str(self.dir), "--db", str(self.db)])
        self.assertEqual(code, 0)
        self.assertIn("unrecognised       1", out)
        self.assertIn("nothing recognised", err)
        self.assertEqual(len(self.rows()), 3)

    def test_nothing_parsed_is_a_parse_mismatch(self):
        (self.dir / "junk.html").write_text("<html><body><p>hello</p></body></html>", encoding="utf-8")
        code, _, err = self.run_cli(["ingest", str(self.dir), "--db", str(self.db)])
        self.assertEqual(code, 3)
        self.assertIn("none of those files parsed", err)

    def test_missing_path_is_reported(self):
        code, _, err = self.run_cli(["ingest", str(self.dir / "nope"), "--db", str(self.db)])
        self.assertEqual(code, 2)
        self.assertIn("not found", err)

    def test_builds_the_report_and_csv_offline(self):
        report = self.dir / "report.html"
        csv_path = self.dir / "out.csv"
        code, out, _ = self.run_cli(
            [
                "ingest",
                str(FIXTURES),
                "--db",
                str(self.db),
                "--report",
                str(report),
                "--csv",
                str(csv_path),
                "--include-undated",
                "--since",
                "2026-01-01",
                "--until",
                "2026-12-31",
            ]
        )
        self.assertEqual(code, 0, out)
        self.assertTrue(report.exists())
        self.assertIn("bina.az listings", report.read_text(encoding="utf-8"))
        self.assertIn("price_per_m2", csv_path.read_text(encoding="utf-8"))

    def test_ingest_is_repeatable(self):
        self.run_cli(["ingest", str(FIXTURES), "--db", str(self.db)])
        self.run_cli(["ingest", str(FIXTURES), "--db", str(self.db)])
        self.assertEqual(len(self.rows()), 3)


if __name__ == "__main__":
    unittest.main()
