# Chrono24 Rolex Scraper

A deterministic, production-grade scraper that extracts Rolex listings from
[Chrono24](https://www.chrono24.com/rolex/index.htm) search-results pages
using **Playwright** (browser automation) and **BeautifulSoup** (HTML
parsing), validates every record with **Pydantic v2**, and exports clean
**JSON** and **CSV** datasets via **Pandas**.

Built as a portfolio piece to demonstrate: proxy/header/fingerprint
handling, resilient pagination in the face of anti-bot protection, strict
data validation, and a clean, modular pipeline architecture.

---

## Features

- **Headless Playwright browsing** with a realistic user agent, viewport,
  locale, and header set.
- **Anti-bot resilience**: Chrono24 sits behind Cloudflare, which flags
  rapid sequential navigations within a single browser session and serves a
  403 challenge page. Each search-results page is fetched from its own
  short-lived browser context (fresh cookies/fingerprint state, same
  browser process), which reliably avoids the challenge. Any challenge page
  that does slip through is detected (`403`/`429`/`503` status or
  `"Just a moment"` / `cf-chl` markers) and logged clearly rather than
  silently mis-parsed.
- **Human-like pacing**: randomized 2–4s delays between page transitions.
- **BeautifulSoup extraction** straight from the listing-card markup — no
  reliance on internal/undocumented JSON APIs.
- **Robust `watch_id` extraction**: parsed from the listing URL (e.g.
  `rolex-gmt-master--id47837583.htm` → `47837583`); falls back to a
  deterministic SHA-256 hash of the URL if no numeric ID is present, so
  the mapping stays stable across runs.
- **Locale-aware price parsing**: handles both US-style (`"$14,500.00"`)
  and European-style (`"7.890 €"`, `"1.234,56 €"`) grouping/decimal
  conventions.
- **Pydantic v2 validation** on every record — a malformed card is logged
  and skipped, never crashes the run.
- **Deduplication** by `watch_id` in the pipeline stage (Chrono24 shows
  pinned/sponsored items on more than one page).
- **Dual export**: `data/rolex_listings.json` and `data/rolex_listings.csv`.

---

## Architecture

```
chrono24-rolex-scraper/
├── config.py      # URLs, limits, rate limits, selectors, output paths
├── models.py      # Pydantic v2 WatchListing schema + price/currency cleaning
├── scraper.py      # Playwright browsing, pagination, BeautifulSoup parsing
├── pipeline.py     # Cleaning, deduplication, JSON/CSV export (Pandas)
├── main.py         # Orchestrates the full run + prints a summary
├── requirements.txt
└── data/
    ├── rolex_listings.json
    └── rolex_listings.csv
```

**Flow:** `main.py` → `scraper.scrape_rolex_listings()` (Playwright fetch →
BeautifulSoup parse → Pydantic validate, page by page) → `pipeline.process_and_save()`
(dedupe → DataFrame → JSON + CSV).

### Extraction context

All fields are extracted directly from the listing-card elements on the
search-results grid (`div.js-listing-item-container`) — no navigation into
individual listing detail pages is required:

| Field         | Source                                                              |
|---------------|----------------------------------------------------------------------|
| `watch_id`    | Parsed from the card's `href` (`...--id<digits>.htm`), or a hash fallback |
| `title`       | Card headline (e.g. "Rolex GMT-Master")                              |
| `model`       | Card subtitle (e.g. "1675 Vintage Pepsi")                            |
| `price`       | Card price element, cleaned to `float`                               |
| `currency`    | Symbol/code detected in the raw price text                           |
| `location`    | Seller country code (fallback: full country name from tooltip)       |
| `listing_url` | Absolute URL to the listing detail page                              |
| `image_url`   | Product image (resolved from Chrono24's lazy-loading carousel markup)|

---

## Setup

```bash
# 1. Create and activate a virtual environment
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS/Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Install Playwright's browser binaries (one-time)
playwright install chromium
```

## Usage

```bash
python main.py
```

This launches a headless Chromium browser, scrapes up to `MAX_PAGES` search
pages (stopping early once `MAX_ITEMS` validated listings are collected),
and writes:

- `data/rolex_listings.json`
- `data/rolex_listings.csv`

A run summary (item count, elapsed time, price range/average) is printed to
the console and logged to `logs/scraper.log`.

A demo run (default settings) completes in **under 10 seconds** and yields
50 validated listings from a single search page.

---

## Configuration (`config.py`)

| Setting                | Default | Purpose |
|-------------------------|---------|---------|
| `MAX_PAGES`             | `3`     | How many search-result pages to visit |
| `MAX_ITEMS`             | `50`    | Stop once this many validated listings are collected |
| `DELAY_MIN/MAX_SECONDS` | `2.0`–`4.0` | Randomized delay between page transitions |
| `PROXY_SERVER`          | `None`  | Optional upstream proxy (`http://host:port`) |
| `HEADLESS`              | `True`  | Run Chromium headless |

### Scaling to full production

The demo defaults (`MAX_PAGES=3`, `MAX_ITEMS=50`) exist to keep the demo
fast (~10s) and predictable. For a full-scale production crawl:

1. **Raise or remove the caps.** Set `MAX_ITEMS` to a very large number and
   `MAX_PAGES` to however deep Chrono24's pagination goes for the category
   you're targeting (check the site's own "last page" link, since it varies
   by filter). Alternatively, drive both from CLI flags/env vars instead of
   hardcoding them.
2. **Add real proxies.** Populate `PROXY_SERVER` / `PROXY_USERNAME` /
   `PROXY_PASSWORD` in `config.py` (ideally from environment variables or a
   secrets manager) with a rotating residential/datacenter proxy pool.
   Chrono24 is behind Cloudflare — sustained, unproxied crawling from a
   single IP will eventually be rate-limited or challenged even with the
   per-page fresh-context strategy this project already uses.
3. **Widen the rate-limit window.** Increase `DELAY_MIN_SECONDS` /
   `DELAY_MAX_SECONDS` and consider adding a longer cooldown every N pages.
4. **Rotate fingerprints.** Vary `USER_AGENT`/`VIEWPORT`/`LOCALE` per
   context (or per proxy) rather than reusing one fixed fingerprint for the
   entire crawl.
5. **Persist a "seen" set across runs** (e.g. a small SQLite/Redis store of
   `watch_id`s) so repeat crawls only process new/changed listings instead
   of re-fetching everything.
6. **Handle challenge pages explicitly.** `scraper.py` already logs a clear
   warning when a Cloudflare challenge (403/429/503, or a "Just a moment"
   page) is detected; in production, wire that signal to a
   backoff-and-retry (or proxy-rotation) policy instead of just stopping
   pagination.

---

## Data Model (`models.py`)

```python
class WatchListing(BaseModel):
    watch_id: str
    title: str
    model: Optional[str]
    price: Optional[float]
    currency: Optional[str]
    location: Optional[str]
    listing_url: str
    image_url: Optional[str]
    scraped_at: datetime
```

Optional fields (`model`, `price`, `currency`, `location`, `image_url`)
default to `None` when absent from a card, so one incomplete listing never
aborts the scrape. `title`, `watch_id`, and `listing_url` are required —
a card missing any of these is logged and skipped.

---

## Notes on reliability

This scraper targets the **public, unauthenticated search-results HTML**
that Chrono24 renders server-side — it does not use any private/internal
API, does not require login, and respects the configured rate limits. Site
markup can change at any time; if extraction starts returning empty
results, check `config.SELECTORS` first, as all CSS selectors are
centralized there for quick updates.
