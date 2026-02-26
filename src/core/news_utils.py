"""Utility helpers for the news pipeline — longName resolution and caching."""

import json
import os
import re
from typing import Optional

import yfinance as yf

from src.core.config import load_config
from src.core.logger import logger

_CACHE_FILENAME = "stock_aliases.json"

# Corporate suffixes stripped before constructing search queries.
# Only true legal suffixes — business descriptors like 'Industries' or
# 'Services' are intentionally excluded to avoid stripping meaningful words.
CORPORATE_SUFFIXES = [
    "limited", "ltd", "ltd.", "corporation", "corp", "corp.",
]


def strip_suffix(long_name: str) -> str:
    """Remove trailing corporate suffixes from a company long name.

    Examples:
        ``"Bank of India Limited"`` → ``"Bank of India"``
        ``"Hindustan Zinc Ltd."`` → ``"Hindustan Zinc"``

    Args:
        long_name (str): Full company name from yfinance.

    Returns:
        str: Name with trailing corporate suffix removed, stripped of whitespace.
    """
    pattern = r"[\s,]+(" + "|".join(re.escape(s) for s in CORPORATE_SUFFIXES) + r")[\s.]*$"
    return re.sub(pattern, "", long_name, flags=re.IGNORECASE).strip()


def _is_relevant_title(title: str, long_name: str, ticker: str = "") -> bool:
    """Return True if the article title contains the company name or ticker
    as a standalone phrase — not embedded inside a longer entity name.

    Uses ``re.finditer`` + preceding-character check so that e.g.
    ``"State Bank of India"`` is rejected when ``search_name="Bank of India"``,
    while ``"Vedanta, BPCL, Hindustan Zinc among..."`` correctly passes for
    ``search_name="Hindustan Zinc"`` (comma precedes, not a letter).

    Args:
        title (str): Article headline text.
        long_name (str): Full company long name (e.g. ``"Bank of India Limited"``).
        ticker (str): NSE ticker symbol (e.g. ``"BANKINDIA"``) — optional extra term.

    Returns:
        bool: ``True`` if title is relevant to the stock.
    """
    title_lower = title.lower()

    def _standalone_match(text: str, phrase: str) -> bool:
        """Return True if phrase appears in text and is not preceded by a letter."""
        pattern = r'\b' + re.escape(phrase) + r'\b'
        for m in re.finditer(pattern, text):
            before = text[:m.start()].rstrip()
            if before and before[-1].isalpha():
                continue  # embedded inside a longer entity word — skip
            return True
        return False

    if _standalone_match(title_lower, long_name.lower()):
        return True

    stripped = strip_suffix(long_name).lower()
    if stripped and _standalone_match(title_lower, stripped):
        return True

    if ticker and _standalone_match(title_lower, ticker.lower()):
        return True

    return False



def _cache_path() -> str:
    """Return the absolute path to stock_aliases.json inside output_dir."""
    config = load_config()
    output_dir = config.get("output_dir", "output")
    os.makedirs(output_dir, exist_ok=True)
    return os.path.join(output_dir, _CACHE_FILENAME)


def _load_cache() -> dict:
    """Load the stock_aliases.json cache from disk. Returns empty dict if absent."""
    path = _cache_path()
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_cache(data: dict) -> None:
    """Persist the updated cache dict back to stock_aliases.json."""
    with open(_cache_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_long_name(stock: str) -> str:
    """Return the company longName for a given NSE ticker.

    Resolution order:
      1. ``output/stock_aliases.json`` (local cache) — zero network cost.
      2. ``yf.Ticker("<stock>.NS").info["longName"]`` — one network call, result cached.
      3. Raw ticker symbol — used when yfinance fails or returns an empty string.

    Args:
        stock (str): NSE ticker without the ``.NS`` suffix (e.g. ``"BANKINDIA"``).

    Returns:
        str: Company long name (e.g. ``"Bank of India"``), or the ticker as fallback.
    """
    cache = _load_cache()

    if stock in cache:
        logger.debug(f"get_long_name cache hit: {stock} → {cache[stock]}")
        return cache[stock]

    long_name = _fetch_long_name_from_yfinance(stock)

    cache[stock] = long_name
    _save_cache(cache)
    logger.info(f"get_long_name cached: {stock} → {long_name}")
    return long_name


def _fetch_long_name_from_yfinance(stock: str) -> str:
    """Fetch longName from yfinance, with a fallback to the raw ticker.

    Args:
        stock (str): NSE ticker without suffix.

    Returns:
        str: longName from yfinance, or the raw ticker on failure.
    """
    symbol = f"{stock}.NS"
    try:
        info: dict = yf.Ticker(symbol).info
        long_name: Optional[str] = info.get("longName", "").strip()
        if long_name:
            return long_name
        logger.warning(
            f"get_long_name: yfinance returned empty longName for {symbol}. "
            f"Falling back to ticker symbol."
        )
    except Exception as exc:
        logger.warning(
            f"get_long_name: yfinance raised for {symbol}: {exc}. "
            f"Falling back to ticker symbol."
        )
    return stock
