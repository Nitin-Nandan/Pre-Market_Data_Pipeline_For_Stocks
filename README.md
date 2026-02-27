# Pre-Market Sentiment Data Pipeline for NSE Stocks

A local, fully automated pipeline that fetches pre-market data for a configurable set of NSE stocks across a specified date range, enriches each row with a relevant news headline and financial sentiment score, and serialises the result to a validated CSV.

---

## Architecture Overview

```
config.yaml
    │
    ▼
PipelineEngine (src/pipeline/engine.py)
    ├── YFinanceProvider     → Pct_Change, Volume, YoY_NetIncome_%
    ├── fetch_headline()     → GoogleNewsProvider → NewsDataProvider → default
    │       ├── GoogleNewsProvider  (RSS, free, unlimited)
    │       └── NewsDataProvider    (API, 200 credits/day free tier)
    └── FinBERTProvider      → Sentiment_Label, Sentiment_Score [-1, 1]
    │
    ▼
output/pre_market_sentiment.csv
    │
    ▼
src/pipeline/validator.py   ← PRD success metric checks
```

**News pipeline detail — dual-query per provider:**
Each provider tries two queries per stock:
- Query A: `"<company name>"` — exact phrase, title relevance filter ON
- Query B: `"<TICKER>"` — ticker symbol, no title filter (ticker is self-selective)

Google News RSS is tried first (primary). NewsData.io is fallback. If both miss, a neutral default headline is assigned and `COVERAGE_GAP` is logged.

> **Constraint:** Historical date-specific news headlines are unavailable on free-tier APIs for NSE stocks. The pipeline fetches the latest available headline at execution time.

---

## Project Structure

```
Daksphere/
├── config.yaml                   # Stocks, date range, output dir, news window
├── run_pipeline.py               # Entry point
├── requirements.txt
├── src/
│   ├── core/
│   │   ├── cache.py              # SQLite key-value cache
│   │   ├── config.py             # YAML config loader
│   │   ├── logger.py             # Structured logger
│   │   ├── news_utils.py         # get_long_name, strip_suffix, _is_relevant_title
│   │   └── retry.py              # @with_retries decorator
│   ├── models/
│   │   └── datatypes.py          # NewsArticle, PipelineRow dataclasses
│   ├── pipeline/
│   │   ├── engine.py             # PipelineEngine — orchestrates all providers
│   │   └── validator.py          # PRD success metric validator
│   └── providers/
│       ├── base.py               # Abstract interfaces
│       ├── market.py             # YFinanceProvider (OHLCV + fundamentals)
│       ├── news.py               # GoogleNewsProvider, NewsDataProvider, fetch_headline
│       └── sentiment.py          # FinBERTProvider (ProsusAI/finbert, CPU)
├── scripts/
│   ├── dump_news_debug.py        # Debug: dual-query news inspection → JSON
│   └── verify_phase4.py          # End-to-end fetch_headline verification
└── output/
    ├── pre_market_sentiment.csv  # Pipeline output
    ├── stock_aliases.json        # yfinance longName cache
    ├── newsdata_debug.json       # NewsData query debug output
    └── google_debug.json         # Google RSS query debug output
```

---

## Setup

### 1. Create Conda environment

```bash
conda create -n daksphere python=3.11
conda activate daksphere
pip install -r requirements.txt
```

> Do not use `conda activate` inside scripts or automated runners — activate manually before running any command.

### 2. Configure API keys

Copy `.env.example` to `.env` and fill in your key:

```
NEWSDATA_API_KEY=your_key_here
```

