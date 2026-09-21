"""
Central configuration for the Chrono24 Rolex scraper.

All tunable parameters live here so the rest of the codebase never hardcodes
URLs, limits, or paths. For a full-scale production run, see the notes next
to MAX_PAGES / MAX_ITEMS below.
"""
from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Target
# ---------------------------------------------------------------------------
BASE_URL: str = "https://www.chrono24.com/rolex/index.htm"
SITE_ROOT: str = "https://www.chrono24.com"

# Chrono24 paginates as index.htm, index-2.htm, index-3.htm, ...
PAGE_URL_TEMPLATE: str = "https://www.chrono24.com/rolex/index-{page}.htm"

# ---------------------------------------------------------------------------
# Safety / execution limits (demo-friendly)
# ---------------------------------------------------------------------------
# MAX_PAGES caps how many search-result pages are visited. Chrono24 shows
# roughly 60 listings per page, so MAX_PAGES=3 covers up to ~180 raw cards.
# For a full-scale production crawl, raise this (or drive it from a CLI flag)
# and pair it with a real proxy pool + longer, jittered delays so the crawl
# stays well under the site's tolerance for automated traffic.
MAX_PAGES: int = 3

# MAX_ITEMS caps the total number of *validated* listings collected, across
# all pages, so a demo run finishes in well under a minute. For production,
# remove the cap (set to a very large number) and rely on MAX_PAGES and/or
# a stopping condition (e.g. "no new listings" / date cursor) instead.
MAX_ITEMS: int = 50

# ---------------------------------------------------------------------------
# Rate limiting / human-like pacing
# ---------------------------------------------------------------------------
DELAY_MIN_SECONDS: float = 2.0
DELAY_MAX_SECONDS: float = 4.0

# Timeouts (milliseconds) for Playwright navigation/selectors.
NAVIGATION_TIMEOUT_MS: int = 45_000
SELECTOR_TIMEOUT_MS: int = 15_000

# ---------------------------------------------------------------------------
# Browser / request fingerprint
# ---------------------------------------------------------------------------
HEADLESS: bool = True
USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
VIEWPORT: dict = {"width": 1366, "height": 900}
LOCALE: str = "en-US"
EXTRA_HTTP_HEADERS: dict = {
    "Accept-Language": "en-US,en;q=0.9",
}

# ---------------------------------------------------------------------------
# Proxy configuration
# ---------------------------------------------------------------------------
# Populate these (e.g. from environment variables or a secrets manager) to
# route traffic through a proxy/proxy pool in production. Leave PROXY_SERVER
# as None to run without a proxy (default for local demo runs).
PROXY_SERVER: str | None = None   # e.g. "http://proxy-host:port"
PROXY_USERNAME: str | None = None
PROXY_PASSWORD: str | None = None

# ---------------------------------------------------------------------------
# Output paths
# ---------------------------------------------------------------------------
ROOT_DIR: Path = Path(__file__).resolve().parent
DATA_DIR: Path = ROOT_DIR / "data"
LOG_DIR: Path = ROOT_DIR / "logs"

JSON_OUTPUT_PATH: Path = DATA_DIR / "rolex_listings.json"
CSV_OUTPUT_PATH: Path = DATA_DIR / "rolex_listings.csv"
LOG_FILE_PATH: Path = LOG_DIR / "scraper.log"

DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# CSS selectors (kept in one place so markup drift only needs one edit)
# ---------------------------------------------------------------------------
SELECTORS: dict = {
    "listing_card": "div.js-listing-item-container",
    "listing_link": "a.js-listing-item-link",
    "title": "p.text-bold.text-ellipsis",
    "model": "div.p-t-3 p.text-ellipsis:not(.text-bold)",
    "price": "p.wt-listing-item-price strong",
    "location_button": "button.wt-listing-item-location",
    "location_span": "button.wt-listing-item-location span",
    "image": "div.listing-item-image img",
}
