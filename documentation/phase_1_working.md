# Phase 1: Project Setup and Foundational Configuration - Detailed Working & Analysis

## Objective
The goal of Phase 1 was to establish the bedrock of the Pre-Market Sentiment Data Pipeline. Before writing any data extraction or transformation logic, we needed a robust environment that could handle configurations securely, log errors thoroughly, manage API rate limits through retries, and cache responses to avoid redundant network calls.

---

## 1. Core Configuration: `src/core/config.py`

**What it is:** A module responsible for loading static settings from `config.yaml` and sensitive secrets from `.env`.
**How we built it:** 
We used the `PyYAML` library heavily here. The `load_config()` function looks for `config.yaml` in the root directory. It parses the YAML structure into a standard Python dictionary. It is purposefully designed to throw explicit errors (`FileNotFoundError` or `ValueError`) if the file is missing or empty, acting as a strict gatekeeper before the pipeline attempts to run.
**Why we did it this way:** 
Hardcoding stock tickers or date ranges directly into Python scripts is an anti-pattern that destroys scalability. By isolating `stocks` and `date_range` into a YAML file, non-technical users can orchestrate the pipeline for 50+ stocks without altering a single line of Python code. We also load `.env` here using `python-dotenv` so that API keys (`FINNHUB_API_KEY`, etc.) remain securely out of source control.

---

## 2. Infrastructure: `src/core/logger.py`

**What it is:** A centralized logging configuration generator.
**How we built it:** 
We used Python's built-in `logging` module. `setup_logger()` creates a logger named "pipeline". Crucially, it attaches two "handlers": a `StreamHandler` to print to the terminal, and a `FileHandler` to write persistently to `output/pipeline.log`. It uses a verbose formatter: `%(asctime)s | %(levelname)-8s | %(module)s.%(funcName)s | %(message)s`.
**Why we did it this way:** 
Data pipelines fail. APIs timeout, tickers get delisted, and rate limits trigger. When running a batch of 50 stocks, an unhandled exception shouldn't crash silent. The timestamped file log ensures we satisfy the PRD's requirement for "Data Provenance Logging," giving us a meticulous trace of exactly which function processed which stock at what exact second.

---

## 3. Resilience: `src/core/retry.py`

**What it is:** A Python decorator that implements exponential backoff for network calls.
**How we built it:** 
Using `functools.wraps`, we wrote a closure `@with_retries(max_retries=3, initial_delay=2)`. When wrapped around a function, it catches any `Exception`. Instead of crashing, it logs a warning, calls `time.sleep()`, and then doubles the delay time (`delay *= 2`). It tries again up to the maximum limit before finally giving up and raising the error.
**Why we did it this way:** 
External APIs (like yfinance, Finnhub, or NewsData) are inherently flaky. A momentary network blip should not ruin a 50-stock batch run. Exponential backoff (waiting 2s, then 4s, then 8s) is the industry standard for politely bypassing temporary API rate limits (HTTP 429 errors) without overwhelming the provider's servers.

---

## 4. Performance: `src/core/cache.py`

**What it is:** A lightweight, localized SQLite database wrapper (`SQLiteCache`).
**How we built it:** 
We utilized Python's native `sqlite3` library. The script creates an invisible database file at `output/.cache.db`. It automatically provisions a table named `api_cache` with an explicit schema: `cache_key TEXT PRIMARY KEY`, `response_data TEXT`, and `created_at TIMESTAMP`. It provides `.get()` and `.set()` methods that serialize and deserialize Python dictionaries as stringified JSON.
**Why we did it this way:** 
Running NLP sentiment analysis across hundreds of news articles is slow. If the pipeline crashes midway, or if the user re-runs the script on the same day, we absolutely must not re-ping the APIs for data we already have. Caching saves API credits, aggressively speeds up local development, and prevents rate-limit bans.

---

## 5. Security and Tracking: `requirements.txt`, `.env`, and `config.yaml`

- **`requirements.txt`:** Locked down the exact toolchain (`pandas`, `yfinance`, `transformers`, `torch`, `flake8`, `mypy`, `lxml`) to ensure environment reproducibility.
- **`.env`:** A hidden file ignored by Git (via `.gitignore`) to store private API keys securely.
- **`config.yaml`:** 
```yaml
stocks:
  - PFOCUS
  - BANKINDIA
  - HINDZINC
date_range:
  start: "2026-02-16"
  end: "2026-02-20"
```

## Summary
Phase 1 established the "plumbing" of the architecture. It doesn't fetch any active market data itself, but ensures that when we do start fetching data, the environment handles it securely, repetitively, and observably.
