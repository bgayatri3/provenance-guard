"""Signal 2: Stylometric heuristics (pure Python, no external calls).

Computes measurable statistical properties that differ between human and AI
writing, normalizes each into an AI-likeness sub-score in [0, 1], and combines
them with fixed weights:

    stylo_score = 0.30 * sophistication   # avg word length + long-word ratio
                + 0.25 * uniformity        # 1 - coefficient of variation of sentence length
                + 0.15 * formality         # 1 - informal markers (lowercase starts, contractions)
                + 0.30 * ai_markers        # density of AI cliché / transition phrases

Direction convention: every normalized sub-score is AI-likeness, where 0.0 =
strongly human and 1.0 = strongly AI.

NOTE — revised from planning.md's original example metrics. Calibrating against
annotated examples showed the original set (sentence variance / type-token
ratio / punctuation density / complexity) failed: type-token ratio sat at
0.86–0.90 for *every* sample (contributing nothing despite 30% weight),
punctuation tracked casual commas rather than AI-ness, and nothing separated
clearly-AI text from casual-human text. The metrics below were chosen because
they empirically separate the four annotated cases; see planning.md ->
"Stylometric heuristics" for the rationale.
"""

import re
import statistics

# Combination weights (sum to 1.0).
W_SOPHISTICATION = 0.30
W_UNIFORMITY = 0.25
W_FORMALITY = 0.15
W_AI_MARKERS = 0.30

# Normalization anchors — the raw value at which a metric reads as fully human
# (-> 0) or fully AI (-> 1). Tuned against annotated examples, documented so they
# can be adjusted deliberately rather than drifting silently.
WORD_LEN_HUMAN = 4.2      # avg chars/word <= this => human
WORD_LEN_AI = 6.2         # avg chars/word >= this => AI
LONG_WORD_HUMAN = 0.15    # fraction of words >=7 chars: <= this => human
LONG_WORD_AI = 0.50       # >= this => AI
CV_AI = 0.25              # sentence-length coeff. of variation <= this => uniform => AI
CV_HUMAN = 0.65           # >= this => variable => human
AI_MARKERS_SATURATION = 3.0  # this many marker phrases => fully AI on that metric

# AI cliché / transition phrases. LLM prose leans on these far more than casual
# human writing; this is the single feature that separates polished-AI text from
# polished-human text. Curated heuristic, lowercased substring match.
AI_MARKERS = (
    "furthermore", "moreover", "however", "therefore", "additionally",
    "consequently", "it is important to note", "in conclusion", "in summary",
    "paradigm", "stakeholder", "leverage", "foster", "underscore", "crucial",
    "essential", "various", "numerous", "transformative", "fundamental",
    "represents a", "plays a vital role", "plays a crucial role", "navigate",
    "realm", "delve", "tapestry", "ever-evolving", "in today's",
)

_SENTENCE_SPLIT = re.compile(r"[.!?]+")
_WORD = re.compile(r"\b[\w']+\b")


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _norm_between(value: float, low: float, high: float) -> float:
    """Linearly map value in [low, high] to [0, 1] (clamped)."""
    return _clamp01((value - low) / (high - low))


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]


