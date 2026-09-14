# bina.az-scraper

Collects **price, area, rooms and location** from bina.az listings into SQLite/CSV,
and builds a standalone **HTML report** over a date range (default: the last 365 days).

No third-party packages. Python 3.9+ and the standard library only.

```bash
python -m bina scrape --pages 40 --report        # crawl, then write report/bina-report.html
python -m bina report --since 2025-09-14         # rebuild the report from what is stored
python -m bina demo                              # see the report layout with synthetic data
```

## Read this before you trust the numbers

**bina.az has no archive.** It publishes only listings that are currently live. There is
no "all listings from the past year" to fetch — what this tool produces is a snapshot of
*present inventory*, sliced by the posting date printed on each listing. Everything that
sold, rented or expired is already gone from the site, and that gap grows the further
back you look: a chart of "listings posted per month" will always slope down toward
older months, because old listings survive only if nobody took them.

That makes the data legitimate for questions like *what is on the market now, and what
does it cost by district and size*, and misleading for questions like *how did Baku
prices move last year*. The report states this on the page itself.

**You can build the archive the site lacks, though.** The database is keyed on listing
ID and never deletes, so every run adds listings the last one did not see and keeps the
ones that have since disappeared. Run it on a schedule (see
[Running it on GitHub Actions](#running-it-on-github-actions)) and after a few months you
own a genuine time series — including the listings bina.az has dropped. That history
starts the day you start collecting; it cannot be backfilled.

Two further limits worth keeping in mind:

- Prices are **asking prices**, not transaction prices.
- The posting date lives on the **detail page**, not the results card, so a date-filtered
  run costs one extra request per listing. `--no-details` skips that and gives you
  price/area/rooms/location with no dates at all.

## Commands

### `scrape`

```bash
python -m bina scrape \
  --section alqi-satqi \        # alqi-satqi = for sale, kiraye = rent
  --pages 40 \                  # result pages to fetch
  --delay 1.0 \                 # seconds between requests
  --days 365 \                  # date range used for the report/CSV
  --csv data/listings.csv \
  --report report/bina-report.html
```

Useful flags:

| Flag | What it does |
|---|---|
| `--query KEY=VALUE` | extra query parameters, repeatable (e.g. `--query city_id=1`) |
| `--no-details` | skip detail pages: fast, but no posting dates |
| `--detail-limit N` | cap detail requests per run; run again later to continue |
| `--no-resume` | re-fetch pages already recorded in the database |
| `--dump-dir DIR` | save every fetched page for `inspect` |
| `--since` / `--until` / `--days` | the reporting window |

Runs are **resumable**. Pages already fetched are recorded in the database and skipped,
and listings that still have no date are picked up by the next run's detail pass, so a
long crawl can be done in sittings.

### `report`

Rebuilds `report/bina-report.html` from the database without touching the network.
`--include-undated` adds listings that have no posting date (they are excluded by
default, since they cannot be placed in time). `--title` sets the heading.

### `inspect`

The debugging tool for when bina.az changes its markup:

```bash
python -m bina scrape --pages 1 --no-details --dump-dir dumps
python -m bina inspect dumps/list-alqi-satqi-p1.html
python -m bina inspect dumps/item-4612345.html --kind detail
```

It prints per-field coverage ("area parsed on 34% of cards") and the parsed rows, so you
can see exactly which field broke.

## Running it on GitHub Actions

`.github/workflows/scrape.yml` runs the scraper on a GitHub runner, which is useful when
the machine you develop on cannot reach bina.az (a restricted network policy, a locked-down
container) — and it is how you accumulate history without leaving a laptop running.

Each run restores the database the previous run produced, scrapes on top of it, and pushes
the result back to a `scraped-data` branch that holds only data:

```
scraped-data
├── data/bina.sqlite3        # the full accumulated database
├── data/listings.csv
└── report/bina-report.html
```

The same files are attached to every run as a downloadable artifact (kept 30 days), so
you do not need to check the branch out to look at them.

- **Run it now:** Actions → *Scrape bina.az* → *Run workflow*. The inputs (section, pages,
  delay, detail limit, reporting window) are all overridable per run.
- **On a schedule:** daily at 03:20 UTC. GitHub disables scheduled workflows after 60 days
  with no repository activity; re-enable from the Actions tab if that happens.
- **Getting the data out:** `git fetch origin scraped-data && git checkout scraped-data`,
  or download the run artifact.

The workflow runs the test suite before scraping and **fails loudly** if a run collects
nothing — `scrape` exits non-zero when it is blocked, refused by robots.txt, or fetches
pages that yield no cards — so a parser break shows up as a red run rather than a stale
report. Note that bina.az may treat cloud IP ranges differently from a home connection; if
the run reports an anti-bot interstitial, that is what happened, and running locally is the
fallback.

## Output

- `data/bina.sqlite3` — `listings`, plus `pages` and `runs` for resume and audit.
- CSV (with `--csv`) — one row per listing, including a computed `price_per_m2`.
- `report/bina-report.html` — a single self-contained file: no network requests, no
  JS libraries, works from `file://`, light and dark themes, every chart has a
  "Show data" table underneath.

The report contains: headline medians; median AZN/m² by district; listings by room
count; listings posted per month; median AZN/m² by month; area against price by room
count; a recent-listings table; and the caveats above.

## When the site changes

Everything site-specific is in two files:

- `bina/patterns.py` — the text patterns (price, `3 otaq`, `85 m²`, `Nəsimi r.`, dates in
  Azerbaijani and Russian).
- `bina/parse.py` — how a listing card is located and read.

The parsers deliberately key on **visible text** rather than CSS class names, and find
cards via `<a href="/items/<id>">` rather than a container class, because bina.az renames
classes far more often than it changes the words it prints. A redesign will still break
things eventually; `inspect` tells you which part.

## Being a good citizen

Defaults are deliberately polite: one request per second with jitter, a real
User-Agent, bounded retries with exponential backoff, and `robots.txt` honoured —
including its `Crawl-delay`. If robots.txt disallows the path, the run stops and says so.

Check bina.az's terms of service before running this at any scale, and keep `--delay` at
a level that cannot affect the site. Scraping someone's site is your responsibility, not
the tool's.

## Tests

```bash
python -m unittest discover -s tests -t .
```

The parser tests run against fixture pages in `tests/fixtures/`, which mirror bina.az's
card and detail markup (including a duplicate VIP card, a comma decimal, the `₼` sign,
and an alternative card layout).

`tests/test_integration.py` runs the whole pipeline — fetch, robots.txt, pagination,
resume, the detail pass and the report — against a local HTTP server standing in for
bina.az. Nothing in the suite touches the public internet.
