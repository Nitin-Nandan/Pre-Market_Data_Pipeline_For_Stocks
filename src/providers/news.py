"""News feed providers and fetch_headline orchestrator.

Pipeline per stock:
  1. GoogleNewsProvider — Query A (company name) → Query B (ticker)
  2. NewsDataProvider   — Query A (company name) → Query B (ticker)
  3. Default headline   — "No major headline available" / Neutral / 0.0

Each provider tries the name-based query first (with _is_relevant_title filter)
and falls through to the ticker-based query (no title filter — query is the signal).
"""

import json
import time
import urllib.parse
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

import feedparser
import requests

from src.core.logger import logger
from src.core.cache import SQLiteCache
from src.core.news_utils import strip_suffix, _is_relevant_title
from src.providers.base import NewsProvider
from src.models.datatypes import NewsArticle

_NEWSDATA_URL = "https://newsdata.io/api/1/latest"
_GOOGLE_RSS_BASE = "https://news.google.com/rss/search"
_PUBDATE_FMT = "%Y-%m-%d %H:%M:%S"

DEFAULT_HEADLINE = "No major headline available"
DEFAULT_SOURCE = "default"


# ── NewsDataProvider ──────────────────────────────────────────────────────────

class NewsDataProvider(NewsProvider):
    """NewsData.io /api/1/latest provider.

    Tries two queries per call:
    - Query A: ``'"<search_name>"'`` with title relevance + 72hr window filter.
    - Query B: ``'"<ticker>"'`` without title filter (ticker is self-selective).
    Free-tier: 200 credits/day. Cache key is date-only to protect this limit.
    """

    def __init__(self, api_key: str, cache_instance: SQLiteCache = None) -> None:
        """Args:
            api_key: NewsData.io API key.
            cache_instance: Shared SQLite cache (created if not provided).
        """
        self.api_key = api_key
        self.cache = cache_instance or SQLiteCache()

    def fetch_news(
        self,
        ticker: str,
        long_name: str,
        date: str,
        lookback_window_hours: int = 72,
    ) -> Optional[NewsArticle]:
        """Return the best article from NewsData or None.

        Args:
            ticker: NSE ticker without ``.NS`` (e.g. ``"BANKINDIA"``).
            long_name: Full company name (e.g. ``"Bank of India Limited"``).
            date: Reference date ``YYYY-MM-DD`` used as cache key.
            lookback_window_hours: Lookback window from ``datetime.now()``.

        Returns:
            Most recent relevant article, or ``None``.
        """
        search_name = strip_suffix(long_name)

        # Query A — company name, title filter ON
        result = self._try_query(
            ticker, long_name, date, lookback_window_hours,
            q=f'"{search_name}"', cache_sfx="name", title_filter=True,
        )
        if result:
            return result

        # Query B — ticker symbol, title filter OFF
        return self._try_query(
            ticker, long_name, date, lookback_window_hours,
            q=f'"{ticker}"', cache_sfx="ticker", title_filter=False,
        )

    def _try_query(
        self,
        ticker: str,
        long_name: str,
        date: str,
        lookback_window_hours: int,
        q: str,
        cache_sfx: str,
        title_filter: bool,
    ) -> Optional[NewsArticle]:
        """Run one NewsData query (cache-aware) and return best article or None."""
        cache_key = f"newsdata_{ticker}_{date}_{cache_sfx}"
        raw_cached = self.cache.get(cache_key)

        if raw_cached:
            logger.debug(f"NewsDataProvider: cache hit [{cache_sfx}] for {ticker}")
            results: List[dict] = json.loads(raw_cached)
        else:
            results = self._call_api(ticker, q)
            if results is None:
                return None
            self.cache.set(cache_key, json.dumps(results))

        return self._select_best(
            results, ticker, long_name, date, lookback_window_hours, title_filter
        )

    def _call_api(self, ticker: str, q: str) -> Optional[List[dict]]:
        """Call /api/1/latest. Returns result list or None on failure."""
        logger.info(f"NewsDataProvider: fetching for {ticker} (q={q})")
        params = {
            "apikey": self.api_key,
            "q": q,
            "language": "en",
            "country": "in",
            "category": "business",
            "prioritydomain": "top",
            "removeduplicate": 1,
        }
        try:
            time.sleep(1)
            resp = requests.get(_NEWSDATA_URL, params=params, timeout=15)
        except requests.RequestException as exc:
            logger.error(f"NewsDataProvider: INFRA_FAILURE for {ticker}: {exc}")
            return None

        if resp.status_code != 200:
            logger.error(
                f"NewsDataProvider: INFRA_FAILURE for {ticker} "
                f"HTTP {resp.status_code}: {resp.text[:200]}"
            )
            return None

        return resp.json().get("results", [])

    def _select_best(
        self,
        results: List[dict],
        ticker: str,
        long_name: str,
        date: str,
        lookback_window_hours: int,
        use_title_filter: bool,
    ) -> Optional[NewsArticle]:
        """Filter by relevance + window, return most recent or None."""
        cutoff = datetime.now() - timedelta(hours=lookback_window_hours)
        candidates = []

        for article in results:
            title = (article.get("title") or "").strip()
            if not title:
                continue
            if use_title_filter and not _is_relevant_title(title, long_name, ticker):
                logger.debug(f"NewsDataProvider: skipped (title): {title!r}")
                continue
            pub_str = article.get("pubDate", "")
            try:
                pub_dt = datetime.strptime(pub_str, _PUBDATE_FMT)
            except ValueError:
                continue
            if pub_dt < cutoff:
                continue
            candidates.append((pub_dt, article))

        if not candidates:
            return None
        pub_dt, best = max(candidates, key=lambda x: x[0])
        headline = (best.get("title") or "").strip()
        logger.info(
            f"NewsDataProvider: selected [{pub_dt:%Y-%m-%d %H:%M}] {headline!r}"
        )
        return NewsArticle(
            headline=headline,
            source=best.get("source_id") or "NewsData",
            url=best.get("link") or best.get("url") or "",
            published_at=pub_dt.strftime(_PUBDATE_FMT),
            summary=best.get("description") or "",
        )


