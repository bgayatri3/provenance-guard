"""Confidence scoring and transparency labels — single source of truth.

Combines the two signal scores and maps the result to a label. Both the
human-facing display label and the snake_case audit attribution derive from
ONE threshold function so they cannot diverge from planning.md.

Spec (planning.md):
    confidence = 0.6 * groq_score + 0.4 * stylo_score
    Label ranges:  AI 0.70–1.00 | Uncertain 0.30–0.69 | Human 0.00–0.29
Both scores and the confidence are AI-likeness: 0.0 = human, 1.0 = AI.
"""

# Final-score weights (must match planning.md).
GROQ_WEIGHT = 0.6
STYLO_WEIGHT = 0.4

# Label thresholds (inclusive lower bounds), per planning.md.
THRESHOLD_AI = 0.70        # >= 0.70           -> AI
THRESHOLD_UNCERTAIN = 0.30  # 0.30 .. < 0.70   -> Uncertain; < 0.30 -> Human

_DISPLAY_LABELS = {
    "ai": "High-confidence AI",
    "uncertain": "Uncertain",
    "human": "High-confidence Human",
}
_ATTRIBUTION_LABELS = {
    "ai": "likely_ai",
    "uncertain": "uncertain",
    "human": "likely_human",
}


def combine_scores(groq_score: float, stylo_score: float) -> float:
    """Weighted blend of the two signals: 0.6*groq + 0.4*stylo."""
    return GROQ_WEIGHT * groq_score + STYLO_WEIGHT * stylo_score


def classify(confidence: float) -> str:
    """Map a confidence score to a bucket key: 'ai' | 'uncertain' | 'human'."""
    if confidence >= THRESHOLD_AI:
        return "ai"
    if confidence >= THRESHOLD_UNCERTAIN:
        return "uncertain"
    return "human"


def score_to_label(confidence: float) -> str:
    """Human-facing transparency label (e.g. 'High-confidence AI')."""
    return _DISPLAY_LABELS[classify(confidence)]


def score_to_attribution(confidence: float) -> str:
    """Audit-log attribution (e.g. 'likely_ai')."""
    return _ATTRIBUTION_LABELS[classify(confidence)]
