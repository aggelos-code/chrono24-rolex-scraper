"""
Playwright-driven scraper for Chrono24 Rolex search-result pages.

Design notes
------------
- Playwright is used purely to fetch fully-rendered HTML (Chrono24's listing
  grid is server-rendered, but we still let the page settle in case of any
  client-side hydration). All field extraction happens via BeautifulSoup on
  the resulting HTML, per the "extract from listing cards" requirement.
- Every field is defensively extracted: a missing/changed element on one
  card logs a warning and yields None for that field rather than aborting
  the whole scrape.
- ``watch_id`` is parsed straight from the listing href
  (``...--id47837583.htm`` -> ``"47837583"``); if no numeric ID is present
  in the URL, a deterministic SHA-256-based fallback hash is used instead so
  the same URL always maps to the same watch_id.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from bs4.element import Tag
from playwright.async_api import Browser, Page, async_playwright
from pydantic import ValidationError

import config
from models import WatchListing, detect_currency

logger = logging.getLogger(__name__)

_ID_FROM_URL_RE = re.compile(r"-id(\d+)\.htm")


def extract_watch_id(listing_url: str) -> str:
    """Parse the numeric listing ID out of a Chrono24 URL.

    Falls back to a deterministic hash of the URL when no ID segment is
    found, so downstream deduping/joins still behave consistently.
    """
    match = _ID_FROM_URL_RE.search(listing_url)
    if match:
        return match.group(1)
    return hashlib.sha256(listing_url.encode("utf-8")).hexdigest()[:16]


def _clean_image_url(img_tag: Optional[Tag]) -> Optional[str]:
    if img_tag is None:
        return None
    # Chrono24 lazy-loads secondary carousel images: the real src lives in
    # data-lazy-sweet-spot-master-src (with a "_SIZE_" placeholder token)
    # while the visible <img src=...> is a blank SVG placeholder.
    lazy_src = img_tag.get("data-lazy-sweet-spot-master-src")
    if lazy_src:
        # Template looks like ".../Square_SIZE_.jpg"; "280" fills it to a
        # concrete, valid resolution (matches the site's own default size).
        return lazy_src.replace("_SIZE_", "280")
    src = img_tag.get("src")
    if src and not src.startswith("data:"):
        return src
    return None


def parse_listing_card(card: Tag, page_url: str) -> Optional[WatchListing]:
    """Extract and validate a single WatchListing from a listing card."""
    try:
        link_tag = card.select_one(config.SELECTORS["listing_link"]) or card.find("a", href=True)
        if link_tag is None or not link_tag.get("href"):
            logger.warning("Skipping card with no listing link on %s", page_url)
            return None
        listing_url = urljoin(config.SITE_ROOT, link_tag["href"])

        title_tag = card.select_one(config.SELECTORS["title"])
        title = title_tag.get_text(strip=True) if title_tag else None
        if not title:
            logger.warning("Skipping card with no title: %s", listing_url)
            return None

        model_tag = card.select_one(config.SELECTORS["model"])
        model_name = model_tag.get_text(strip=True) if model_tag else None

        price_tag = card.select_one(config.SELECTORS["price"])
        raw_price = price_tag.get_text(strip=True) if price_tag else None

        location_tag = card.select_one(config.SELECTORS["location_span"])
        location = location_tag.get_text(strip=True) if location_tag else None
        if not location:
            location_btn = card.select_one(config.SELECTORS["location_button"])
            location = location_btn.get("data-title") if location_btn else None

        image_tag = card.select_one(config.SELECTORS["image"])
        image_url = _clean_image_url(image_tag)

        return WatchListing(
            watch_id=extract_watch_id(listing_url),
            title=title,
            model=model_name,
            price=raw_price,
            currency=detect_currency(raw_price),
            location=location,
            listing_url=listing_url,
            image_url=image_url,
        )
    except ValidationError as exc:
        logger.warning("Validation failed for a listing card on %s: %s", page_url, exc)
        return None
    except Exception:  # noqa: BLE001 - never let one bad card kill the run
        logger.exception("Unexpected error parsing a listing card on %s", page_url)
        return None


def parse_search_page(html: str, page_url: str) -> list[WatchListing]:
    """Parse every listing card on a single search-results page."""
    soup = BeautifulSoup(html, "lxml")
    cards = soup.select(config.SELECTORS["listing_card"])
    logger.info("Found %d listing cards on %s", len(cards), page_url)

    listings: list[WatchListing] = []
    for card in cards:
        listing = parse_listing_card(card, page_url)
        if listing is not None:
            listings.append(listing)
    return listings


async def _launch_browser():
    playwright = await async_playwright().start()
    launch_kwargs: dict = {"headless": config.HEADLESS}
    if config.PROXY_SERVER:
        proxy: dict = {"server": config.PROXY_SERVER}
        if config.PROXY_USERNAME:
            proxy["username"] = config.PROXY_USERNAME
        if config.PROXY_PASSWORD:
            proxy["password"] = config.PROXY_PASSWORD
        launch_kwargs["proxy"] = proxy

    browser: Browser = await playwright.chromium.launch(**launch_kwargs)
    return playwright, browser


async def _new_page(browser: Browser):
    """Create a fresh browser context + page for a single page fetch.

    Chrono24 sits behind Cloudflare, which flags rapid sequential
    navigations *within the same browser context* as bot-like and serves a
    403 challenge page. Issuing each search-results page request from its
    own short-lived context (fresh cookie jar / fingerprint state, same
    browser process) reliably avoids that challenge while still reusing one
    browser instance for the whole crawl.
    """
    context = await browser.new_context(
        user_agent=config.USER_AGENT,
        viewport=config.VIEWPORT,
        locale=config.LOCALE,
        extra_http_headers=config.EXTRA_HTTP_HEADERS,
    )
    context.set_default_navigation_timeout(config.NAVIGATION_TIMEOUT_MS)
    page: Page = await context.new_page()
    return context, page


_CHALLENGE_MARKERS = ("Just a moment", "cf-chl", "Attention Required")


def _looks_like_bot_challenge(status: Optional[int], html: str) -> bool:
    if status in (403, 429, 503):
        return True
    return any(marker in html for marker in _CHALLENGE_MARKERS)


async def fetch_page_html(page: Page, url: str) -> str:
    logger.info("Navigating to %s", url)
    response = await page.goto(url, wait_until="domcontentloaded")
    status = response.status if response else None
    try:
        await page.wait_for_selector(config.SELECTORS["listing_card"], timeout=config.SELECTOR_TIMEOUT_MS)
    except Exception:
        logger.warning("Listing cards did not appear in time on %s (page may be empty/blocked)", url)
    html = await page.content()
    if _looks_like_bot_challenge(status, html):
        logger.warning(
            "Anti-bot challenge detected on %s (status=%s). Consider a residential/rotating "
            "proxy (see PROXY_SERVER in config.py) and longer delays for production use.",
            url, status,
        )
    return html


async def scrape_rolex_listings(
    max_pages: int = config.MAX_PAGES,
    max_items: int = config.MAX_ITEMS,
) -> list[WatchListing]:
    """Crawl Chrono24 Rolex search pages and return validated listings.

    Stops early once either ``max_pages`` pages have been visited or
    ``max_items`` validated listings have been collected, whichever comes
    first.
    """
    all_listings: list[WatchListing] = []
    playwright = browser = None

    try:
        playwright, browser = await _launch_browser()

        for page_number in range(1, max_pages + 1):
            if len(all_listings) >= max_items:
                break

            url = config.BASE_URL if page_number == 1 else config.PAGE_URL_TEMPLATE.format(page=page_number)

            context, page = await _new_page(browser)
            try:
                try:
                    html = await fetch_page_html(page, url)
                except Exception:
                    logger.exception("Failed to fetch %s; stopping pagination", url)
                    break
            finally:
                await context.close()

            page_listings = parse_search_page(html, url)
            if not page_listings:
                logger.info("No listings found on %s; stopping pagination", url)
                break

            remaining = max_items - len(all_listings)
            all_listings.extend(page_listings[:remaining])

            if page_number < max_pages and len(all_listings) < max_items:
                delay = random.uniform(config.DELAY_MIN_SECONDS, config.DELAY_MAX_SECONDS)
                logger.info("Sleeping %.1fs before next page (human-like pacing)", delay)
                await asyncio.sleep(delay)
    finally:
        if browser is not None:
            await browser.close()
        if playwright is not None:
            await playwright.stop()

    logger.info("Scrape complete: %d validated listings", len(all_listings))
    return all_listings
