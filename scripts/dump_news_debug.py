"""
Debug dump — runs full dual-query pipeline (Google + NewsData, name + ticker)
for all stocks and writes results to output/newsdata_debug.json and
output/google_debug.json, each showing Query A and Query B separately.

Also calls fetch_headline for the final orchestrated result.

Run with:
    $env:PYTHONPATH="."; python scripts/dump_news_debug.py
"""

import json
import os
import time
import urllib.parse
from datetime import datetime, timedelta

import feedparser
import requests
from dotenv import load_dotenv

load_dotenv()

from src.core.config import load_config
from src.core.news_utils import get_long_name, strip_suffix, _is_relevant_title

NEWSDATA_URL = "https://newsdata.io/api/1/latest"
GOOGLE_RSS_BASE = "https://news.google.com/rss/search"
PUBDATE_FMT = "%Y-%m-%d %H:%M:%S"
LOOKBACK_HOURS = 72


# ── raw fetch helpers ─────────────────────────────────────────────────────────

def _fetch_newsdata(api_key: str, q: str) -> list:
    """Call NewsData API with a given q parameter. Returns raw results list."""
    params = {
        "apikey": api_key, "q": q,
        "language": "en", "country": "in",
        "category": "business", "prioritydomain": "top",
        "removeduplicate": 1,
    }
    time.sleep(1)
    try:
        resp = requests.get(NEWSDATA_URL, params=params, timeout=15)
        if resp.status_code != 200:
            print(f"    [NewsData] HTTP {resp.status_code}")
            return []
        return resp.json().get("results", [])
    except Exception as e:
        print(f"    [NewsData] Exception: {e}")
        return []


def _fetch_google(query: str) -> list:
    """Fetch Google News RSS for a given query string. Returns entry list."""
    url = (f"{GOOGLE_RSS_BASE}?q={urllib.parse.quote(query)}"
           f"&hl=en-IN&gl=IN&ceid=IN:en")
    try:
        feed = feedparser.parse(url)
        entries = []
        for entry in feed.entries:
            title = getattr(entry, "title", "").strip()
            if not title:
                continue
            pub = getattr(entry, "published_parsed", None)
            pub_str = datetime(*pub[:6]).strftime(PUBDATE_FMT) if pub else ""
            src = getattr(entry, "source", {})
            source = src.get("title", "Google News") if isinstance(src, dict) else str(src)
            entries.append({
                "title": title, "source": source,
                "url": getattr(entry, "link", ""),
                "published_at": pub_str,
            })
        return entries
    except Exception as e:
        print(f"    [Google] Exception: {e}")
        return []


# ── annotation helpers ────────────────────────────────────────────────────────

def _annotate_nd(articles: list, long_name: str, ticker: str,
                 cutoff: datetime, use_title_filter: bool) -> list:
    """Annotate raw NewsData results with relevance + window flags."""
    annotated = []
    for a in articles:
        title = (a.get("title") or "").strip()
        if not title:
            continue
        pub_str = a.get("pubDate", "")
        try:
            pub_dt = datetime.strptime(pub_str, PUBDATE_FMT)
            in_window = pub_dt >= cutoff
        except ValueError:
            in_window = False
        relevant = (not use_title_filter) or _is_relevant_title(title, long_name, ticker)
        annotated.append({
            "title": title,
            "source": a.get("source_id") or a.get("source") or "",
            "published_at": pub_str,
            "url": a.get("link") or a.get("url") or "",
            "relevant_title": relevant,
            "in_72hr_window": in_window,
            "title_filter_applied": use_title_filter,
            "SELECTED": False,
        })
    return annotated


def _annotate_gn(articles: list, long_name: str, ticker: str,
                 cutoff: datetime, use_title_filter: bool) -> list:
    """Annotate raw Google RSS results with relevance + window flags."""
    annotated = []
    for a in articles:
        title = (a.get("title") or "").strip()
        if not title:
            continue
        pub_str = a.get("published_at", "")
        try:
            pub_dt = datetime.strptime(pub_str, PUBDATE_FMT)
            in_window = pub_dt >= cutoff
        except ValueError:
            in_window = False
        relevant = (not use_title_filter) or _is_relevant_title(title, long_name, ticker)
        annotated.append({
            "title": title,
            "source": a.get("source") or "Google News",
            "published_at": pub_str,
            "url": a.get("url") or "",
            "relevant_title": relevant,
            "in_72hr_window": in_window,
            "title_filter_applied": use_title_filter,
            "SELECTED": False,
        })
    return annotated


def _select(annotated: list) -> str:
    """Pick the most recent article that passed both filters."""
    candidates = [a for a in annotated if a["relevant_title"] and a["in_72hr_window"]]
    if not candidates:
        return "NONE"
    best = max(candidates, key=lambda a: a["published_at"])
    best["SELECTED"] = True
    return best["title"]


