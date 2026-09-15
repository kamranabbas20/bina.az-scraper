"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import selectors as sel
from .config import Settings, load_settings
from .crawl import Crawler, build_search_url
from .fetchers import FetchError, build_fetcher
from .history import (
    format_timeline,
    group_by_item,
    load_observations,
    price_changes,
    summarize,
)
from .logging_conf import configure_logging
from .parse.detail import parse_detail
from .parse.listing import parse_listing_page
from .store.jsonl import MODES
from .verify import format_report, guess_kind


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-c", "--config", help="YAML config file")
    parser.add_argument("--log-level", default=None, help="DEBUG, INFO, WARNING, ERROR")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bina-scraper",
        description="Scrape property listings from bina.az into JSON Lines.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    crawl = sub.add_parser("crawl", help="walk search-result pages and write listings")
    _add_common(crawl)
    crawl.add_argument("--deal-type", choices=sorted(sel.SEARCH_PATHS), default=None)
    crawl.add_argument("--search-path", default=None, help="override the search path entirely")
    crawl.add_argument(
        "--param",
        action="append",
        default=None,
        metavar="KEY=VALUE",
        help="query-string filter, repeatable (e.g. --param room_ids[]=2)",
    )
    crawl.add_argument("--start-page", type=int, default=None)
    crawl.add_argument("--max-pages", type=int, default=None)
    crawl.add_argument("--max-items", type=int, default=None)
    crawl.add_argument("--fetcher", choices=("http", "browser"), default=None)
    crawl.add_argument("--delay", type=float, default=None, help="seconds between requests")
    crawl.add_argument("-o", "--output", default=None, help="JSONL output path")
    crawl.add_argument(
        "--mode",
        dest="store_mode",
        choices=MODES,
        default=None,
        help=(
            "observations: one row per listing per crawl (default); "
            "changes: one row per listing per change; "
            "unique: one row per listing ever, no history"
        ),
    )
    crawl.add_argument("--save-html-dir", default=None, help="also keep the raw HTML here")
    crawl.add_argument("--proxy", default=None)
    crawl.add_argument("--contact-email", default=None, help="goes into the User-Agent")
    crawl.add_argument(
        "--no-details",
        dest="fetch_details",
        action="store_false",
        default=None,
        help="card fields only; one request per page instead of per listing",
    )
    crawl.add_argument(
        "--no-resume",
        dest="resume",
        action="store_false",
        default=None,
        help="ignore what the output file already holds",
    )
    crawl.add_argument(
        "--ignore-robots",
        dest="respect_robots",
        action="store_false",
        default=None,
        help="skip the robots.txt check (you are responsible for this)",
    )
    crawl.add_argument("--dry-run", action="store_true", help="print the URLs and exit")

    fetch = sub.add_parser("fetch", help="fetch one URL and print the parsed record as JSON")
    _add_common(fetch)
    fetch.add_argument("url", help="an item URL, or a search-results URL")
    fetch.add_argument("--fetcher", choices=("http", "browser"), default=None)
    fetch.add_argument("--save-html", default=None, help="write the raw HTML here too")

    parse = sub.add_parser("parse", help="parse a saved HTML file (no network)")
    _add_common(parse)
    parse.add_argument("path", help="saved .html file")
    parse.add_argument("--kind", choices=("listing", "detail"), default=None)
    parse.add_argument("--url", default="https://bina.az/items/0", help="URL the file came from")

    history = sub.add_parser(
        "history", help="query an observation log: summary, timelines, price changes"
    )
    _add_common(history)
    history.add_argument("path", help="JSONL file written by crawl")
    history.add_argument("--item", default=None, help="show one listing's timeline")
    history.add_argument(
        "--price-changes", action="store_true", help="list every price move in the log"
    )
    history.add_argument("--json", action="store_true", help="emit JSON instead of text")

    verify = sub.add_parser(
        "verify-selectors", help="report which selectors still match a saved page"
    )
    _add_common(verify)
    verify.add_argument("path", help="saved .html file")
    verify.add_argument("--kind", choices=("listing", "detail"), default=None)
    verify.add_argument("--url", default="https://bina.az/items/0")
    return parser


def _stub_dict(stub) -> dict:
    """ListingStub uses __slots__, so dataclasses.asdict is not available."""
    return {field: getattr(stub, field) for field in stub.__slots__}


