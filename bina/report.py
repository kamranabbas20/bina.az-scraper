"""Build the standalone HTML report from the scraped listings."""

from __future__ import annotations

import datetime as dt
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Optional, Sequence

from . import charts
from .models import Listing
from .stats import median, quantile, trimmed

MIN_PER_GROUP = 5  # below this a median is noise, so the group is dropped
AREA_BOUNDS = (10.0, 1000.0)  # m² — anything outside is a parsing artefact
PRICE_BOUNDS = (1_000.0, 20_000_000.0)  # AZN


# --- formatting -------------------------------------------------------------


def fmt_int(value: float) -> str:
    return f"{int(round(value)):,}".replace(",", " ")


def fmt_azn(value: float) -> str:
    return fmt_int(value)


def fmt_area(value: float) -> str:
    return f"{value:.0f}"


def fmt_month(key: str) -> str:
    year, month = key.split("-")
    return f"{month}.{year[2:]}"


# --- data preparation -------------------------------------------------------


class Dataset:
    """The filtered rows the report is computed from, plus why rows were cut."""

    def __init__(
        self,
        listings: Iterable[Listing],
        currency: str = "AZN",
        since: Optional[dt.date] = None,
        until: Optional[dt.date] = None,
    ):
        self.currency = currency
        self.since = since
        self.until = until
        self.excluded: Counter = Counter()

        rows: list[Listing] = []
        for listing in listings:
            if listing.posted_at and since and listing.posted_at < since:
                self.excluded["posted before the range"] += 1
                continue
            if listing.posted_at and until and listing.posted_at > until:
                self.excluded["posted after the range"] += 1
                continue
            if listing.price is None:
                self.excluded["no price"] += 1
                continue
            if listing.currency and listing.currency != currency:
                self.excluded[f"priced in {listing.currency}"] += 1
                continue
            if not PRICE_BOUNDS[0] <= listing.price <= PRICE_BOUNDS[1]:
                self.excluded["price out of plausible range"] += 1
                continue
            if listing.area is None:
                self.excluded["no area"] += 1
                continue
            if not AREA_BOUNDS[0] <= listing.area <= AREA_BOUNDS[1]:
                self.excluded["area out of plausible range"] += 1
                continue
            rows.append(listing)

        self.rows = rows

    def __len__(self) -> int:
        return len(self.rows)

    @property
    def dated(self) -> list[Listing]:
        return [row for row in self.rows if row.posted_at]

    @property
    def date_sources(self) -> Counter:
        return Counter(row.date_source or "unknown" for row in self.rows if row.posted_at)

    def by_district(self) -> list[tuple[str, list[Listing]]]:
        groups: dict[str, list[Listing]] = defaultdict(list)
        for row in self.rows:
            name = row.district or row.settlement or row.metro
            if name:
                groups[name].append(row)
        return sorted(groups.items(), key=lambda item: len(item[1]), reverse=True)

    def by_month(self) -> list[tuple[str, list[Listing]]]:
        groups: dict[str, list[Listing]] = defaultdict(list)
        for row in self.dated:
            groups[f"{row.posted_at.year:04d}-{row.posted_at.month:02d}"].append(row)
        if not groups:
            return []
        # Fill the gaps so a quiet month reads as zero, not as a missing point.
        keys = sorted(groups)
        out: list[tuple[str, list[Listing]]] = []
        year, month = (int(part) for part in keys[0].split("-"))
        end_year, end_month = (int(part) for part in keys[-1].split("-"))
        while (year, month) <= (end_year, end_month):
            key = f"{year:04d}-{month:02d}"
            out.append((key, groups.get(key, [])))
            month += 1
            if month > 12:
                year, month = year + 1, 1
        return out


# --- chart sections ---------------------------------------------------------


def district_chart(data: Dataset, top: int = 12) -> str:
    groups = [
        (name, rows)
        for name, rows in data.by_district()
        if len(rows) >= MIN_PER_GROUP
    ][:top]
    if not groups:
        return charts.empty_figure(
            "Median price per m² by district",
            "No district could be parsed from enough listings.",
        )

    rows = []
    for name, listings in groups:
        value = median(listing.price_per_m2 for listing in listings)
        if value:
            rows.append((name, value, f"{len(listings)} listings"))
    rows.sort(key=lambda row: row[1], reverse=True)

    return charts.figure(
        "Median price per m² by district",
        f"{data.currency} per m², districts with at least {MIN_PER_GROUP} listings",
        charts.hbar(rows, fmt_azn, row_height=30),
        charts.table(
            ["District", f"Median {data.currency}/m²", "Listings"],
            [(name, fmt_azn(value), extra.split()[0]) for name, value, extra in rows],
        ),
        note="Sorted by price, not by listing count.",
    )


