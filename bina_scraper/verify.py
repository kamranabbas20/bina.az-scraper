"""Check the selectors in selectors.py against a saved HTML page.

bina.az cannot be fetched from every network, and its markup changes without
notice, so selector repair is done offline: save a page in a browser, run this,
and every candidate selector reports how many nodes it matched.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import selectors as sel
from .parse.detail import parse_detail
from .parse.listing import find_next_page_url, parse_listing_page
from .parse.soup import make_soup


@dataclass
class SelectorReport:
    group: str
    key: str
    matches: dict[str, int]

    @property
    def matched(self) -> bool:
        return any(count > 0 for count in self.matches.values())


def check_selectors(html: str, kind: str) -> list[SelectorReport]:
    """Count matches for every candidate selector in the chosen group."""
    soup = make_soup(html)
    groups = {"listing": sel.LISTING, "detail": sel.DETAIL}
    if kind not in groups:
        raise ValueError(f"kind must be one of {sorted(groups)}, got {kind!r}")

    reports: list[SelectorReport] = []
    for key, candidates in groups[kind].items():
        reports.append(
            SelectorReport(
                group=kind,
                key=key,
                matches={candidate: len(soup.select(candidate)) for candidate in candidates},
            )
        )
    return reports


def guess_kind(html: str) -> str:
    """Guess whether a saved page is a search-results page or an item page."""
    detail_hits = sum(html.count(marker) for marker in ("product-properties", "product-title", "product-photos"))
    listing_hits = sum(html.count(marker) for marker in ("items-i", "item_link"))
    return "detail" if detail_hits > listing_hits else "listing"


def format_report(html: str, kind: str, url: str = "https://bina.az/items/0") -> str:
    """Human-readable report, including what the parsers actually extracted."""
    lines: list[str] = [f"selector revision: {sel.SELECTOR_REVISION}", f"page kind: {kind}", ""]
    reports = check_selectors(html, kind)
    broken = [r for r in reports if not r.matched]

    for report in reports:
        status = "OK " if report.matched else "MISS"
        lines.append(f"[{status}] {report.key}")
        for candidate, count in report.matches.items():
            marker = "*" if count else " "
            lines.append(f"       {marker} {count:>4} x  {candidate}")
    lines.append("")

    if kind == "listing":
        stubs = parse_listing_page(html)
        lines.append(f"parsed {len(stubs)} cards; next page: {find_next_page_url(html)}")
        for stub in stubs[:3]:
            lines.append(
                f"  {stub.item_id}: {stub.title!r} {stub.price} {stub.currency} "
                f"rooms={stub.rooms} area={stub.area_m2} floor={stub.floor}/{stub.floors_total} "
                f"loc={stub.location!r}"
            )
    else:
        listing = parse_detail(html, url)
        filled = {k: v for k, v in listing.to_dict().items() if v not in (None, [], {}, "")}
        lines.append(f"parsed detail page: {len(filled)} of {len(listing.to_dict())} fields filled")
        for key in sorted(filled):
            if key == "properties":
                continue
            value = str(filled[key])
            lines.append(f"  {key}: {value[:110]}")

    if broken:
        lines.append("")
        lines.append("Stale selectors (no candidate matched):")
        for report in broken:
            lines.append(f"  - {report.key}")
        lines.append("Add a working selector to the front of that list in bina_scraper/selectors.py.")
    return "\n".join(lines)