# ── GoogleNewsProvider ────────────────────────────────────────────────────────

class GoogleNewsProvider(NewsProvider):
    """Google News RSS provider.

    Tries two queries per call:
    - Query A: ``"<search_name>" (NSE OR shares OR stock) when:3d`` — title filter ON.
    - Query B: ``"<ticker>" NSE when:3d`` — title filter OFF (ticker is self-selective).
    ``when:3d`` handles server-side date filtering.
    """

    def __init__(self, cache_instance: SQLiteCache = None) -> None:
        """Args:
            cache_instance: Shared SQLite cache (created if not provided).
        """
        self.cache = cache_instance or SQLiteCache()

    def fetch_news(
        self,
        ticker: str,
        long_name: str,
        date: str,
        lookback_window_hours: int = 72,
    ) -> Optional[NewsArticle]:
        """Return the best article from Google News RSS or None.

        Args:
            ticker: NSE ticker without ``.NS``.
            long_name: Full company name.
            date: Reference date ``YYYY-MM-DD`` used as cache key.
            lookback_window_hours: Not used directly — ``when:3d`` filters server-side.

        Returns:
            Most recent relevant article, or ``None``.
        """
        search_name = strip_suffix(long_name)

        # Query A — company name, title filter ON
        q_a = f'"{search_name}" (NSE OR shares OR stock) when:3d'
        result = self._try_query(ticker, long_name, date, q_a,
                                  cache_sfx="name", title_filter=True)
        if result:
            return result

        # Query B — ticker symbol, title filter OFF
        q_b = f'"{ticker}" NSE when:3d'
        return self._try_query(ticker, long_name, date, q_b,
                                cache_sfx="ticker", title_filter=False)

    def _try_query(
        self,
        ticker: str,
        long_name: str,
        date: str,
        query: str,
        cache_sfx: str,
        title_filter: bool,
    ) -> Optional[NewsArticle]:
        """Run one Google News RSS query (cache-aware) and return best article or None."""
        cache_key = f"gnews_{ticker}_{date}_{cache_sfx}"
        raw_cached = self.cache.get(cache_key)

        if raw_cached:
            logger.debug(f"GoogleNewsProvider: cache hit [{cache_sfx}] for {ticker}")
            entries: list = json.loads(raw_cached)
        else:
            entries = self._fetch_rss(ticker, query)
            if entries is None:
                return None
            self.cache.set(cache_key, json.dumps(entries))

        return self._select_best(entries, ticker, long_name, date, title_filter)

    def _fetch_rss(self, ticker: str, query: str) -> Optional[list]:
        """Fetch and parse Google News RSS. Returns list of entry dicts or None."""
        encoded = urllib.parse.quote(query)
        url = f"{_GOOGLE_RSS_BASE}?q={encoded}&hl=en-IN&gl=IN&ceid=IN:en"
        logger.info(f"GoogleNewsProvider: fetching [{ticker}] q={query!r}")

        try:
            feed = feedparser.parse(url)
        except Exception as exc:
            logger.error(f"GoogleNewsProvider: INFRA_FAILURE for {ticker}: {exc}")
            return None

        if feed.bozo and hasattr(feed, "bozo_exception"):
            logger.warning(
                f"GoogleNewsProvider: RSS parse warning for {ticker}: "
                f"{feed.bozo_exception} | url={url}"
            )

        entries = []
        for entry in feed.entries:
            title = getattr(entry, "title", "").strip()
            if not title:
                continue
            pub_parsed = getattr(entry, "published_parsed", None)
            pub_str = (
                datetime(*pub_parsed[:6]).strftime(_PUBDATE_FMT)
                if pub_parsed else ""
            )
            source_raw = getattr(entry, "source", {})
            source = (
                source_raw.get("title", "Google News")
                if isinstance(source_raw, dict)
                else str(source_raw) or "Google News"
            )
            entries.append({
                "title": title,
                "source": source,
                "url": getattr(entry, "link", ""),
                "published_at": pub_str,
                "summary": getattr(entry, "summary", ""),
            })

        logger.info(f"GoogleNewsProvider: {len(entries)} entries for {ticker}")
        return entries

    def _select_best(
        self,
        entries: list,
        ticker: str,
        long_name: str,
        date: str,
        use_title_filter: bool,
    ) -> Optional[NewsArticle]:
        """Filter by relevance, return most recent or None."""
        candidates = []
        for entry in entries:
            title = entry.get("title", "")
            if use_title_filter and not _is_relevant_title(title, long_name, ticker):
                logger.debug(f"GoogleNewsProvider: skipped (title): {title!r}")
                continue
            pub_str = entry.get("published_at", "")
            candidates.append((pub_str, entry))

        if not candidates:
            return None
        pub_str, best = max(candidates, key=lambda x: x[0])
        headline = best["title"]
        logger.info(f"GoogleNewsProvider: selected [{pub_str}] {headline!r}")
        return NewsArticle(
            headline=headline,
            source=best.get("source", "Google News"),
            url=best.get("url", ""),
            published_at=pub_str or date,
            summary=best.get("summary", ""),
        )


