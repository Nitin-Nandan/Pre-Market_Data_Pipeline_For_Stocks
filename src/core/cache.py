"""Local SQLite caching utility for API responses."""

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional

from src.core.logger import logger


class SQLiteCache:
    """A minimal SQLite-backed key-value cache for stringified JSON API responses."""

    def __init__(self, db_path: str = "output/.cache.db") -> None:
        """
        Initialize the SQLite cache.

        Args:
            db_path (str): Path to the SQLite database file.
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Get a connection to the SQLite database."""
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def _init_db(self) -> None:
        """Create the cache table if it doesn't exist."""
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS api_cache (
                    cache_key TEXT PRIMARY KEY,
                    response_data TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a cached response natively parsed as a dictionary.

        Args:
            key (str): The cache key.

        Returns:
            Optional[Dict[str, Any]]: The parsed JSON response if found, else None.
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "SELECT response_data FROM api_cache WHERE cache_key = ?", 
                    (key,)
                )
                row = cursor.fetchone()
                if row:
                    logger.info(f"Cache hit for key: {key}")
                    return json.loads(row[0])
        except sqlite3.Error as e:
            logger.error(f"SQLite error retrieving cache for key {key}: {e}")
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error for cached key {key}: {e}")
            
        logger.info(f"Cache miss for key: {key}")
        return None

    def set(self, key: str, value: Dict[str, Any]) -> None:
        """
        Store a dictionary response as a stringified JSON blob in the cache.

        Args:
            key (str): The cache key.
            value (Dict[str, Any]): The response dictionary to store.
        """
        try:
            value_str = json.dumps(value)
            with self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO api_cache (cache_key, response_data)
                    VALUES (?, ?)
                    """,
                    (key, value_str)
                )
        except (sqlite3.Error, TypeError) as e:
            logger.error(f"Error saving to cache for key {key}: {e}")