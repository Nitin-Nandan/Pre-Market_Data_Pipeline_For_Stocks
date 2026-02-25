"""Market data integration via yfinance and yfinance-cache."""

import pandas as pd
import yfinance as yf
try:
    import yfinance_cache as yfc
    HAS_YFC = True
except ImportError:
    HAS_YFC = False

from typing import Optional
from src.providers.base import MarketDataProvider
from src.core.logger import logger
from src.core.retry import with_retries


class YFinanceProvider(MarketDataProvider):
    """Yahoo Finance implementation for market and fundamental data."""

    def __init__(self) -> None:
        """Initialize the YFinance provider for NSE stocks."""
        self.suffix = ".NS"
        if not HAS_YFC:
            logger.warning("yfinance-cache is not imported/available. Falling back to base yfinance.")

    @with_retries(max_retries=3, initial_delay=2)
    def fetch_ohlcv(self, stock: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Fetch OHLCV data for a given stock and date range, computing % Change.
        Fetches an extended historical window to guarantee previous-close availability.

        Args:
            stock (str): The ticker symbol.
            start_date (str): Start date in YYYY-MM-DD format.
            end_date (str): End date in YYYY-MM-DD format.

        Returns:
            pd.DataFrame: DataFrame containing Date, Open, High, Low, Close, Volume, and Pct_Change.
        """
        symbol = f"{stock}{self.suffix}"
        logger.info(f"Fetching OHLCV for {symbol} from {start_date} to {end_date}")

        # yfinance `end` is exclusive, and we need a buffer before `start_date` to get the prev close
        start_dt = pd.to_datetime(start_date)
        buffer_start_dt = start_dt - pd.Timedelta(days=10)
        buffer_start = buffer_start_dt.strftime('%Y-%m-%d')

        end_dt = pd.to_datetime(end_date) + pd.Timedelta(days=1)
        end_date_exclusive = end_dt.strftime('%Y-%m-%d')

        ticker = yfc.Ticker(symbol) if HAS_YFC else yf.Ticker(symbol)
        
        hist = ticker.history(start=buffer_start, end=end_date_exclusive)

        if hist.empty:
            logger.warning(f"No OHLCV data returned for {symbol}")
            return pd.DataFrame()

        # Reset index to make Date a column
        hist = hist.reset_index()
        
        # In yfinance, Date is often timezone-aware. We remove the tz and format.
        if 'Date' in hist.columns:
            if pd.api.types.is_datetime64_any_dtype(hist['Date']):
                hist['Date'] = hist['Date'].dt.tz_localize(None).dt.strftime('%Y-%m-%d')
            else:
                hist['Date'] = pd.to_datetime(hist['Date']).dt.tz_localize(None).dt.strftime('%Y-%m-%d')

        # Ensure numeric types
        hist['Close'] = pd.to_numeric(hist['Close'], errors='coerce')
        hist['Volume'] = pd.to_numeric(hist['Volume'], errors='coerce').fillna(0).astype(int)

        # Compute % Change: (Close - Prev Close) / Prev Close * 100
        # pct_change() computes vs the immediately preceding row, which is correct for trading sessions
        hist['Pct_Change'] = hist['Close'].pct_change() * 100.0

        # Filter the DataFrame down to the originally requested date range
        mask = (hist['Date'] >= start_date) & (hist['Date'] <= end_date)
        filtered_hist = hist.loc[mask].copy()

        # Format Pct_Change to floats if desired, keep it numeric for the data pipeline layer
        return filtered_hist[['Date', 'Open', 'High', 'Low', 'Close', 'Volume', 'Pct_Change']]

    @with_retries(max_retries=3, initial_delay=2)
    def fetch_fundamentals(self, stock: str) -> Optional[float]:
        """
        Fetch the most recent YoY Net Income % change for a stock.
        """
        symbol = f"{stock}{self.suffix}"
        logger.info(f"Fetching fundamentals for {symbol}")
        
        try:
            ticker = yfc.Ticker(symbol) if HAS_YFC else yf.Ticker(symbol)
            qf = ticker.quarterly_financials
            
            if qf is None or qf.empty:
                logger.warning(f"No financials returned for {symbol}")
                return None
                
            # Attempt to locate 'Net Income' or 'Net Income Common Stockholders'
            target_row = None
            for row_name in ['Net Income', 'Net Income Common Stockholders']:
                if row_name in qf.index:
                    target_row = row_name
                    break
                    
            if not target_row:
                logger.warning(f"'{symbol}' financials lack 'Net Income' line items.")
                return None
                
            net_income = qf.loc[target_row].dropna().sort_index(ascending=False)
            
            if len(net_income) < 2:
                logger.warning(f"Not enough quarterly data points for {symbol}")
                return None
                
            current_q_date = net_income.index[0]
            current_q_val = net_income.iloc[0]
            
            prev_year_date = current_q_date - pd.DateOffset(years=1)
            time_diffs = abs(net_income.index - prev_year_date)
            min_diff = time_diffs.min()
            
            if min_diff <= pd.Timedelta(days=20):  # 20-day tolerance
                prev_q_val = net_income.loc[net_income.index[time_diffs.argmin()]]
            else:
                logger.warning(f"No matching previous year quarter found for {symbol}")
                return None
                
            if prev_q_val == 0:
                logger.warning(f"Previous year net income was exactly zero for {symbol} (div-by-zero risk)")
                return None
                
            yoy_pct = ((current_q_val - prev_q_val) / abs(prev_q_val)) * 100.0
            return round(float(yoy_pct), 2)
            
        except Exception as e:
            logger.error(f"Error fetching fundamentals for {symbol}: {e}")
            return None