def _params_to_dict(pairs: list[str] | None) -> dict[str, str] | None:
    if not pairs:
        return None
    out: dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit(f"--param expects KEY=VALUE, got {pair!r}")
        key, value = pair.split("=", 1)
        out[key] = value
    return out


def _settings_from_args(args: argparse.Namespace) -> Settings:
    overrides = {
        key: getattr(args, key, None)
        for key in (
            "deal_type",
            "search_path",
            "start_page",
            "max_pages",
            "max_items",
            "fetcher",
            "delay",
            "output",
            "store_mode",
            "save_html_dir",
            "proxy",
            "contact_email",
            "fetch_details",
            "resume",
            "respect_robots",
            "log_level",
        )
    }
    params = _params_to_dict(getattr(args, "param", None))
    if params:
        overrides["query_params"] = params
    return load_settings(getattr(args, "config", None), **overrides)


def cmd_crawl(args: argparse.Namespace) -> int:
    settings = _settings_from_args(args)
    if args.dry_run:
        for page in range(settings.start_page, settings.start_page + settings.max_pages):
            print(build_search_url(settings, page))
        print(
            f"fetcher={settings.fetcher} details={settings.fetch_details} "
            f"delay={settings.delay}s output={settings.output}",
            file=sys.stderr,
        )
        return 0
    stats = Crawler(settings).run()
    print(stats.summary(), file=sys.stderr)
    if stats.blocked:
        return 2
    return 0 if stats.records_written or stats.skipped_duplicates else 1


def cmd_fetch(args: argparse.Namespace) -> int:
    settings = _settings_from_args(args)
    fetcher = build_fetcher(settings)
    try:
        result = fetcher.get(args.url)
    except FetchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        fetcher.close()

    if args.save_html:
        Path(args.save_html).write_text(result.html, encoding="utf-8")

    if "/items/" in args.url:
        record = parse_detail(result.html, result.final_url or args.url).to_dict()
    else:
        record = [_stub_dict(stub) for stub in parse_listing_page(result.html)]
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    records = load_observations(args.path)
    if not records:
        print(f"{args.path} holds no usable observations", file=sys.stderr)
        return 1

    if args.item:
        observations = group_by_item(records).get(str(args.item), [])
        if not observations:
            print(f"no observations for item {args.item}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(observations, ensure_ascii=False, indent=2))
        else:
            print(format_timeline(str(args.item), observations))
        return 0

    if args.price_changes:
        changes = price_changes(records)
        if args.json:
            print(
                json.dumps(
                    [
                        {
                            "item_id": c.item_id,
                            "old_price": c.old_price,
                            "new_price": c.new_price,
                            "currency": c.currency,
                            "delta": c.delta,
                            "pct": c.pct,
                            "previous_at": c.previous_at,
                            "observed_at": c.observed_at,
                        }
                        for c in changes
                    ],
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            for change in changes:
                print(change.describe())
            noun = "change" if len(changes) == 1 else "changes"
            print(f"{len(changes)} price {noun}", file=sys.stderr)
        return 0

    summary = summarize(records)
    if args.json:
        print(json.dumps(summary.__dict__, ensure_ascii=False, indent=2))
    else:
        print(summary.describe())
    return 0


def cmd_parse(args: argparse.Namespace) -> int:
    html = Path(args.path).read_text(encoding="utf-8", errors="replace")
    kind = args.kind or guess_kind(html)
    if kind == "detail":
        print(json.dumps(parse_detail(html, args.url).to_dict(), ensure_ascii=False, indent=2))
    else:
        stubs = parse_listing_page(html)
        print(json.dumps([_stub_dict(s) for s in stubs], ensure_ascii=False, indent=2))
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    html = Path(args.path).read_text(encoding="utf-8", errors="replace")
    kind = args.kind or guess_kind(html)
    report = format_report(html, kind, args.url)
    print(report)
    return 1 if "Stale selectors" in report else 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(getattr(args, "log_level", None) or "INFO")
    handlers = {
        "crawl": cmd_crawl,
        "fetch": cmd_fetch,
        "parse": cmd_parse,
        "history": cmd_history,
        "verify-selectors": cmd_verify,
    }
    return handlers[args.command](args)