def rooms_chart(data: Dataset) -> str:
    counts = Counter(row.rooms for row in data.rows if row.rooms and 1 <= row.rooms <= 10)
    if not counts:
        return charts.empty_figure("Listings by room count", "No room counts were parsed.")

    rows = []
    for rooms in sorted(counts):
        listings = [row for row in data.rows if row.rooms == rooms]
        price = median(listing.price for listing in listings)
        extra = f"median {fmt_azn(price)} {data.currency}" if price else ""
        rows.append((f"{rooms}", float(counts[rooms]), extra))

    return charts.figure(
        "Listings by room count",
        "Number of listings",
        charts.vbar(rows, fmt_int),
        charts.table(
            ["Rooms", "Listings", f"Median price ({data.currency})"],
            [
                (
                    label,
                    fmt_int(value),
                    extra.replace("median ", "").replace(f" {data.currency}", "") or "—",
                )
                for label, value, extra in rows
            ],
        ),
    )


def volume_chart(data: Dataset) -> str:
    months = data.by_month()
    if not months:
        return charts.empty_figure(
            "Listings posted per month",
            "No posting dates were collected — run the scrape with detail pages enabled.",
        )
    rows = [(fmt_month(key), float(len(listings)), key) for key, listings in months]
    return charts.figure(
        "Listings posted per month",
        "Count of listings by the date on the listing page",
        charts.vbar(rows, fmt_int, rotate_labels=len(rows) > 8, direct_labels=len(rows) <= 14),
        charts.table(
            ["Month", "Listings"], [(key, fmt_int(value)) for _, value, key in rows]
        ),
        note=(
            "Only listings that are still live are counted, so older months are "
            "under-represented — sold and expired listings are gone from the site."
        ),
    )


def price_trend_chart(data: Dataset) -> str:
    months = [
        (key, listings) for key, listings in data.by_month() if len(listings) >= MIN_PER_GROUP
    ]
    if len(months) < 2:
        return charts.empty_figure(
            "Median price per m² by month",
            "Not enough dated listings to draw a trend.",
        )
    rows = []
    for key, listings in months:
        value = median(listing.price_per_m2 for listing in listings)
        if value:
            rows.append((fmt_month(key), value, f"{len(listings)} listings"))

    return charts.figure(
        "Median price per m² by month",
        f"{data.currency} per m², months with at least {MIN_PER_GROUP} listings",
        charts.line(rows, fmt_azn, every_nth_label=2 if len(rows) > 9 else 1),
        charts.table(
            ["Month", f"Median {data.currency}/m²", "Listings"],
            [(label, fmt_azn(value), extra.split()[0]) for label, value, extra in rows],
        ),
        note=(
            "The vertical scale is fitted to the data, not anchored at zero, so read "
            "the axis before judging the size of a move. This is the price of inventory "
            "posted in each month, not a repeat-sales index — composition changes "
            "between months move the line too."
        ),
    )


