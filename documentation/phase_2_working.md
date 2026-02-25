# Phase 2: Abstract Provider Interfaces and Data Models - Detailed Working & Analysis

## Objective
The goal of Phase 2 was to define the structural "blueprints" for the data pipeline. We needed to ensure that regardless of which specific API or AI model we use in the future, the data flowing through the pipeline is strictly typed, and the classes interacting with it are forced to implement standard, predictable methods.

---

## 1. Data Schemas: `src/models/datatypes.py`

**What it is:** Python dataclasses defining the specific shapes of data our pipeline accepts and outputs.
**How we built it:** 
We used the `@dataclass` decorator from Python's standard library. We defined two core un-mutable objects:
1. `NewsArticle`: A localized intermediate schema containing `headline`, `source`, `url`, `published_at`, and an optional `summary`.
2. `PipelineRow`: The final, master output schema directly reflecting the PRD requirements (`date`, `stock`, `pct_change`, `volume`, `headline`, `sentiment_label`, `sentiment_score`, `yoy_net_income_pct`, and `data_source_log`).

**Why we did it this way:** 
Dictionaries (`{}`) are prone to typos. If a developer accidentally types `{"percentage_change": 5}` instead of `{"pct_change": 5}`, a dictionary will silently pass it along until a catastrophic failure happens later. Dataclasses strictly enforce fields and types. By using `PipelineRow`, we guarantee that every single row appended to the final CSV matches the exact success criteria mandated by the TSD/PRD.

---

## 2. The Provider Pattern: `src/providers/base.py`

**What it is:** Abstract Base Classes (ABCs) that act as strict contracts for any data-fetching class.
**How we built it:** 
We imported `ABC` and `@abstractmethod` from the `abc` library. We defined three abstract interfaces:
1. `MarketDataProvider`: Requires the implementation of `fetch_ohlcv` and `fetch_fundamentals`.
2. `NewsProvider`: Requires the implementation of `fetch_news`.
3. `SentimentProvider`: Requires the implementation of `analyze`.

**Why we did it this way:** 
This is the core of the **Provider Pattern** architectural constraint mandated by the TSD. 
Assume we currently use `Finnhub` for news. If Finnhub goes bankrupt tomorrow, we don't want to rewrite the entire pipeline engine. Because we have `NewsProvider`, we simply write a new subclass (e.g., `BloombergProvider`) that implements `fetch_news`. The rest of the pipeline engine has zero knowledge of *how* the news is fetched; it only knows that *any* `NewsProvider` will return a list of `NewsArticle` dataclasses. This guarantees extreme modularity and scalability.

### Technical Note on `@abstractmethod`
By decorating `fetch_ohlcv` with `@abstractmethod`, Python physically prevents the pipeline from executing if a child class (like `YFinanceProvider`) forgets to write exactly that function. It is a compile-time safety check against incomplete code.

---

## 3. The Verification Execution

To verify Phase 2, we ran the following terminal command:
```bash
python -c "import inspect; from src.providers.base import MarketDataProvider; print(inspect.isabstract(MarketDataProvider))"
```

**Output Analysis:** The console returned `True`. 
**What this proved:** This validated that the `MarketDataProvider` object was not a standard class that could be instantiated on its own (which would be useless, as it contains no logic). It proved it was heavily abstracted using Python's metaclass system, successfully acting as a pure structural interface.

## Summary
Phase 2 created the strict programmatic rules of the pipeline. It defined what the data looks like (`datatypes.py`) and exactly how our modules are legally allowed to interact with the outside world (`base.py`). This guarantees that as the project grows to handle 50+ stocks across various APIs, the foundation remains predictable and error-resistant.