# ── Orchestrator ──────────────────────────────────────────────────────────────

def fetch_headline(
    ticker: str,
    long_name: str,
    date: str,
    google: GoogleNewsProvider,
    newsdata: NewsDataProvider,
    lookback_window_hours: int = 72,
) -> Tuple[NewsArticle, str]:
    """Orchestrate Google → NewsData → default to produce one headline per stock.

    Args:
        ticker: NSE ticker without ``.NS``.
        long_name: Full company name from ``get_long_name``.
        date: Reference date ``YYYY-MM-DD``.
        google: Initialised ``GoogleNewsProvider``.
        newsdata: Initialised ``NewsDataProvider``.
        lookback_window_hours: Lookback window (applies to NewsData; Google uses when:3d).

    Returns:
        Tuple of ``(NewsArticle, source_label)`` where source_label is one of:
        ``"google"``, ``"google_ticker"``, ``"newsdata"``, ``"newsdata_ticker"``,
        ``"default"``.
    """
    # ── Step 1: Google News (primary) ─────────────────────────────────────────
    try:
        article = google.fetch_news(ticker, long_name, date, lookback_window_hours)
        if article:
            logger.info(
                f"HEADLINE [{ticker}] source=google | {article.headline!r}"
            )
            return article, "google"
    except Exception as exc:
        logger.error(f"HEADLINE [{ticker}] GoogleNewsProvider raised: {exc}")

    # ── Step 2: NewsData.io (fallback) ────────────────────────────────────────
    try:
        article = newsdata.fetch_news(ticker, long_name, date, lookback_window_hours)
        if article:
            logger.info(
                f"HEADLINE [{ticker}] source=newsdata | {article.headline!r}"
            )
            return article, "newsdata"
    except Exception as exc:
        logger.error(f"HEADLINE [{ticker}] NewsDataProvider raised: {exc}")

    # ── Step 3: Default ───────────────────────────────────────────────────────
    _log_default_reason(ticker, date)
    return NewsArticle(
        headline=DEFAULT_HEADLINE,
        source=DEFAULT_SOURCE,
        url="",
        published_at=date,
        summary="",
    ), "default"


def _log_default_reason(ticker: str, date: str) -> None:
    """Log a structured reason code when both providers return None."""
    logger.warning(
        f"HEADLINE [{ticker}] source=default | date={date} | "
        f"reason=COVERAGE_GAP — no article survived filters from either provider"
    )