def area_price_chart(data: Dataset) -> str:
    if not data.rows:
        return charts.empty_figure("Area against price", "No listings to plot.")

    areas = trimmed([row.area for row in data.rows])
    prices = trimmed([row.price for row in data.rows])
    if not areas or not prices:
        return charts.empty_figure("Area against price", "No listings to plot.")
    area_cap, price_cap = max(areas), max(prices)

    buckets: dict[str, list[tuple[float, float, str]]] = {
        "1 room": [],
        "2 rooms": [],
        "3+ rooms": [],
    }
    plotted = 0
    for row in data.rows:
        if row.area > area_cap or row.price > price_cap:
            continue
        if row.rooms == 1:
            key = "1 room"
        elif row.rooms == 2:
            key = "2 rooms"
        elif row.rooms and row.rooms >= 3:
            key = "3+ rooms"
        else:
            continue
        location = row.location_raw or row.district or "location unknown"
        buckets[key].append((row.area, row.price, f"{fmt_area(row.area)} m² · {location}"))
        plotted += 1

    series = [(name, points) for name, points in buckets.items() if points]
    if not series:
        return charts.empty_figure("Area against price", "No listings had both area and rooms.")

    summary_rows = []
    for name, points in series:
        summary_rows.append(
            (
                name,
                fmt_int(len(points)),
                fmt_area(median(p[0] for p in points) or 0),
                fmt_azn(median(p[1] for p in points) or 0),
                fmt_azn(median(p[1] / p[0] for p in points) or 0),
            )
        )

    return charts.figure(
        "Area against price",
        f"Each dot is one listing · {fmt_int(plotted)} plotted",
        charts.scatter(series, fmt_area, fmt_azn, "Area (m²)", f"Price ({data.currency})"),
        charts.table(
            [
                "Rooms",
                "Listings",
                "Median m²",
                f"Median price ({data.currency})",
                f"Median {data.currency}/m²",
            ],
            summary_rows,
        ),
        legend=charts.legend(
            [(name, charts.SERIES_ROLES[index]) for index, (name, _) in enumerate(series)]
        ),
        note="The top and bottom 2% of areas and prices are clipped so outliers do not flatten the plot.",
    )


def tiles(data: Dataset) -> str:
    prices = [row.price for row in data.rows]
    areas = [row.area for row in data.rows]
    per_m2 = [row.price_per_m2 for row in data.rows]
    p25 = quantile(per_m2, 0.25)
    p75 = quantile(per_m2, 0.75)

    items = [
        charts.stat_tile(
            "Listings analysed", fmt_int(len(data)), f"{fmt_int(len(data.dated))} with a date"
        ),
        charts.stat_tile(
            "Median price",
            f"{fmt_azn(median(prices) or 0)} {data.currency}",
            f"median area {fmt_area(median(areas) or 0)} m²",
        ),
        charts.stat_tile(
            f"Median {data.currency}/m²",
            fmt_azn(median(per_m2) or 0),
            f"middle half {fmt_azn(p25 or 0)}–{fmt_azn(p75 or 0)}",
        ),
        charts.stat_tile(
            "Districts covered",
            fmt_int(len([1 for _, rows in data.by_district() if len(rows) >= MIN_PER_GROUP])),
            f"of {len(data.by_district())} seen",
        ),
    ]
    return f'<section class="tiles">{"".join(items)}</section>'


def recent_table(data: Dataset, limit: int = 200) -> str:
    rows = sorted(data.dated, key=lambda row: row.posted_at, reverse=True)[:limit]
    if not rows:
        rows = data.rows[:limit]
    body = [
        (
            row.posted_at.isoformat() if row.posted_at else "—",
            f"{fmt_azn(row.price)} {row.currency or ''}".strip(),
            fmt_area(row.area),
            fmt_azn(row.price_per_m2 or 0),
            row.rooms if row.rooms else "—",
            row.location_raw or row.district or "—",
            row.listing_id,
        )
        for row in rows
    ]
    return (
        '<section class="card">'
        "<h3>Listings</h3>"
        f'<p class="sub">Most recent {len(body)} rows of {fmt_int(len(data))}. '
        "The full set is in the SQLite database and the CSV export.</p>"
        + charts.table(
            ["Posted", "Price", "m²", f"{data.currency}/m²", "Rooms", "Location", "ID"], body
        )
        + "</section>"
    )


def caveats(data: Dataset, extra_notes: Sequence[str] = ()) -> str:
    items = [
        "bina.az publishes only listings that are currently live. There is no archive, "
        "so this is a snapshot of present inventory sliced by posting date — not a "
        "historical record of the market. Anything sold, rented or expired is absent, "
        "and that absence grows the further back you look.",
        "Prices are asking prices as advertised, not transaction prices.",
    ]
    sources = data.date_sources
    if sources:
        described = ", ".join(f"{count} {name}" for name, count in sources.most_common())
        items.append(
            f"Posting dates come from the listing page ({described}). A date labelled "
            f"'updated' is a bump, not an original posting date."
        )
    if data.excluded:
        dropped = ", ".join(f"{count} {reason}" for reason, count in data.excluded.most_common())
        items.append(f"Rows excluded from the charts: {dropped}.")
    items.extend(extra_notes)
    return (
        '<section class="card caveats"><h3>How to read this</h3><ul>'
        + "".join(f"<li>{charts.esc(item)}</li>" for item in items)
        + "</ul></section>"
    )


