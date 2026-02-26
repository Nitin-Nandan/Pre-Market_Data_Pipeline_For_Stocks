"""
4.4 Verification — runs fetch_headline orchestrator end-to-end for all stocks
and prints structured output: provider used, headline selected, log reason.

Run with:
    $env:PYTHONPATH="."; python scripts/verify_phase4.py
"""

import os
import logging
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Show INFO logs on console for verification
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)

from src.core.config import load_config
from src.core.news_utils import get_long_name
from src.core.cache import SQLiteCache
from src.providers.news import GoogleNewsProvider, NewsDataProvider, fetch_headline

DIVIDER = "=" * 70


def main():
    config = load_config()
    stocks = config.get("stocks", [])
    api_key = os.getenv("NEWSDATA_API_KEY")
    if not api_key:
        print("ERROR: NEWSDATA_API_KEY not set in .env")
        return

    date = datetime.now().strftime("%Y-%m-%d")
    cache = SQLiteCache()
    google = GoogleNewsProvider(cache_instance=cache)
    newsdata = NewsDataProvider(api_key=api_key, cache_instance=cache)

    print(f"\n{DIVIDER}")
    print(f"  Phase 4.4 Verification  |  date={date}")
    print(DIVIDER)

    results = []
    for stock in stocks:
        long_name = get_long_name(stock)
        print(f"\n{'─'*70}")
        print(f"  {stock}  |  {long_name}")
        print(f"{'─'*70}")

        article, source = fetch_headline(
            ticker=stock,
            long_name=long_name,
            date=date,
            google=google,
            newsdata=newsdata,
        )

        print(f"  SOURCE   : {source}")
        print(f"  HEADLINE : {article.headline}")
        print(f"  PUB DATE : {article.published_at}")
        print(f"  URL      : {article.url[:80] if article.url else '(none)'}")
        results.append((stock, source, article.headline))

    print(f"\n{DIVIDER}")
    print(f"  SUMMARY")
    print(DIVIDER)
    for stock, source, headline in results:
        disp = headline[:60] + ".." if len(headline) > 62 else headline
        print(f"  {stock:12}  [{source:16}]  {disp}")
    print()


if __name__ == "__main__":
    main()