def get_stylometric_score(text: str) -> dict:
    """Score `text` for AI-likeness via stylometric heuristics.

    Returns:
        {
          "stylo_score": float in [0, 1],
          "metrics": { <raw and normalized sub-metrics, for inspection> }
        }
    """
    words = _WORD.findall(text)
    sentences = _split_sentences(text)
    sentence_word_counts = [len(_WORD.findall(s)) for s in sentences] or [len(words)]
    n_words = len(words) or 1
    n_sentences = len(sentences) or 1

    # --- 1. Lexical sophistication ---------------------------------------
    # AI prose favors longer, more formal words; casual human writing is short.
    avg_word_len = statistics.mean(len(w) for w in words) if words else 0.0
    long_word_ratio = sum(1 for w in words if len(w) >= 7) / n_words
    norm_sophistication = 0.5 * _norm_between(avg_word_len, WORD_LEN_HUMAN, WORD_LEN_AI) \
        + 0.5 * _norm_between(long_word_ratio, LONG_WORD_HUMAN, LONG_WORD_AI)

    # --- 2. Sentence-length uniformity -----------------------------------
    # AI keeps a steady cadence (low coefficient of variation); humans vary.
    # CV (stddev/mean) is scale-free, unlike raw stddev.
    mean_len = statistics.mean(sentence_word_counts)
    if len(sentence_word_counts) >= 2 and mean_len > 0:
        cv = statistics.pstdev(sentence_word_counts) / mean_len
    else:
        cv = 0.0  # single sentence => maximally uniform
    norm_uniformity = 1.0 - _norm_between(cv, CV_AI, CV_HUMAN)

    # --- 3. Formality / casing -------------------------------------------
    # Lowercase sentence starts and contractions signal casual human writing.
    starts_lower = sum(1 for s in sentences if s[:1].islower()) / n_sentences
    contraction_density = sum(1 for w in words if "'" in w) / n_sentences
    informality = _clamp01(starts_lower + 0.4 * min(contraction_density, 1.0))
    norm_formality = 1.0 - informality

    # --- 4. AI marker density --------------------------------------------
    lowered = text.lower()
    marker_hits = sum(1 for m in AI_MARKERS if m in lowered)
    norm_ai_markers = _clamp01(marker_hits / AI_MARKERS_SATURATION)

    stylo_score = (
        W_SOPHISTICATION * norm_sophistication
        + W_UNIFORMITY * norm_uniformity
        + W_FORMALITY * norm_formality
        + W_AI_MARKERS * norm_ai_markers
    )

    return {
        "stylo_score": _clamp01(stylo_score),
        "metrics": {
            "avg_word_len": round(avg_word_len, 3),
            "long_word_ratio": round(long_word_ratio, 3),
            "norm_sophistication": round(norm_sophistication, 3),
            "sentence_cv": round(cv, 3),
            "norm_uniformity": round(norm_uniformity, 3),
            "starts_lower": round(starts_lower, 3),
            "contraction_density": round(contraction_density, 3),
            "norm_formality": round(norm_formality, 3),
            "marker_hits": marker_hits,
            "norm_ai_markers": round(norm_ai_markers, 3),
        },
    }


if __name__ == "__main__":
    # `python -m signals.stylometric_signal` — the four annotated calibration cases.
    samples = {
        "edited-AI (mid)": (
            "I've been thinking a lot about remote work lately. There are genuine "
            "tradeoffs — flexibility and no commute on one side, isolation and "
            "blurred work-life boundaries on the other. Studies show productivity "
            "varies widely by individual and role type."
        ),
        "formal-human (mid-high)": (
            "The relationship between monetary policy and asset price inflation has "
            "been extensively studied in the literature. Central banks face a "
            "fundamental tension between their mandate for price stability and the "
            "unintended consequences of prolonged low interest rates on equity and "
            "real estate valuations."
        ),
        "clear-AI (high)": (
            "Artificial intelligence represents a transformative paradigm shift in "
            "modern society. It is important to note that while the benefits of AI "
            "are numerous, it is equally essential to consider the ethical "
            "implications. Furthermore, stakeholders across various sectors must "
            "collaborate to ensure responsible deployment."
        ),
        "clear-human (low)": (
            "ok so i finally tried that new ramen place downtown and honestly? "
            "underwhelming. the broth was fine but they put WAY too much sodium in "
            "it and i was thirsty for like three hours after. my friend got the "
            "spicy version and said it was better. probably won't go back unless "
            "someone drags me there"
        ),
    }
    for label, sample in samples.items():
        result = get_stylometric_score(sample)
        print(f"[{label}] stylo_score={result['stylo_score']:.3f}")
        for k, v in result["metrics"].items():
            print(f"    {k}: {v}")