# --- page -------------------------------------------------------------------

CSS = """
:root {
  color-scheme: light;
  --page: #f9f9f7;
  --surface-1: #fcfcfb;
  --text-primary: #0b0b0b;
  --text-secondary: #52514e;
  --text-muted: #898781;
  --grid: #e1e0d9;
  --axis: #c3c2b7;
  --border: rgba(11,11,11,0.10);
  --series-1: #2a78d6;
  --series-2: #eb6834;
  --series-3: #1baf7a;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --page: #0d0d0d;
    --surface-1: #1a1a19;
    --text-primary: #ffffff;
    --text-secondary: #c3c2b7;
    --text-muted: #898781;
    --grid: #2c2c2a;
    --axis: #383835;
    --border: rgba(255,255,255,0.10);
    --series-1: #3987e5;
    --series-2: #d95926;
    --series-3: #199e70;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --page: #0d0d0d;
  --surface-1: #1a1a19;
  --text-primary: #ffffff;
  --text-secondary: #c3c2b7;
  --text-muted: #898781;
  --grid: #2c2c2a;
  --axis: #383835;
  --border: rgba(255,255,255,0.10);
  --series-1: #3987e5;
  --series-2: #d95926;
  --series-3: #199e70;
}

* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--page);
  color: var(--text-primary);
  font: 14px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif;
}
.wrap { max-width: 1080px; margin: 0 auto; padding-block: 32px; padding-left: 16px; padding-right: 16px; }

header h1 { font-size: 22px; margin: 0 0 4px; letter-spacing: -0.01em; }
header .meta { color: var(--text-secondary); margin: 0; }
header .range { font-variant-numeric: tabular-nums; }

.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin: 24px 0; }
.tile { background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; }
.tile-label { margin: 0; color: var(--text-secondary); font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; }
.tile-value { margin: 6px 0 2px; font-size: 27px; font-weight: 600; line-height: 1.1; }
.tile-detail { margin: 0; color: var(--text-muted); font-size: 12px; }

.card { background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px; padding: 18px 18px 14px; margin: 0 0 16px; }
.card h3 { margin: 0; font-size: 15px; }
.card .sub, .card .note { color: var(--text-secondary); margin: 4px 0 0; font-size: 12px; }
.card .note { color: var(--text-muted); margin-top: 10px; }
.card .empty { color: var(--text-muted); margin: 12px 0 4px; }
figcaption { margin-bottom: 10px; }
.plot { overflow-x: auto; }
.plot svg { width: 100%; height: auto; min-width: 520px; display: block; }

.legend { display: flex; flex-wrap: wrap; gap: 14px; list-style: none; padding: 0; margin: 0 0 6px; color: var(--text-secondary); font-size: 12px; }
.legend li { display: flex; align-items: center; gap: 6px; }
.swatch { width: 10px; height: 10px; border-radius: 2px; display: inline-block; }

.grid { stroke: var(--grid); stroke-width: 1; }
.axis { stroke: var(--axis); stroke-width: 1; }
.bar { fill: var(--series-1); }
.line { fill: none; stroke: var(--series-1); stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
.dot { fill: var(--series-1); stroke: var(--surface-1); stroke-width: 2; }
.point { stroke: var(--surface-1); stroke-width: 1.5; fill-opacity: 0.78; }
.hit, .hit-dot { fill: transparent; }
.tick { fill: var(--text-muted); font-size: 11px; font-variant-numeric: tabular-nums; }
.cat { fill: var(--text-secondary); font-size: 11px; }
.value { fill: var(--text-primary); font-size: 11px; font-variant-numeric: tabular-nums; }
.axis-label { fill: var(--text-muted); font-size: 11px; }
g.mark:hover .bar, g.mark:focus-visible .bar, g.mark:hover .dot { filter: brightness(1.08); }
g.mark:focus-visible, .point:focus-visible { outline: 2px solid var(--series-1); outline-offset: 2px; }

.table-view { margin-top: 12px; }
.table-view summary { cursor: pointer; color: var(--text-secondary); font-size: 12px; }
table { border-collapse: collapse; width: 100%; margin-top: 10px; font-size: 12px; }
th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--border); font-variant-numeric: tabular-nums; }
th { color: var(--text-secondary); font-weight: 600; white-space: nowrap; }
.card > table, .table-view table { display: block; overflow-x: auto; }

.caveats ul { margin: 10px 0 0; padding-left: 20px; color: var(--text-secondary); }
.caveats li { margin-bottom: 8px; }

footer { color: var(--text-muted); font-size: 12px; margin-top: 8px; }

.tip {
  position: absolute; z-index: 10; pointer-events: none;
  background: var(--surface-1); color: var(--text-primary);
  border: 1px solid var(--border); border-radius: 8px;
  padding: 7px 10px; font-size: 12px; max-width: 260px;
  box-shadow: 0 4px 16px rgba(0,0,0,0.18);
}
.tip b { font-weight: 600; }
.tip span { color: var(--text-secondary); display: block; }
@media (max-width: 520px) {
  .tile-value { font-size: 23px; }
}
"""

