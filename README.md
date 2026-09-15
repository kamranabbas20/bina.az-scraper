# bina.az-scraper

A polite, selector-driven scraper for property listings on [bina.az](https://bina.az).
It walks search-result pages, optionally visits each item page, and writes one
JSON object per listing to a JSON Lines file.

## Read this first: bina.az is behind Cloudflare

bina.az serves a Cloudflare bot check, and on some networks (datacenter IPs,
most cloud providers) it returns a hard `403 Attention Required` to everything —
plain HTTP clients and real browsers alike. The scraper detects this and stops
with a clear message and exit code 2 instead of writing empty records:

```
ERROR bina_scraper.crawl: https://bina.az/robots.txt: blocked by the site (HTTP 403).
```

There is no bypass in this project and none is planned. If you see that message,
run it from a network bina.az actually serves. If plain HTTP gets a JavaScript
challenge rather than a block, `--fetcher browser` renders the page in Chromium,
which is often enough.

**The selectors in `bina_scraper/selectors.py` have not been checked against a
live page**, for the same reason — the machine they were written on is blocked.
They encode bina.az's documented markup, but expect to repair one or two on your
first run. That takes one command; see [Repairing selectors](#repairing-selectors).

## Install

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# only if you need the browser fetcher
pip install -r requirements-browser.txt && playwright install chromium
```

## Quickstart

```bash
# See what would be requested, without touching the network
python -m bina_scraper crawl --max-pages 3 --dry-run

# Cards only: one request per results page, ~20 listings each
python -m bina_scraper crawl --max-pages 3 --no-details -o data/cards.jsonl

# Full records: one extra request per listing
python -m bina_scraper crawl --max-pages 3 --delay 3 -o data/listings.jsonl

# One listing, printed as JSON
python -m bina_scraper fetch https://bina.az/items/4471693
```

Copy `config.example.yml` to `config.yml` for anything you run more than once:

```bash
python -m bina_scraper crawl -c config.yml
```

CLI flags override the config file, which overrides the defaults. An unknown key
in the config file is an error rather than a silently ignored typo.

### Filters

bina.az's query parameters are not stable enough to hardcode, so build the
search you want in a browser and copy its query string:

```bash
python -m bina_scraper crawl --deal-type rent --param where=baku --param 'room_ids[]=2'
```

## Commands

| Command | What it does |
| --- | --- |
| `crawl` | Walk search-result pages and write listings to JSONL |
| `fetch <url>` | Fetch one item or search URL and print the parsed record |
| `parse <file.html>` | Parse a saved HTML file — no network |
| `history <file.jsonl>` | Query an observation log: summary, timelines, price changes |
| `verify-selectors <file.html>` | Report which selectors still match a saved page |

Exit codes: `0` success, `1` nothing written, `2` blocked or fetch failure.

## Repairing selectors

When bina.az changes its markup, the parsers keep running and the affected
fields go `null`. To find and fix that:

1. Open the page in a browser and save it (`Ctrl+S`, "HTML only").
2. Run `python -m bina_scraper verify-selectors saved.html`.

Every candidate selector reports its match count, the parsed record is printed
so you can see what actually came out, and anything with no match at all is
listed at the bottom:

```
[OK  ] card
       *    4 x  div.items-i
            0 x  div.items_list div.items-i
[MISS] card_price
            0 x  .price-val

Stale selectors (no candidate matched):
  - card_price
```

3. Add a working selector to the front of that key's list in
   `bina_scraper/selectors.py` and bump `SELECTOR_REVISION`.

Every selector lives in that one file; the parsers never hardcode one. Each key
holds a *list* of candidates tried in order, so adding a new selector does not
break older saved pages. `SELECTOR_REVISION` is stamped into every record under
`properties._selector_revision`, so a dataset can be traced to the selector set
that produced it.

A crawl can also keep the raw HTML for exactly this purpose:

```bash
python -m bina_scraper crawl --max-pages 1 --save-html-dir data/raw
```

## Output

One JSON object per line, UTF-8, with non-ASCII left as-is rather than escaped
(`"city": "Bakı"`):

```json
{
  "item_id": "4471693",
  "url": "https://bina.az/items/4471693",
  "scraped_at": "2025-09-15T08:12:44+00:00",
  "source": "bina.az",
  "title": "3 otaqlı yeni tikili, 90 m², Nərimanov r.",
  "price": 185000.0,
  "currency": "AZN",
  "deal_type": "sale",
  "category": "Yeni tikili",
  "rooms": 3,
  "area_m2": 90.0,
  "floor": 9,
  "floors_total": 16,
  "city": "Bakı",
  "district": "Nərimanov",
  "metro": "28 May",
  "latitude": 40.4093,
  "longitude": 49.8671,
  "has_repair": true,
  "has_bill_of_sale": true,
  "has_mortgage": false,
  "amenities": ["Kombi", "Mebel", "Kondisioner"],
  "photo_urls": ["https://bina.az/photos/4471693/1.jpg"],
  "seller_name": "Elçin",
  "seller_type": "agent",
  "listed_at": "2025-09-15T00:00:00",
  "view_count": 1284,
  "properties": {"Kateqoriya": "Yeni tikili", "Qazanc növü": "Naməlum"}
}
```

Notes on the shape:

- A field that could not be found is `null`, never a guess. A markup change
  costs you a field, not a wrong value and not the run.
- `properties` keeps every detail-page row under its original Azerbaijani
  label, including ones this project does not model, so nothing is lost.
- Prices are numbers with a separate `currency`; bina.az quotes AZN, USD and
  EUR. `"Razılaşma ilə"` (price on request) parses to `null`.
- Land plots are quoted in *sot*, which lands in `land_area_sot` and is kept
  out of `area_m2`.
- Dates are ISO 8601. `"Bugün, 09:12"` and `"Dünən, 23:40"` resolve against
  the run date, so they are only meaningful because `scraped_at` is recorded
  alongside them.

### Storage modes

Re-running appends. What happens to a listing the file already knows depends on
`store_mode`, and the choice decides whether you end up with a catalogue or a
history:

| Mode | Rows per listing | Use it for |
| --- | --- | --- |
| `observations` (default) | One per crawl | Price history, time-on-market, spotting a delisting |
| `changes` | One per change | The same history for anything that moved, in a much smaller file |
| `unique` | One, ever | A catalogue of current listings |

```bash
python -m bina_scraper crawl --mode changes -o data/listings.jsonl
```

`observations` records a row every crawl even when nothing moved, which is the
point: "this listing was still live at this price on this date" is a fact you
cannot recover later. `changes` drops those rows, so the file stays small and a
price history is still complete — but you can no longer tell an unchanged
listing from one you never checked.

`unique` is the cheapest and the only mode that saves requests: a listing
already in the file is never fetched again. The history modes have to fetch
before they can tell whether anything changed, so they cost one request per
listing per crawl. Budget for that before pointing a cron job at it.

Every record carries a `content_hash` over the listing's own fields — the crawl
timestamp and the view counter are excluded, since both move on their own and
would make every observation look like a change. That hash is what `changes`
mode compares, and it makes diffing two observations downstream a string
comparison.

`resume: true` (the default) reads the existing file's state on startup;
`--no-resume` ignores it, which in `unique` mode re-scrapes everything and in
`changes` mode makes the next write count as a change.

### Reading the log back

```bash
python -m bina_scraper history data/listings.jsonl                    # summary
python -m bina_scraper history data/listings.jsonl --item 4471693     # one timeline
python -m bina_scraper history data/listings.jsonl --price-changes    # every move
```

```
$ python -m bina_scraper history data/listings.jsonl --item 4471693
4471693  (3 observations)
  3 otaqlı yeni tikili
  2025-09-13T06:00:04+00:00      185,000 AZN
  2025-09-14T06:00:11+00:00      179,000 AZN   [price, content changed]
  2025-09-15T06:00:07+00:00      179,000 AZN

$ python -m bina_scraper history data/listings.jsonl --price-changes
4471693  185,000 → 179,000 AZN  (-6,000, -3.2%)  on 2025-09-14T06:00:11+00:00
```

Add `--json` to any of those for machine-readable output. A price that becomes
`"Razılaşma ilə"` (on request) parses to `null` and is not reported as a drop
to zero.

## Being a good citizen

The defaults are deliberately slow and shallow — one page, 2–3 s between
requests, one worker — and widening that is an explicit choice:

- `robots.txt` is fetched and honoured, including `Crawl-delay`. If it cannot
  be read, the crawl refuses rather than guessing. `--ignore-robots` overrides
  that and puts the decision on you.
- Set `contact_email` in the config so the `User-Agent` says who is crawling.
- There is no concurrency. Scraping a listings site at speed is how you get an
  IP banned and the site's bill raised.
- Listing text and photos belong to whoever posted them, and bina.az's terms
  govern what you may do with them. Check before you republish.

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest
```

123 tests run offline against HTML fixtures in `tests/fixtures/`; no test
touches the network. The fixtures deliberately include the awkward cases — a promoted
listing repeated on the page, an ad card with no item id, a land plot quoted in
sot, a property row this project does not model, and a Cloudflare challenge body.

If you fix a selector, add the saved page (trimmed) as a fixture. That is what
keeps the next markup change from costing the same afternoon twice.

### Layout

```
bina_scraper/
  cli.py          # argparse entry point, four subcommands
  config.py       # Settings dataclass, YAML + flag loading
  selectors.py    # every CSS selector and label mapping, in one place
  crawl.py        # the crawl loop: pages -> cards -> details -> JSONL
  history.py      # reading an observation log back: timelines, price changes
  robots.py       # robots.txt policy
  verify.py       # the verify-selectors report
  fetchers/       # http.py (requests) and browser.py (Playwright)
  parse/          # listing.py, detail.py, normalize.py
  store/          # jsonl.py, and the three storage modes
```

Adding a field is usually three edits: a field on `Listing` in `models.py`, a
label in `PROPERTY_LABELS` in `selectors.py`, and a test.
