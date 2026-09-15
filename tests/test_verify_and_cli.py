import json

import pytest

from bina_scraper.cli import main
from bina_scraper.verify import check_selectors, format_report, guess_kind


def test_guess_kind(listing_html, item_html):
    assert guess_kind(listing_html) == "listing"
    assert guess_kind(item_html) == "detail"


def test_check_selectors_reports_matches(listing_html):
    reports = {r.key: r for r in check_selectors(listing_html, "listing")}
    assert reports["card"].matched is True
    assert reports["card"].matches["div.items-i"] == 4


def test_report_flags_stale_selectors(listing_html):
    """A page missing the price markup must name the broken selector."""
    broken = listing_html.replace("price-val", "price-value").replace("price-cur", "price-currency")
    report = format_report(broken, "listing")
    assert "Stale selectors" in report
    assert "card_price" in report


def test_report_on_healthy_page_has_no_stale_section(item_html):
    report = format_report(item_html, "detail", "https://bina.az/items/4471693")
    assert "Stale selectors" not in report
    assert "price: 185000.0" in report


def test_check_selectors_rejects_unknown_kind(listing_html):
    with pytest.raises(ValueError):
        check_selectors(listing_html, "nonsense")


def test_cli_parse_listing(tmp_path, listing_html, capsys):
    path = tmp_path / "page.html"
    path.write_text(listing_html, encoding="utf-8")
    assert main(["parse", str(path)]) == 0
    records = json.loads(capsys.readouterr().out)
    assert [r["item_id"] for r in records] == ["4471693", "4471694"]


def test_cli_parse_detail(tmp_path, item_html, capsys):
    path = tmp_path / "item.html"
    path.write_text(item_html, encoding="utf-8")
    assert main(["parse", str(path), "--url", "https://bina.az/items/4471693"]) == 0
    record = json.loads(capsys.readouterr().out)
    assert record["rooms"] == 3
    assert record["city"] == "Bakı"


def test_cli_verify_exit_codes(tmp_path, listing_html, capsys):
    good = tmp_path / "good.html"
    good.write_text(listing_html, encoding="utf-8")
    assert main(["verify-selectors", str(good)]) == 0

    bad = tmp_path / "bad.html"
    bad.write_text(listing_html.replace("price-val", "zzz"), encoding="utf-8")
    assert main(["verify-selectors", str(bad)]) == 1
    capsys.readouterr()


def test_cli_crawl_dry_run_prints_urls(capsys):
    assert main(["crawl", "--max-pages", "3", "--dry-run"]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert out == [
        "https://bina.az/alqi-satqi",
        "https://bina.az/alqi-satqi?page=2",
        "https://bina.az/alqi-satqi?page=3",
    ]


def test_cli_crawl_dry_run_with_filters(capsys):
    assert main(["crawl", "--deal-type", "rent", "--param", "where=baku", "--dry-run"]) == 0
    assert "kiraye?where=baku" in capsys.readouterr().out


def test_cli_rejects_malformed_param():
    with pytest.raises(SystemExit):
        main(["crawl", "--param", "nokey", "--dry-run"])
