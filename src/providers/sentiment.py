"""Local CPU financial sentiment inference using ProsusAI/finbert.

Pipeline:
    headline (str) → FinBERTProvider.analyze() → SentimentResult

Label mapping:
    finbert "positive" → "Positive" /  +score
    finbert "negative" → "Negative" /  -score
    finbert "neutral"  → "Neutral"  /   0.0

Score normalization:
    Raw logit-softmax score ∈ [0, 1] is mapped to [-1.0, 1.0]:
        Positive →  score
        Negative → -score
        Neutral  →  0.0

The default headline ("No major headline available") is short-circuited to
Neutral / 0.0 without running inference — avoids polluting the model with
structurally empty inputs.
"""

from dataclasses import dataclass

from src.core.logger import logger
from src.providers.base import SentimentProvider

_DEFAULT_HEADLINE = "No major headline available"
_MODEL_NAME = "ProsusAI/finbert"

# FinBERT raw label → canonical label
_LABEL_MAP = {
    "positive": "Positive",
    "negative": "Negative",
    "neutral": "Neutral",
}


@dataclass
class SentimentResult:
    """Output of a single sentiment inference call.

    Attributes:
        label: Canonical label — ``"Positive"``, ``"Neutral"``, or ``"Negative"``.
        score: Continuous score in ``[-1.0, 1.0]``.
            Positive headlines → ``(0.0, 1.0]``.
            Negative headlines → ``[-1.0, 0.0)``.
            Neutral  headlines → ``0.0``.
        raw_label: Original label string returned by the model.
        raw_score: Original softmax confidence returned by the model.
    """
    label: str
    score: float
    raw_label: str
    raw_score: float


class FinBERTProvider(SentimentProvider):
    """Local CPU financial sentiment using ``ProsusAI/finbert``.

    The underlying HuggingFace pipeline is loaded lazily on the first call to
    :meth:`analyze` so that importing this module has zero cost.

    Args:
        model_name: HuggingFace model identifier (default ``ProsusAI/finbert``).
    """

    def __init__(self, model_name: str = _MODEL_NAME) -> None:
        self.model_name = model_name
        self._pipeline = None  # lazy-loaded

    # ── public API ──────────────────────────────────────────────────────────

    def analyze(self, headline: str) -> SentimentResult:
        """Return sentiment label and score for a financial headline.

        Short-circuits to ``Neutral / 0.0`` for the default 'no headline'
        placeholder without running inference.

        Args:
            headline: Raw article headline string.

        Returns:
            :class:`SentimentResult` with ``label`` and ``score``.
        """
        headline = (headline or "").strip()

        if not headline or headline == _DEFAULT_HEADLINE:
            logger.debug("FinBERTProvider: default headline — returning Neutral/0.0")
            return SentimentResult(
                label="Neutral", score=0.0,
                raw_label="neutral", raw_score=0.0,
            )

        pipe = self._get_pipeline()
        try:
            raw = pipe(headline, truncation=True, max_length=512)
            # transformers 5.x with top_k unset returns list[list[dict]];
            # with top_k=1 it also returns list[list[dict]].
            # Normalise both: unwrap one level if needed.
            result = raw[0]
            if isinstance(result, list):
                result = result[0]   # list[list[dict]] → dict
        except Exception as exc:
            logger.error(f"FinBERTProvider: inference failed for {headline!r}: {exc}")
            return SentimentResult(
                label="Neutral", score=0.0,
                raw_label="error", raw_score=0.0,
            )

        raw_label: str = result["label"].lower()
        raw_score: float = float(result["score"])
        label = _LABEL_MAP.get(raw_label, "Neutral")
        score = _normalize(raw_label, raw_score)

        logger.info(
            f"FinBERTProvider: [{label} / {score:+.3f}] "
            f"(raw={raw_label}/{raw_score:.3f}) — {headline[:60]!r}"
        )
        return SentimentResult(
            label=label, score=score,
            raw_label=raw_label, raw_score=raw_score,
        )

    # ── internal ─────────────────────────────────────────────────────────────

    def _get_pipeline(self):
        """Lazy-load the HuggingFace pipeline on first call."""
        if self._pipeline is None:
            from transformers import pipeline as hf_pipeline
            logger.info(
                f"FinBERTProvider: loading model '{self.model_name}' on CPU "
                f"(first call only — subsequent calls reuse cached pipeline)"
            )
            self._pipeline = hf_pipeline(
                task="text-classification",
                model=self.model_name,
                device=-1,          # CPU-only — no GPU required
            )
            logger.info("FinBERTProvider: model loaded ✓")
        return self._pipeline


# ── helpers ───────────────────────────────────────────────────────────────────

def _normalize(raw_label: str, raw_score: float) -> float:
    """Map softmax confidence → signed score in [-1.0, 1.0].

    Args:
        raw_label: Lowercase label from model (``"positive"``/``"negative"``/``"neutral"``).
        raw_score: Softmax confidence ∈ ``[0, 1]``.

    Returns:
        float in ``[-1.0, 1.0]``.
    """
    if raw_label == "positive":
        return round(raw_score, 4)
    if raw_label == "negative":
        return round(-raw_score, 4)
    return 0.0
