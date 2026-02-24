"""Abstract base classes for data providers."""

import pandas as pd
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple

from src.models.datatypes import NewsArticle


class MarketDataProvider(ABC):
    """Abstract interface for fetching historical market and fundamental data."""

    @abstractmethod
    def fetch_ohlcv(self, stock: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Fetch OHLCV data for a given stock and date range.

        Args:
            stock (str): The ticker symbol.
            start_date (str): Start date in YYYY-MM-DD format.
            end_date (str): End date in YYYY-MM-DD format.

        Returns:
            pd.DataFrame: DataFrame containing Date, Open, High, Low, Close, Volume.
        """
        pass

    @abstractmethod
    def fetch_fundamentals(self, stock: str) -> Optional[float]:
        """
        Fetch the most recent YoY Net Income % change for a stock.

        Args:
            stock (str): The ticker symbol.

        Returns:
            Optional[float]: The YoY Net Income % change if available, else None.
        """
        pass


class NewsProvider(ABC):
    """Abstract interface for fetching company-specific news headlines."""

    @abstractmethod
    def fetch_news(self, stock: str, date: str, lookback_window_hours: int = 48) -> List[NewsArticle]:
        """
        Fetch news articles for a stock around a specific date.

        Args:
            stock (str): The ticker symbol.
            date (str): The target date in YYYY-MM-DD format.
            lookback_window_hours (int): How far back to look for headlines.

        Returns:
            List[NewsArticle]: A list of normalized NewsArticle objects.
        """
        pass


class SentimentProvider(ABC):
    """Abstract interface for classifying financial text sentiment."""

    @abstractmethod
    def analyze(self, text: str) -> Tuple[str, float]:
        """
        Analyze the sentiment of a given text.

        Args:
            text (str): The text to analyze.

        Returns:
            Tuple[str, float]: A tuple containing the categorical label 
                               (Positive/Neutral/Negative) and continuous score [-1.0, 1.0].
        """
        pass