"""Configuration module for loading project settings and environment variables."""

import os
from pathlib import Path
from typing import Any, Dict

import yaml
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

def load_config(config_path: str | Path = "config.yaml") -> Dict[str, Any]:
    """
    Load configuration from the specified YAML file.

    Args:
        config_path (str | Path): Path to the configuration file. Defaults to "config.yaml".

    Returns:
        Dict[str, Any]: A dictionary containing the configuration settings.
    """
    config_file = Path(config_path)
    if not config_file.exists():
        raise FileNotFoundError(f"Configuration file not found at {config_path}")

    with open(config_file, "r", encoding="utf-8") as file:
        config_data = yaml.safe_load(file)

    if not config_data:
        raise ValueError(f"Configuration file {config_path} is empty or invalid.")

    return config_data