"""Output validator — enforces PRD success metrics on pre_market_sentiment.csv.

Checks:
  1. Exactly 15 rows (3 stocks × 5 dates)
  2. Sentiment_Score within [-1.0, 1.0]
  3. Zero nulls in Pct_Change and Volume
  4. At most 33% nulls in YoY_NetIncome_Pct

Usage:
    python -m src.pipeline.validator output/pre_market_sentiment.csv
"""

import sys
import csv
from typing import List, Tuple


_REQUIRED_COLS = [
    "Date", "Stock", "Pct_Change", "Volume",
    "Headline", "Sentiment_Label", "Sentiment_Score",
    "YoY_NetIncome_Pct", "Data_Source_Log",
]


def validate(csv_path: str) -> Tuple[bool, List[str]]:
    """Run all validation checks against csv_path.

    Args:
        csv_path: Absolute or relative path to ``pre_market_sentiment.csv``.

    Returns:
        Tuple of ``(passed: bool, messages: list[str])``.
        ``messages`` contains PASS/FAIL lines for each check.
    """
    messages: List[str] = []
    passed = True

    # ── load ──────────────────────────────────────────────────────────────────
    try:
        with open(csv_path, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except FileNotFoundError:
        return False, [f"FAIL  file not found: {csv_path}"]
    except Exception as exc:
        return False, [f"FAIL  could not read CSV: {exc}"]

    # ── column presence ───────────────────────────────────────────────────────
    if not rows:
        return False, ["FAIL  CSV is empty"]
    missing = [c for c in _REQUIRED_COLS if c not in rows[0]]
    if missing:
        return False, [f"FAIL  missing columns: {missing}"]

    # ── check 1: row count ────────────────────────────────────────────────────
    n = len(rows)
    if n == 15:
        messages.append(f"PASS  row count = {n} (expected 15)")
    else:
        messages.append(f"FAIL  row count = {n} (expected 15)")
        passed = False

    # ── check 2: Sentiment_Score in [-1, 1] ───────────────────────────────────
    bad_scores = []
    for i, row in enumerate(rows, start=2):
        raw = row.get("Sentiment_Score", "")
        try:
            score = float(raw)
            if not (-1.0 <= score <= 1.0):
                bad_scores.append((i, score))
        except ValueError:
            bad_scores.append((i, raw))
    if not bad_scores:
        messages.append("PASS  Sentiment_Score ∈ [-1.0, 1.0] for all rows")
    else:
        messages.append(
            f"FAIL  Sentiment_Score out of range in "
            f"{len(bad_scores)} rows: {bad_scores[:3]}"
        )
        passed = False

    # ── check 3: 0% nulls in Pct_Change and Volume ───────────────────────────
    for col in ("Pct_Change", "Volume"):
        null_rows = [i + 2 for i, r in enumerate(rows) if not r.get(col, "").strip()]
        if not null_rows:
            messages.append(f"PASS  {col}: 0 nulls")
        else:
            messages.append(f"FAIL  {col}: {len(null_rows)} null(s) at rows {null_rows}")
            passed = False

    # ── check 4: ≤33% nulls in YoY_NetIncome_Pct ─────────────────────────────
    yoy_nulls = [i + 2 for i, r in enumerate(rows) if not r.get("YoY_NetIncome_Pct", "").strip()]
    yoy_pct = len(yoy_nulls) / n * 100 if n else 0
    if yoy_pct <= 33.0:
        messages.append(f"PASS  YoY_NetIncome_Pct null rate = {yoy_pct:.1f}% (≤33%)")
    else:
        messages.append(f"FAIL  YoY_NetIncome_Pct null rate = {yoy_pct:.1f}% (>33%)")
        passed = False

    return passed, messages


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python -m src.pipeline.validator <path_to_csv>")
        return 1
    csv_path = sys.argv[1]
    passed, messages = validate(csv_path)
    for msg in messages:
        print(msg)
    if passed:
        print("\nVALIDATION PASSED ✓")
        return 0
    else:
        print("\nVALIDATION FAILED ✗")
        return 1


if __name__ == "__main__":
    sys.exit(main())
