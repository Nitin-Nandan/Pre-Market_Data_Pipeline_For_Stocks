# Phase 4 Alternatives: Designing Free News Pipelines for NSE Stocks

## Executive Summary
This document investigates why the current News API providers (Finnhub, NewsData.io) return 0 articles for NSE stocks in the free tier, and outlines viable 100% free, highly scalable alternatives for the data pipeline. 

---

## 1. Why the Current Providers Fail on the Free Tier

### Finnhub's Limitations
- **Geo-Restrictions:** Finnhub's `/company-news` endpoint strictly provides news exclusively for **US markets** on the Free Tier.
- **The `.NS` Error:** When we queried `BANKINDIA.NS`, it threw a `403 Forbidden` because Finnhub blocks international tickers for free users. 
- **The Empty Response:** When we stripped the suffix and queried `BANKINDIA`, it returned `200 OK` but `0 articles`. Because there is no US stock named BANKINDIA, it silently found no matches.

### NewsData.io's Limitations
- **Time Horizon:** The NewsData.io Free Tier API restricts searches to articles published within the exact **past 48 hours** natively. 
- **The Empty Response:** Unless major financial news in English broke for mid-cap/small-cap companies (like Prime Focus) over the specific weekend or the last 48 hours precisely, the API legitimately returns `0 articles`.

---

## 2. Viable 100% Free Alternatives for NSE Stocks

Since the project parameters require exactly zero-cost and favor the "latest" headlines (as patched in our previous update), we have two outstanding programmatic options that require absolutely no API keys.

### Option A: `yfinance` Native News Fetching (Recommended)
You already have `yfinance` installed for market data. It actually contains a robust internal news scraper.
*   **How it works:** `yf.Ticker("BANKINDIA.NS").news` natively returns a list of dictionaries containing Yahoo Finance headlines concerning that specific ticker.
*   **Pros:** 
    *   100% Free and NO API Key required.
    *   Already installed in our environment.
    *   Perfectly maps to the exact `.NS` tickers we already use.
    *   Returns structured fields (`title`, `providerPublishTime`, `publisher`, `link`).
*   **Cons:** 
    *   Restricted to the 8 most recent articles. 
    *   Does not support searching historical dates (e.g., getting news exactly from 3 years ago), but since we updated the code to fetch "latest" dynamically anyway, this operates flawlessly.

### Option B: Google News RSS Feed (Robust Fallback)
Google News provides a native RSS Feed for any keyword search that can be queried publicly. 
*   **How it works:** `https://news.google.com/rss/search?q={search_term}` returns a structured XML document.
*   **Pros:** 
    *   100% Free and NO API Key required.
    *   Massive indexing of Indian news (Moneycontrol, Mint, Economic Times).
    *   We can leverage the excellent `StockAliases` architecture we just built (e.g., searching for `"bank of india" + "NSE"`) to get perfectly relevant Indian news.
*   **Cons:** 
    *   Requires parsing raw XML utilizing Python's `xml.etree`.
    *   Like `yfinance`, it revolves around the "latest" news rather than exact historical windows.

---

## 3. Recommended Action Plan

We recommend completely refactoring `src/providers/news.py` to:
1.  **Drop Finnhub and NewsData completely.** Remove their environment variables.
2.  Implement a `YFinanceNewsProvider` as the Primary Provider (utilizing Option A).
3.  Implement a `GoogleNewsProvider` as the Fallback Provider (utilizing Option B alongside our new alias fuzzy matcher).

This completely ensures a robust, 100% free pipeline strictly tailored towards the NSE.
