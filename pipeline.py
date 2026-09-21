"""
Data pipeline: turn validated WatchListing objects into cleaned exports
(JSON + CSV) on disk.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

import config
from models import WatchListing

logger = logging.getLogger(__name__)

_COLUMN_ORDER = [
    "watch_id",
    "title",
    "model",
    "price",
    "currency",
    "location",
    "listing_url",
    "image_url",
    "scraped_at",
]


def to_dataframe(listings: list[WatchListing]) -> pd.DataFrame:
    """Convert validated listings into a cleaned, deduplicated DataFrame."""
    if not listings:
        return pd.DataFrame(columns=_COLUMN_ORDER)

    records = [listing.model_dump(mode="json") for listing in listings]
    df = pd.DataFrame.from_records(records)

    df = df.drop_duplicates(subset="watch_id", keep="first")
    df = df.sort_values("watch_id").reset_index(drop=True)

    for column in _COLUMN_ORDER:
        if column not in df.columns:
            df[column] = None
    df = df[_COLUMN_ORDER]

    return df


def save_json(listings: list[WatchListing], path: Path = config.JSON_OUTPUT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [listing.model_dump(mode="json") for listing in listings]
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    logger.info("Wrote %d listings to %s", len(payload), path)


def save_csv(df: pd.DataFrame, path: Path = config.CSV_OUTPUT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8")
    logger.info("Wrote %d rows to %s", len(df), path)


def process_and_save(listings: list[WatchListing]) -> pd.DataFrame:
    """Clean/dedupe listings and persist them as both JSON and CSV."""
    df = to_dataframe(listings)

    # Re-derive the deduplicated listing set (in original model form) so the
    # JSON export matches the CSV 1:1.
    kept_ids = set(df["watch_id"])
    deduped = [listing for listing in listings if listing.watch_id in kept_ids]
    seen: set[str] = set()
    unique_listings = []
    for listing in deduped:
        if listing.watch_id not in seen:
            unique_listings.append(listing)
            seen.add(listing.watch_id)

    save_json(unique_listings, config.JSON_OUTPUT_PATH)
    save_csv(df, config.CSV_OUTPUT_PATH)
    return df