JS = """
(function () {
  var tip = document.createElement('div');
  tip.className = 'tip';
  tip.hidden = true;
  document.body.appendChild(tip);

  function render(el) {
    var label = el.getAttribute('data-label') || '';
    var value = el.getAttribute('data-value') || '';
    var extra = el.getAttribute('data-extra') || '';
    tip.innerHTML = '';
    var head = document.createElement('b');
    head.textContent = label + (value ? ' — ' + value : '');
    tip.appendChild(head);
    if (extra) {
      var sub = document.createElement('span');
      sub.textContent = extra;
      tip.appendChild(sub);
    }
    tip.hidden = false;
  }

  function place(x, y) {
    var pad = 14;
    var left = x + pad;
    var top = y + pad;
    if (left + tip.offsetWidth > window.scrollX + window.innerWidth) {
      left = x - tip.offsetWidth - pad;
    }
    tip.style.left = Math.max(window.scrollX + 4, left) + 'px';
    tip.style.top = top + 'px';
  }

  function target(node) {
    if (!node || !node.closest) return null;
    return node.closest('[data-label]');
  }

  document.addEventListener('pointermove', function (event) {
    var el = target(event.target);
    if (!el) { tip.hidden = true; return; }
    render(el);
    place(event.pageX, event.pageY);
  });

  document.addEventListener('pointerleave', function () { tip.hidden = true; });

  document.addEventListener('focusin', function (event) {
    var el = target(event.target);
    if (!el) { tip.hidden = true; return; }
    render(el);
    var box = el.getBoundingClientRect();
    place(window.scrollX + box.left, window.scrollY + box.bottom);
  });

  document.addEventListener('focusout', function () { tip.hidden = true; });
})();
"""


def build_report(
    listings: Iterable[Listing],
    since: Optional[dt.date] = None,
    until: Optional[dt.date] = None,
    currency: str = "AZN",
    title: str = "bina.az listings",
    source_note: str = "",
    extra_notes: Sequence[str] = (),
) -> str:
    data = Dataset(listings, currency=currency, since=since, until=until)

    range_text = "all dates"
    if since or until:
        range_text = f"{since or '…'} to {until or '…'}"

    generated = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    header = (
        "<header>"
        f"<h1>{charts.esc(title)}</h1>"
        f'<p class="meta">price · area · rooms · location for '
        f'<span class="range">{charts.esc(range_text)}</span> · '
        f"{fmt_int(len(data))} listings · generated {charts.esc(generated)}</p>"
        + (f'<p class="meta">{charts.esc(source_note)}</p>' if source_note else "")
        + "</header>"
    )

    body = [
        header,
        tiles(data),
        district_chart(data),
        rooms_chart(data),
        volume_chart(data),
        price_trend_chart(data),
        area_price_chart(data),
        recent_table(data),
        caveats(data, extra_notes),
        '<footer>Generated by bina.az-scraper. Asking prices as advertised on bina.az.</footer>',
    ]

    return (
        "<!doctype html>\n"
        '<html lang="en"><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{charts.esc(title)}</title>"
        f"<style>{CSS}</style>"
        "</head><body>"
        f'<div class="wrap">{"".join(body)}</div>'
        f"<script>{JS}</script>"
        "</body></html>\n"
    )


def write_report(path: str | Path, html_text: str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_text, encoding="utf-8")
    return path
