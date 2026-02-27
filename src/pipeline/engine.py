"""Pipeline engine — orchestrates stock × date mapping across all providers.

Flow per (stock, date):
  1. Market  — fetch_ohlcv → Pct_Change, Volume
  2. News    — fetch_headline (Google → NewsData → default)
  3. Sentiment — FinBERTProvider.analyze(headline)
  4. Fundamentals — fetch_fundamentals → YoY_NetIncome_%
  5. Assemble PipelineRow and append to output list

Serialises to output/pre_market_sentiment.csv with composite key (Stock, Date).
Failures on a single (stock, date) are logged and skipped — the engine always
continues to the next row.
"""

import os
import csv
import json
from datetime import datetime, timedelta
from typing import List, Optional

from src.core.config import load_config  # noqa: F401
from src.core.logger import logger
from src.core.news_utils import get_long_name
from src.core.cache import SQLiteCache
from src.models.datatypes import NewsArticle, PipelineRow
from src.providers.market import YFinanceProvider
from src.providers.news import (
    GoogleNewsProvider, NewsDataProvider, fetch_headline,
    DEFAULT_HEADLINE, DEFAULT_SOURCE,
)
from src.providers.sentiment import FinBERTProvider

_CSV_HEADER = [
    "Date", "Stock", "Pct_Change", "Volume",
    "Headline", "Sentiment_Label", "Sentiment_Score",
    "YoY_NetIncome_Pct", "Data_Source_Log",
]


