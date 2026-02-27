"""Pre-market sentiment pipeline entry point.

Usage:
    python run_pipeline.py

Loads config.yaml, initialises all providers, runs PipelineEngine,
and reports success/failure to stdout and the pipeline log.
"""

import sys
import os
from dotenv import load_dotenv

load_dotenv()  # must precede src imports so env vars are available at module load

from src.core.config import load_config  # noqa: E402
from src.core.logger import logger  # noqa: E402
from src.pipeline.engine import PipelineEngine  # noqa: E402


def main() -> int:
    """Run the pipeline. Returns 0 on success, 1 on failure."""
    try:
        config = load_config()
    except (FileNotFoundError, ValueError) as exc:
        logger.error(f"run_pipeline: failed to load config: {exc}")
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    output_dir = config.get("output_dir", "output")

    try:
        engine = PipelineEngine(config=config, output_dir=output_dir)
        rows = engine.run()
    except Exception as exc:
        logger.error(f"run_pipeline: PipelineEngine raised: {exc}", exc_info=True)
        print(f"ERROR: pipeline failed — {exc}", file=sys.stderr)
        return 1

    csv_path = os.path.join(output_dir, "pre_market_sentiment.csv")
    print(f"SUCCESS: {len(rows)} rows written to {csv_path}")
    logger.info(f"run_pipeline: completed — {len(rows)} rows → {csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
