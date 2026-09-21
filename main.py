"""
Entry point: run the Chrono24 Rolex scraper end-to-end.

Usage:
    python main.py
"""
from __future__ import annotations

import asyncio
import logging
import sys
import time

import config
import pipeline
from scraper import scrape_rolex_listings


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(config.LOG_FILE_PATH, encoding="utf-8"),
        ],
    )


async def run() -> int:
    logger = logging.getLogger("main")
    logger.info(
        "Starting Chrono24 Rolex scrape (max_pages=%d, max_items=%d)",
        config.MAX_PAGES,
        config.MAX_ITEMS,
    )

    started = time.perf_counter()
    listings = await scrape_rolex_listings(max_pages=config.MAX_PAGES, max_items=config.MAX_ITEMS)
    elapsed = time.perf_counter() - started

    if not listings:
        logger.error("No listings were scraped. Chrono24's markup may have changed, "
                      "or the request was blocked. See logs above for details.")
        return 1

    df = pipeline.process_and_save(listings)

    priced = df["price"].dropna()
    logger.info("=" * 60)
    logger.info("SCRAPE SUMMARY")
    logger.info("  Listings collected : %d", len(df))
    logger.info("  Elapsed time       : %.1fs", elapsed)
    logger.info("  Price range        : %s - %s",
                 f"${priced.min():,.2f}" if not priced.empty else "n/a",
                 f"${priced.max():,.2f}" if not priced.empty else "n/a")
    logger.info("  Average price      : %s",
                 f"${priced.mean():,.2f}" if not priced.empty else "n/a")
    logger.info("  JSON output        : %s", config.JSON_OUTPUT_PATH)
    logger.info("  CSV output         : %s", config.CSV_OUTPUT_PATH)
    logger.info("=" * 60)
    return 0


def main() -> None:
    configure_logging()
    exit_code = asyncio.run(run())
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