Get a free key at [newsdata.io](https://newsdata.io). The free tier provides 200 credits/day. The pipeline caches responses per stock per day so multiple runs on the same day consume only one credit per stock.

### 3. Configure stocks and date range

Edit `config.yaml`:

```yaml
stocks:
  - BANKINDIA
  - HINDZINC
  - PFOCUS

date_range:
  start: "2026-02-16"
  end:   "2026-02-20"

output_dir: "output"

news:
  lookback_window_hours: 72
```

Stock symbols must be valid NSE tickers (without `.NS` suffix).

---

## Running the Pipeline

```bash
# From the project root with conda env active:
python run_pipeline.py
```

Expected output:
```
SUCCESS: 15 rows written to output/pre_market_sentiment.csv
```

### Validate output

```bash
python -m src.pipeline.validator output/pre_market_sentiment.csv
```

Expected:
```
PASS  row count = 15 (expected 15)
PASS  Sentiment_Score ∈ [-1.0, 1.0] for all rows
PASS  Pct_Change: 0 nulls
PASS  Volume: 0 nulls
PASS  YoY_NetIncome_Pct null rate = 0.0% (≤33%)

VALIDATION PASSED ✓
```

---

## Output Schema

| Column | Type | Description |
|---|---|---|
| `Date` | `YYYY-MM-DD` | Trading date |
| `Stock` | `str` | NSE ticker (no suffix) |
| `Pct_Change` | `float` | `(Close - PrevClose) / PrevClose × 100` |
| `Volume` | `int` | Daily traded volume |
| `Headline` | `str` | Most recent relevant news headline at execution time |
| `Sentiment_Label` | `str` | `Positive`, `Neutral`, or `Negative` |
| `Sentiment_Score` | `float` | Signed score in `[-1.0, 1.0]` |
| `YoY_NetIncome_Pct` | `float \| ""` | YoY net income % change (empty if unavailable) |
| `Data_Source_Log` | `str` | Pipe-delimited provenance: `market=yfinance \| news=google \| sentiment=finbert \| fundamentals=yfinance` |

---

## News Headline Logic

Headlines are fetched using a dual-query fallback chain:

1. **Google News RSS** (primary, free, unlimited)
   - Query A: `"<company name>" (NSE OR shares OR stock) when:3d` — title filter ON
   - Query B: `"<TICKER>" NSE when:3d` — no title filter
2. **NewsData.io** `/api/1/latest` (fallback, 200 credits/day)
   - Query A: `q="<company name>"` — title filter ON, 72hr window
   - Query B: `q="<TICKER>"` — no title filter, 72hr window
3. **Default** — `"No major headline available"` → `Neutral / 0.0`

Title relevance uses word-boundary regex with a preceding-character check to prevent embedded false positives (e.g. "State Bank of India" is correctly rejected when searching for "Bank of India").

Structured log reason codes: `COVERAGE_GAP` | `SOURCE_ISSUE` | `INFRA_FAILURE`

---

## Sentiment Model

**Model:** `ProsusAI/finbert` — BERT fine-tuned on financial news  
**Inference:** CPU-only (`device=-1`), no GPU required  
**Score mapping:**
- `positive` → `+score ∈ (0, 1]`
- `negative` → `-score ∈ [-1, 0)`
- `neutral`  → `0.0`

The model is lazy-loaded on first call and reused for the entire pipeline run. The default "No major headline available" placeholder is short-circuited to `Neutral / 0.0` without inference.

---

## Debug Tools

```bash
# Inspect dual-query news results per stock → output/newsdata_debug.json + google_debug.json
python scripts/dump_news_debug.py

# End-to-end fetch_headline verification with structured log output
python scripts/verify_phase4.py
```

---

## Constraints and Known Limitations

- **Free-tier API limits:** NewsData.io free tier = 200 credits/day. Cache prevents re-fetching on the same day.
- **Historical news:** Free-tier APIs do not support date-specific historical headline lookup. Headlines reflect the latest available at execution time.
- **NSE holidays:** The engine generates Mon–Fri dates; NSE-specific holidays are not excluded. Non-trading days produce no OHLCV row and are silently skipped.
- **YoY Net Income:** Quarterly financials may be unavailable for some stocks (small-caps). These cells are left empty — the validator allows ≤33% null rate.
- **CPU inference speed:** FinBERT on CPU takes ~0.5–2s per headline depending on hardware. For 15 rows this is negligible; for large-scale runs consider batching.