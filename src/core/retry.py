"""Retry logic wrapper with exponential backoff."""

import time
from functools import wraps
from typing import Any, Callable, TypeVar, cast

from src.core.logger import logger

F = TypeVar('F', bound=Callable[..., Any])

def with_retries(max_retries: int = 3, initial_delay: int = 2) -> Callable[[F], F]:
    """
    A decorator that retries a function upon failure using exponential backoff.

    Args:
        max_retries (int): Maximum number of retry attempts.
        initial_delay (int): Initial delay in seconds before the first retry. 
                             Subsequent delays double with each attempt.

    Returns:
        Callable: The decorated function.
    """
    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            delay = initial_delay
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries:
                        logger.error(f"'{func.__name__}' failed after {max_retries} retries: {e}")
                        raise
                    
                    logger.warning(
                        f"'{func.__name__}' failed (attempt {attempt + 1}/{max_retries}): {e}. "
                        f"Retrying in {delay} seconds..."
                    )
                    time.sleep(delay)
                    delay *= 2  # Exponential backoff
            
            return None # Should not be reached due to raise
        return cast(F, wrapper)
    return decorator