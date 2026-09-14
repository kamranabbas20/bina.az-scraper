"""Command line interface: ``python -m bina <command>``."""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
from pathlib import Path

from .fetch import Fetcher, FetchConfig
from .parse import parse_detail_page, parse_listing_page
from .report import build_report, write_report
from .scrape import DEFAULT_SECTION, ScrapeOptions, run_scrape
from .store import Store, export_csv

DEFAULT_DB = "data/bina.sqlite3"
DEFAULT_REPORT = "report/bina-report.html"
DEFAULT_DAYS = 365

# Exit code for "the run collected nothing", so an automated run fails loudly
# instead of quietly publishing a stale report.
EXIT_NOTHING_SCRAPED = 2


def main(argv=None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-7s %(message)s",
    )

    if args.command == "scrape":
        return _cmd_scrape(args)
    if args.command == "report":
        return _cmd_report(args)
    if args.command == "inspect":
        return _cmd_inspect(args)
    if args.command == "demo":
        return _cmd_demo(args)
    if args.command == "probe":
        return _cmd_probe(args)

    parser.print_help()
    return 1


# --- commands ---------------------------------------------------------------


def _cmd_scrape(args) -> int:
    since, until = _date_range(args)
    store = Store(args.db)
    options = ScrapeOptions(
        base_url=args.base_url,
        section=args.section,
        query=dict(_parse_query(args.query)),
        start_page=args.start_page,
        max_pages=args.pages,
        details=not args.no_details,
        detail_limit=args.detail_limit,
        since=since,
        until=until,
        resume=not args.no_resume,
        dump_dir=Path(args.dump_dir) if args.dump_dir else None,
        fetch=FetchConfig(
            delay=args.delay,
            obey_robots=not args.ignore_robots,
            user_agent=args.user_agent or FetchConfig.user_agent,
        ),
    )

    print(f"scraping {options.page_url(options.start_page)}")
    print(f"date range for the report: {since} .. {until}")
    summary = run_scrape(store, options)
    print("\n".join(summary.as_lines()))

    if args.csv:
        rows = export_csv(store.iter_listings(since, until, args.include_undated), args.csv)
        print(f"csv written        {args.csv} ({rows} rows)")

    if args.report:
        _write(store, args.report, since, until, args)

    store.close()

    code = _scrape_exit_code(summary)
    if code:
        print(
            "\nERROR: this run collected nothing. Either the site refused us or the "
            "card markup changed — re-run with --dump-dir and use `inspect`.",
            file=sys.stderr,
        )
    return code


def _cmd_report(args) -> int:
    since, until = _date_range(args)
    store = Store(args.db)
    if store.count() == 0:
        print(f"{args.db} has no listings yet — run `python -m bina scrape` first.", file=sys.stderr)
        return 1
    _write(store, args.out, since, until, args)
    store.close()
    return 0


def _cmd_inspect(args) -> int:
    """Parse a saved page and print what came out — the selector debugger."""
    markup = Path(args.path).read_text(encoding="utf-8", errors="replace")

    if args.kind == "detail":
        listing = parse_detail_page(markup, base_url=args.base_url)
        for name, value in vars(listing).items():
            print(f"{name:15} {value}")
        return 0

    listings, report = parse_listing_page(markup, args.base_url)
    print(f"cards found: {report.cards_found}")
    for name, ratio in report.coverage().items():
        print(f"  {name:9} parsed on {ratio:.0%} of cards")
    for note in report.notes:
        print(f"  note: {note}")
    print()
    for listing in listings[: args.limit]:
        print(
            f"{listing.listing_id:>10}  "
            f"{(listing.price and f'{listing.price:>10,.0f}') or '         ?'} "
            f"{listing.currency or '?':4} "
            f"{(listing.area and f'{listing.area:>6.1f}m2') or '      ?'} "
            f"{(listing.rooms and f'{listing.rooms}r') or '?r':3} "
            f"{listing.location_raw or '?'}"
        )
    return 0