class PipelineEngine:
    """Orchestrates the full pre-market sentiment pipeline.

    Args:
        config: Parsed config.yaml dict (passed in; not re-loaded internally).
        output_dir: Directory where ``pre_market_sentiment.csv`` is written.
    """

    def __init__(self, config: dict, output_dir: str = "output") -> None:
        self.config = config
        self.output_dir = output_dir

        api_key = os.getenv("NEWSDATA_API_KEY", "")
        cache = SQLiteCache()

        self.market = YFinanceProvider()
        self.google = GoogleNewsProvider(cache_instance=cache)
        self.newsdata = NewsDataProvider(api_key=api_key, cache_instance=cache)
        self.sentiment = FinBERTProvider()

    # ── public ────────────────────────────────────────────────────────────────

    def run(self) -> List[PipelineRow]:
        """Run the pipeline for all stocks × all dates in config.

        Returns:
            List of assembled :class:`PipelineRow` objects.
        """
        stocks = self.config.get("stocks", [])
        start = self.config["date_range"]["start"]
        end = self.config["date_range"]["end"]
        lookback = self.config.get("news", {}).get("lookback_window_hours", 72)
        dates = _trading_dates(start, end)

        logger.info(
            f"PipelineEngine: {len(stocks)} stocks × {len(dates)} dates "
            f"= {len(stocks) * len(dates)} rows target"
        )

        # Fetch OHLCV for all stocks in one call per stock (covers full range)
        ohlcv_cache: dict = {}
        fundamentals_cache: dict = {}
        for stock in stocks:
            try:
                df = self.market.fetch_ohlcv(stock, start, end)
                ohlcv_cache[stock] = df
            except Exception as exc:
                logger.error(f"PipelineEngine: fetch_ohlcv failed for {stock}: {exc}")
                ohlcv_cache[stock] = None
            try:
                fundamentals_cache[stock] = self.market.fetch_fundamentals(stock)
            except Exception as exc:
                logger.error(f"PipelineEngine: fetch_fundamentals failed for {stock}: {exc}")
                fundamentals_cache[stock] = None

        self._write_market_data(ohlcv_cache, fundamentals_cache)

        rows: List[PipelineRow] = []
        for date in dates:
            for stock in stocks:
                row = self._process_row(
                    stock, date, lookback,
                    ohlcv_cache, fundamentals_cache,
                )
                if row:
                    rows.append(row)

        self._write_csv(rows)
        logger.info(
            f"PipelineEngine: wrote {len(rows)} rows to "
            f"{self.output_dir}/pre_market_sentiment.csv"
        )
        return rows

    # ── internal ──────────────────────────────────────────────────────────────

    def _process_row(
        self,
        stock: str,
        date: str,
        lookback: int,
        ohlcv_cache: dict,
        fundamentals_cache: dict,
    ) -> Optional[PipelineRow]:
        """Build one PipelineRow for (stock, date). Returns None on hard failure."""
        log_parts: List[str] = []

        # ── Market data ───────────────────────────────────────────────────────
        pct_change: Optional[float] = None
        volume: Optional[int] = None
        df = ohlcv_cache.get(stock)
        if df is not None and not df.empty:
            day_row = df[df["Date"] == date]
            if not day_row.empty:
                pct_change = round(float(day_row["Pct_Change"].iloc[0]), 4)
                volume = int(day_row["Volume"].iloc[0])
                log_parts.append("market=yfinance")
            else:
                logger.warning(f"PipelineEngine: no OHLCV row for {stock} on {date}")
                log_parts.append("market=missing_date")
        else:
            logger.warning(f"PipelineEngine: no OHLCV data for {stock}")
            log_parts.append("market=unavailable")

        if pct_change is None or volume is None:
            logger.error(f"PipelineEngine: skipping ({stock}, {date}) — market data required")
            return None

        # ── News + Sentiment ──────────────────────────────────────────────────
        try:
            long_name = get_long_name(stock)
            article, news_source = fetch_headline(
                stock, long_name, date,
                self.google, self.newsdata, lookback,
            )
            log_parts.append(f"news={news_source}")
        except Exception as exc:
            logger.error(f"PipelineEngine: fetch_headline failed for {stock}/{date}: {exc}")
            article = NewsArticle(
                headline=DEFAULT_HEADLINE, source=DEFAULT_SOURCE,
                url="", published_at=date,
            )
            log_parts.append("news=error")

        try:
            result = self.sentiment.analyze(article.headline)
            sentiment_label = result.label
            sentiment_score = result.score
            log_parts.append("sentiment=finbert")
        except Exception as exc:
            logger.error(f"PipelineEngine: sentiment failed for {stock}/{date}: {exc}")
            sentiment_label = "Neutral"
            sentiment_score = 0.0
            log_parts.append("sentiment=error")

        # ── Fundamentals ─────────────────────────────────────────────────────
        yoy = fundamentals_cache.get(stock)
        log_parts.append("fundamentals=yfinance" if yoy is not None else "fundamentals=unavailable")

        return PipelineRow(
            date=date,
            stock=stock,
            pct_change=pct_change,
            volume=volume,
            headline=article.headline,
            sentiment_label=sentiment_label,
            sentiment_score=sentiment_score,
            yoy_net_income_pct=yoy,
            data_source_log=" | ".join(log_parts),
        )

    def _write_csv(self, rows: List[PipelineRow]) -> None:
        """Write rows to output/pre_market_sentiment.csv (overwrites each run)."""
        os.makedirs(self.output_dir, exist_ok=True)
        path = os.path.join(self.output_dir, "pre_market_sentiment.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=_CSV_HEADER)
            writer.writeheader()
            for row in rows:
                writer.writerow({
                    "Date": row.date,
                    "Stock": row.stock,
                    "Pct_Change": row.pct_change,
                    "Volume": row.volume,
                    "Headline": row.headline,
                    "Sentiment_Label": row.sentiment_label,
                    "Sentiment_Score": row.sentiment_score,
                    "YoY_NetIncome_Pct": (
                        row.yoy_net_income_pct
                        if row.yoy_net_income_pct is not None else ""
                    ),
                    "Data_Source_Log": row.data_source_log,
                })

    def _write_market_data(
        self,
        ohlcv_cache: dict,
        fundamentals_cache: dict,
    ) -> None:
        """Persist raw market data to output/ for audit and inspection.

        Writes:
        - ``output/ohlcv_<STOCK>.csv`` — OHLCV rows for each stock.
        - ``output/fundamentals.json`` — YoY net income % per stock.
        """
        os.makedirs(self.output_dir, exist_ok=True)

        # ── OHLCV: one CSV per stock ──────────────────────────────────────────
        for stock, df in ohlcv_cache.items():
            if df is None or df.empty:
                continue
            path = os.path.join(self.output_dir, f"ohlcv_{stock}.csv")
            df.to_csv(path, index=False)
            logger.info(f"PipelineEngine: saved OHLCV for {stock} → {path}")

        # ── Fundamentals: single JSON with all stocks ─────────────────────────
        fund_path = os.path.join(self.output_dir, "fundamentals.json")
        data = {
            stock: val
            for stock, val in fundamentals_cache.items()
        }
        with open(fund_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        logger.info(f"PipelineEngine: saved fundamentals → {fund_path}")


# ── helpers ───────────────────────────────────────────────────────────────────

def _trading_dates(start: str, end: str) -> List[str]:
    """Return Mon–Fri dates between start and end inclusive (YYYY-MM-DD strings).

    This is a best-effort filter — NSE-specific holidays are not excluded here.
    The market provider returns an empty row for non-trading days which are then
    skipped by _process_row.
    """
    start_dt = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")
    dates = []
    cur = start_dt
    while cur <= end_dt:
        if cur.weekday() < 5:   # Mon=0 … Fri=4
            dates.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
    return dates
