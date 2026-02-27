"""Post-clone environment setup helper.

Run once after creating the conda env and installing requirements:

    conda create -n daksphere python=3.11
    conda activate daksphere
    pip install -r requirements.txt
    python setup_env.py

This script:
1. Detects and removes the broken yfinance-cache package (missing VERSION file).
2. Verifies all required imports resolve correctly.
3. Prints a clear summary of what passed / was fixed.
"""

import subprocess
import sys


def _pip(args: list[str]) -> int:
    return subprocess.call([sys.executable, "-m", "pip"] + args)


def check_and_fix_yfinance_cache() -> None:
    print("Checking yfinance-cache...")
    try:
        import yfinance_cache  # noqa: F401
        print("  [OK] yfinance-cache imports cleanly.")
    except FileNotFoundError:
        print(
            "  [WARN] yfinance-cache is installed but broken (missing VERSION file).\n"
            "         This is a known issue with the PyPI distribution on some platforms.\n"
            "         Removing it — the pipeline falls back to plain yfinance automatically."
        )
        _pip(["uninstall", "yfinance-cache", "-y"])
        print("  [FIXED] yfinance-cache uninstalled.")
    except ImportError:
        print("  [OK] yfinance-cache is not installed — will use plain yfinance (expected).")


def verify_imports() -> None:
    print("\nVerifying core imports...")
    required = [
        ("yfinance", "yfinance"),
        ("pandas", "pandas"),
        ("transformers", "transformers"),
        ("torch", "torch"),
        ("requests", "requests"),
        ("yaml", "PyYAML"),
        ("dotenv", "python-dotenv"),
        ("feedparser", "feedparser"),
        ("lxml", "lxml"),
    ]
    all_ok = True
    for mod, pkg in required:
        try:
            __import__(mod)
            print(f"  [OK] {pkg}")
        except ImportError:
            print(f"  [MISSING] {pkg}  →  run: pip install {pkg}")
            all_ok = False

    if not all_ok:
        print("\nSome packages are missing. Run:  pip install -r requirements.txt")
        sys.exit(1)


def verify_pipeline_imports() -> None:
    print("\nVerifying pipeline source imports...")
    try:
        from src.providers.market import YFinanceProvider  # noqa: F401
        from src.providers.news import GoogleNewsProvider  # noqa: F401
        from src.providers.sentiment import FinBERTProvider  # noqa: F401
        from src.pipeline.engine import PipelineEngine  # noqa: F401
        print("  [OK] All pipeline modules import cleanly.")
    except Exception as exc:
        print(f"  [ERROR] Pipeline import failed: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    print("=" * 60)
    print("  Daksphere — Environment Setup Check")
    print("=" * 60)
    check_and_fix_yfinance_cache()
    verify_imports()
    verify_pipeline_imports()
    print("\n" + "=" * 60)
    print("  Setup complete. You can now run: python run_pipeline.py")
    print("=" * 60)