def _cmd_probe(args) -> int:
    """Report what a live URL actually returns.

    The point of failure that matters is "the page loaded but held no
    listings", and the only way to tell a client-rendered page from a moved
    path from an anti-bot interstitial is to look at what came back. This
    prints that to stdout so it survives in a CI log.
    """
    import re
    from collections import Counter
    from urllib.parse import urlparse

    from . import patterns as P
    from .fetch import FetchError
    from .minidom import parse_html

    agent = args.user_agent or FetchConfig.user_agent
    fetcher = Fetcher(FetchConfig(delay=0.0, obey_robots=False, user_agent=agent))
    parts = urlparse(args.url)
    origin = f"{parts.scheme}://{parts.netloc}"

    print(f"== robots.txt  {origin}/robots.txt")
    try:
        for line in fetcher.get(f"{origin}/robots.txt").splitlines()[:30]:
            print("   ", line)
    except FetchError as exc:
        print("    unavailable:", exc)
    allowed = Fetcher(FetchConfig(delay=0.0, obey_robots=True, user_agent=agent)).allowed(args.url)
    print(f"    allows this path for our User-Agent: {allowed}")

    print(f"\n== GET {args.url}")
    try:
        markup = fetcher.get(args.url)
    except FetchError as exc:
        print("    failed:", exc)
        return 1

    root = parse_html(markup)
    title = root.find(tag="title")
    anchors = root.find_all(tag="a")
    item_links = [a for a in anchors if P.ITEM_HREF.search(a.get("href") or "")]
    body = root.find(tag="body") or root

    print(f"    bytes: {len(markup)}")
    print(f"    title: {title.text() if title else '(none)'}")
    print(f"    anchors: {len(anchors)}   /items/<id> links: {len(item_links)}")
    print(f"    <script> tags: {len(root.find_all(tag='script'))}")
    print(f"    visible text: {len(body.text())} chars")

    markers = (
        "cloudflare",
        "captcha",
        "turnstile",
        "just a moment",
        "enable javascript",
        "__next_data__",
        "data-react",
        "ng-app",
        "vue",
    )
    found = [m for m in markers if m in markup.lower()]
    print(f"    markers present: {', '.join(found) if found else 'none'}")

    # The histogram is the useful part: if listings moved to another path,
    # their new shape shows up here as the most common repeated link.
    shapes = Counter(
        re.sub(r"\d+", "<n>", (a.get("href") or "").split("?")[0]) for a in anchors
    )
    shapes.pop("", None)
    print("    most common link shapes:")
    for shape, count in shapes.most_common(15):
        print(f"      {count:4}  {shape[:100]}")

    print("\n== first 2000 characters of visible text")
    print(body.text()[:2000])

    print("\n== first 40 lines of HTML")
    for line in markup.splitlines()[:40]:
        print("   ", line[:200])
    return 0


def _cmd_demo(args) -> int:
    """Generate a report from synthetic rows, to check the output layout."""
    from .demo import synthetic_listings

    since, until = _date_range(args)
    listings = synthetic_listings(count=args.count, since=since, until=until, seed=args.seed)
    html_text = build_report(
        listings,
        since=since,
        until=until,
        title="bina.az listings — SYNTHETIC DEMO DATA",
        source_note=(
            "These numbers are randomly generated for layout checking. They are not "
            "bina.az data and must not be read as market figures."
        ),
        extra_notes=[
            "This report was produced by `python -m bina demo`. Every row is synthetic.",
        ],
    )
    path = write_report(args.out, html_text)
    print(f"demo report written to {path} ({len(listings)} synthetic listings)")
    return 0


# --- helpers ----------------------------------------------------------------


def _write(store: Store, out: str, since, until, args) -> None:
    listings = list(store.iter_listings(since, until, getattr(args, "include_undated", False)))
    note = f"Source: {args.db} · {len(listings)} listings in range"
    html_text = build_report(
        listings,
        since=since,
        until=until,
        currency=getattr(args, "currency", "AZN"),
        title=getattr(args, "title", None) or "bina.az listings",
        source_note=note,
    )
    path = write_report(out, html_text)
    print(f"report written      {path}")


def _scrape_exit_code(summary) -> int:
    """Non-zero when a run collected nothing, so CI fails loudly.

    A resumed run that had no pages left to fetch is a legitimate no-op and
    stays at 0; being blocked, refused by robots.txt, or fetching pages that
    yielded no cards is not.
    """
    if summary.stopped_because in {"blocked", "robots.txt"}:
        return EXIT_NOTHING_SCRAPED
    if summary.stopped_because.startswith("fetch failed") and not summary.cards_seen:
        return EXIT_NOTHING_SCRAPED
    if summary.pages_fetched and not summary.cards_seen:
        return EXIT_NOTHING_SCRAPED
    return 0


