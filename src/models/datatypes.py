"""Data structures for the pre-market sentiment pipeline."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class NewsArticle:
    """
    Represents a normalized news article fetched from any news provider.
    """
    headline: str
    source: str
    url: str
    published_at: str  # ISO 8601 format timestamp or YYYY-MM-DD
    summary: Optional[str] = None


@dataclass
class PipelineRow:
    """
    Represents a single verified row of output data conforming to the PRD schema.
    """
    date: str
    stock: str
    pct_change: float
    volume: Optional[int]
    headline: str
    sentiment_label: str
    sentiment_score: float
    yoy_net_income_pct: Optional[float]
    data_source_log: str