def _query_block(articles: list, selected: str) -> dict:
    return {
        "total_fetched": len(articles),
        "relevant_in_window": sum(
            1 for a in articles if a["relevant_title"] and a["in_72hr_window"]
        ),
        "selected_headline": selected,
        "articles": articles,
    }


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    config = load_config()
    stocks = config.get("stocks", [])
    output_dir = config.get("output_dir", "output")
    os.makedirs(output_dir, exist_ok=True)

    api_key = os.getenv("NEWSDATA_API_KEY")
    if not api_key:
        print("ERROR: NEWSDATA_API_KEY not set in .env")
        return

    cutoff = datetime.now() - timedelta(hours=LOOKBACK_HOURS)
    today = datetime.now().strftime("%Y-%m-%d")
    nd_out, gn_out = {}, {}

    for stock in stocks:
        long_name = get_long_name(stock)
        search_name = strip_suffix(long_name)
        print(f"\n{'─'*60}")
        print(f"Stock: {stock}  long_name={long_name!r}  search_name={search_name!r}")

        # ── NewsData — Query A (name, title filter ON) ─────────────────────
        q_nd_a = f'"{search_name}"'
        print(f"  [NewsData] Query A: q={q_nd_a} ...")
        nd_a_raw = _fetch_newsdata(api_key, q_nd_a)
        nd_a = _annotate_nd(nd_a_raw, long_name, stock, cutoff, use_title_filter=True)
        nd_a_sel = _select(nd_a)
        print(f"    fetched={len(nd_a)}  selected={nd_a_sel!r}")

        # ── NewsData — Query B (ticker, title filter OFF) ──────────────────
        q_nd_b = f'"{stock}"'
        print(f"  [NewsData] Query B: q={q_nd_b} ...")
        nd_b_raw = _fetch_newsdata(api_key, q_nd_b)
        nd_b = _annotate_nd(nd_b_raw, long_name, stock, cutoff, use_title_filter=False)
        nd_b_sel = _select(nd_b)
        print(f"    fetched={len(nd_b)}  selected={nd_b_sel!r}")

        nd_out[stock] = {
            "symbol": f"{stock}.NS", "long_name": long_name,
            "search_name": search_name, "cutoff": cutoff.strftime(PUBDATE_FMT),
            "query_a_name": _query_block(nd_a, nd_a_sel),
            "query_b_ticker": _query_block(nd_b, nd_b_sel),
            "pipeline_selected": nd_a_sel if nd_a_sel != "NONE" else nd_b_sel,
        }

        # ── Google — Query A (name, title filter ON) ───────────────────────
        q_gn_a = f'"{search_name}" (NSE OR shares OR stock) when:3d'
        print(f"  [Google] Query A: {q_gn_a!r} ...")
        gn_a_raw = _fetch_google(q_gn_a)
        gn_a = _annotate_gn(gn_a_raw, long_name, stock, cutoff, use_title_filter=True)
        gn_a_sel = _select(gn_a)
        print(f"    fetched={len(gn_a)}  selected={gn_a_sel!r}")

        # ── Google — Query B (ticker, title filter OFF) ────────────────────
        q_gn_b = f'"{stock}" NSE when:3d'
        print(f"  [Google] Query B: {q_gn_b!r} ...")
        gn_b_raw = _fetch_google(q_gn_b)
        gn_b = _annotate_gn(gn_b_raw, long_name, stock, cutoff, use_title_filter=False)
        gn_b_sel = _select(gn_b)
        print(f"    fetched={len(gn_b)}  selected={gn_b_sel!r}")

        gn_out[stock] = {
            "symbol": f"{stock}.NS", "long_name": long_name,
            "search_name": search_name, "cutoff": cutoff.strftime(PUBDATE_FMT),
            "query_a_name": _query_block(gn_a, gn_a_sel),
            "query_b_ticker": _query_block(gn_b, gn_b_sel),
            "pipeline_selected": gn_a_sel if gn_a_sel != "NONE" else gn_b_sel,
        }

    nd_path = os.path.join(output_dir, "newsdata_debug.json")
    gn_path = os.path.join(output_dir, "google_debug.json")

    with open(nd_path, "w", encoding="utf-8") as f:
        json.dump(nd_out, f, indent=2, ensure_ascii=False)
    with open(gn_path, "w", encoding="utf-8") as f:
        json.dump(gn_out, f, indent=2, ensure_ascii=False)

    print(f"\n{'═'*60}")
    print(f"Wrote {nd_path}  and  {gn_path}")
    print(f"{'═'*60}")
    print(f"\n{'Stock':12}  {'Google (primary)':50}  {'NewsData (fallback)'}")
    print("-" * 110)
    for stock in stocks:
        gn_sel = gn_out[stock]["pipeline_selected"]
        nd_sel = nd_out[stock]["pipeline_selected"]
        gn_disp = (gn_sel[:48] + "..") if len(gn_sel) > 50 else gn_sel
        nd_disp = (nd_sel[:48] + "..") if len(nd_sel) > 50 else nd_sel
        print(f"{stock:12}  {gn_disp:50}  {nd_disp}")


if __name__ == "__main__":
    main()