def _date_range(args) -> tuple[dt.date, dt.date]:
    until = _parse_date(args.until) or dt.date.today()
    since = _parse_date(args.since) or until - dt.timedelta(days=args.days)
    if since > until:
        raise SystemExit(f"--since ({since}) is after --until ({until})")
    return since, until


def _parse_date(value) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        raise SystemExit(f"dates must be YYYY-MM-DD, got {value!r}")


def _parse_query(pairs) -> list[tuple[str, str]]:
    out = []
    for pair in pairs or []:
        if "=" not in pair:
            raise SystemExit(f"--query expects key=value, got {pair!r}")
        key, value = pair.split("=", 1)
        out.append((key, value))
    return out


def _add_range_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--since", help="start of the date range (YYYY-MM-DD)")
    parser.add_argument("--until", help="end of the date range (YYYY-MM-DD), default today")
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_DAYS,
        help=f"range length when --since is omitted (default {DEFAULT_DAYS})",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m bina",
        description="Scrape bina.az listings (price, area, rooms, location) and build an HTML report.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command")

    scrape = sub.add_parser("scrape", help="crawl listings into the SQLite database")
    scrape.add_argument("--db", default=DEFAULT_DB)
    scrape.add_argument("--base-url", default="https://bina.az")
    scrape.add_argument(
        "--section",
        default=DEFAULT_SECTION,
        help="bina.az section path, e.g. alqi-satqi (sale) or kiraye (rent)",
    )
    scrape.add_argument(
        "--query",
        action="append",
        metavar="KEY=VALUE",
        help="extra query parameter, repeatable (e.g. --query city_id=1)",
    )
    scrape.add_argument("--pages", type=int, default=50, help="how many result pages to fetch")
    scrape.add_argument("--start-page", type=int, default=1)
    scrape.add_argument("--delay", type=float, default=1.0, help="seconds between requests")
    scrape.add_argument(
        "--no-details",
        action="store_true",
        help="skip detail pages — much faster, but then no posting dates and no date filter",
    )
    scrape.add_argument(
        "--detail-limit",
        type=int,
        help="cap the number of detail pages per run (they are the slow part)",
    )
    scrape.add_argument("--no-resume", action="store_true", help="re-fetch pages already recorded")
    scrape.add_argument("--ignore-robots", action="store_true", help=argparse.SUPPRESS)
    scrape.add_argument("--user-agent")
    scrape.add_argument("--dump-dir", help="save every fetched page here (for --kind debugging)")
    scrape.add_argument("--csv", help="also export the in-range rows to this CSV path")
    scrape.add_argument("--report", nargs="?", const=DEFAULT_REPORT, help="also build the HTML report")
    scrape.add_argument("--include-undated", action="store_true")
    scrape.add_argument("--currency", default="AZN")
    scrape.add_argument("--title")
    _add_range_args(scrape)

    report = sub.add_parser("report", help="build the HTML report from the database")
    report.add_argument("--db", default=DEFAULT_DB)
    report.add_argument("--out", default=DEFAULT_REPORT)
    report.add_argument("--currency", default="AZN")
    report.add_argument("--title")
    report.add_argument(
        "--include-undated",
        action="store_true",
        help="also include listings with no posting date (they cannot be placed in time)",
    )
    _add_range_args(report)

    inspect = sub.add_parser("inspect", help="show what the parser extracts from a saved page")
    inspect.add_argument("path")
    inspect.add_argument("--kind", choices=("list", "detail"), default="list")
    inspect.add_argument("--base-url", default="https://bina.az")
    inspect.add_argument("--limit", type=int, default=20)

    probe = sub.add_parser(
        "probe", help="report what a live URL actually returns (diagnose a failing scrape)"
    )
    probe.add_argument("url")
    probe.add_argument("--user-agent")
    probe.add_argument("--ignore-robots", action="store_true", help=argparse.SUPPRESS)

    demo = sub.add_parser("demo", help="build a report from synthetic data (layout check)")
    demo.add_argument("--out", default="report/demo-report.html")
    demo.add_argument("--count", type=int, default=1200)
    demo.add_argument("--seed", type=int, default=7)
    _add_range_args(demo)

    return parser


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
