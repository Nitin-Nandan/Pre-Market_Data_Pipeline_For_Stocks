"""Logging infrastructure setup."""

import logging
import os
from pathlib import Path


def setup_logger(name: str = "pipeline", log_file: str = "output/pipeline.log") -> logging.Logger:
    """
    Configure and return a standard logger that writes to a specified file and the console.

    Args:
        name (str): The name of the logger.
        log_file (str): The path to the log file.

    Returns:
        logging.Logger: The configured logger instance.
    """
    # Ensure the directory exists
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(name)
    
    # Avoid adding multiple handlers if setup is called multiple times
    if logger.hasHandlers():
        return logger

    logger.setLevel(logging.INFO)

    # Formatter includes timestamp, level, module, and message
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(module)s.%(funcName)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # File handler
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger

# Create a default logger instance
logger = setup_logger()