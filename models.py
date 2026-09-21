"""
Pydantic v2 data models for validating scraped Rolex listings.

Keeping validation here (rather than sprinkled through the scraper) means
malformed cards fail fast and predictably, and the rest of the pipeline can
trust that every ``WatchListing`` instance it sees is well-formed.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Matches "$14,500", "7.890 €", "CHF 5,200.50", "USD 1234", etc.
_CURRENCY_SYMBOL_RE = re.compile(r"[£$€]|CHF|USD|EUR|GBP", re.IGNORECASE)
_NUMERIC_RE = re.compile(r"[0-9.,]+")


def detect_currency(raw: str | None) -> Optional[str]:
    """Best-effort currency symbol/code extraction from a raw price string."""
    if not raw:
        return None
    match = _CURRENCY_SYMBOL_RE.search(str(raw))
    return match.group(0).upper() if match else None


def clean_price(raw: str | float | int | None) -> Optional[float]:
    """Normalize a currency string (any common locale format) to a float.

    Handles both US-style ("$14,500.00" -> 14500.00) and European-style
    ("7.890 €" -> 7890.00, "1.234,56 €" -> 1234.56) grouping/decimal
    conventions. Returns None if no numeric value can be recovered.
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)

    text = str(raw).strip().replace("\xa0", " ")
    if not text:
        return None

    match = _NUMERIC_RE.search(text)
    if not match:
        return None
    number = match.group(0)

    has_dot = "." in number
    has_comma = "," in number

    if has_dot and has_comma:
        # Whichever separator appears last is the decimal separator.
        if number.rfind(",") > number.rfind("."):
            number = number.replace(".", "").replace(",", ".")
        else:
            number = number.replace(",", "")
    elif has_comma:
        tail = number.split(",")[-1]
        if len(tail) == 3:
            # Thousands grouping, e.g. "7,890" -> 7890
            number = number.replace(",", "")
        else:
            # Decimal comma, e.g. "7,89" -> 7.89
            number = number.replace(",", ".")
    elif has_dot:
        tail = number.split(".")[-1]
        if len(tail) == 3:
            # European thousands grouping, e.g. "7.890" -> 7890
            number = number.replace(".", "")
        # else: already a valid decimal point, e.g. "7890.50"

    try:
        return round(float(number), 2)
    except ValueError:
        return None


class WatchListing(BaseModel):
    """A single validated Rolex listing scraped from a Chrono24 search page."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    watch_id: str = Field(..., min_length=1, description="Unique listing ID (from URL or hash fallback)")
    title: str = Field(..., min_length=1, description="Listing title, e.g. 'Rolex GMT-Master'")
    model: Optional[str] = Field(default=None, description="Subtitle / model reference, e.g. '1675 Vintage Pepsi'")
    price: Optional[float] = Field(default=None, ge=0, description="Cleaned listing price")
    currency: Optional[str] = Field(default=None, description="Currency symbol/code detected in the raw price text")
    location: Optional[str] = Field(default=None, description="Seller country code or city")
    listing_url: str = Field(..., min_length=1, description="Absolute URL to the listing detail page")
    image_url: Optional[str] = Field(default=None, description="Product image source URL")
    scraped_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("price", mode="before")
    @classmethod
    def _parse_price(cls, value):
        if value is None or isinstance(value, (int, float)):
            return value
        return clean_price(value)

    @field_validator("model", "location", mode="before")
    @classmethod
    def _blank_to_none(cls, value):
        if value is None:
            return None
        value = str(value).strip()
        return value or None

    @field_validator("listing_url")
    @classmethod
    def _validate_url(cls, value: str) -> str:
        # Cheap sanity check without forcing a strict HttpUrl type on output
        # (keeps JSON/CSV export as plain strings).
        if not value.startswith(("http://", "https://")):
            raise ValueError(f"listing_url must be absolute, got: {value!r}")
        return value
