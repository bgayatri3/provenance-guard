"""Signal 1: Groq LLM-based AI-likeness classification.

Sends the submitted text to a Groq-hosted LLM and asks it to judge whether the
writing reads as human- or AI-generated. Per the spec, the model returns:

    {
      "ai_score": <float between 0 and 1>,   # 0 = clearly human, 1 = clearly AI
      "reason":   "<one sentence>"
    }
"""

import json
import os

from groq import Groq

# A current general-purpose Groq model with JSON-mode support.
GROQ_MODEL = "llama-3.3-70b-versatile"

SYSTEM_PROMPT = (
    "You are an expert forensic linguist that detects AI-generated text. "
    "Assess whether the user's text reads as human-written or AI-generated, "
    "weighing semantic and stylistic coherence holistically. "
    "Respond ONLY with a JSON object of the form "
    '{"ai_score": <float 0-1>, "reason": "<one sentence>"}, '
    "where 0.0 means clearly human-written and 1.0 means clearly AI-generated."
)


def _clamp01(value: float) -> float:
    """Clamp a numeric value into the [0.0, 1.0] range."""
    return max(0.0, min(1.0, float(value)))


def get_groq_score(text: str, client: Groq | None = None) -> dict:
    """Score `text` for AI-likeness using the Groq LLM.

    Args:
        text: The user-submitted text to assess.
        client: Optional pre-built Groq client (useful for testing). When
            omitted, a client is created from the GROQ_API_KEY environment
            variable.

    Returns:
        A dict matching the spec's signal format:
            {"ai_score": float in [0, 1], "reason": str}

    Raises:
        ValueError: If GROQ_API_KEY is not set when no client is supplied.
    """
    if client is None:
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY is not set in the environment.")
        client = Groq(api_key=api_key)

    completion = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        response_format={"type": "json_object"},
        temperature=0.0,
    )

    raw = completion.choices[0].message.content
    parsed = json.loads(raw)

    return {
        "ai_score": _clamp01(parsed["ai_score"]),
        "reason": str(parsed.get("reason", "")).strip(),
    }


if __name__ == "__main__":
    # Quick manual smoke test: `python -m signals.groq_signal`
    # Verify scores move in the expected direction before wiring into /submit.
    from dotenv import load_dotenv

    load_dotenv()

    samples = {
        "likely AI": (
            "In today's rapidly evolving digital landscape, leveraging "
            "synergistic solutions is paramount to unlocking unprecedented "
            "value across all stakeholder verticals."
        ),
        "likely human": (
            "honestly i dunno, the bus was late again so i just walked. "
            "kinda annoyed but whatever, got coffee on the way at least lol"
        ),
    }

    for label, sample in samples.items():
        result = get_groq_score(sample)
        print(f"[{label}] -> {result}")
