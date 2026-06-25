"""Provenance Guard — Flask server.

Milestone M3 skeleton: the `POST /submit` route is wired up to validate input
and run Signal 1 (Groq LLM assessment). Signal 2 (stylometrics), confidence
scoring, the audit log (SQLite), and the `POST /appeal` endpoint are stubbed for
later milestones. See planning.md.
"""

import os
import uuid

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from audit_log import add_entry, get_log, init_db
from signals.groq_signal import get_groq_score

load_dotenv()

# Reject submissions longer than this many characters (see "Edge Cases").
MAX_TEXT_LENGTH = 10_000


def score_to_attribution(score: float) -> str:
    """Map an AI-likeness score in [0, 1] to a log attribution label.

    Uses the planning.md thresholds. In M3 the only available score is the
    Groq signal, so attribution is provisional; M4 will feed the blended
    confidence score here instead.
    """
    if score >= 0.70:
        return "likely_ai"
    if score >= 0.30:
        return "uncertain"
    return "likely_human"


app = Flask(__name__)
init_db()

# Rate limiting: per-client, 10 requests/minute on /submit (see spec).
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=[],
)


@app.route("/submit", methods=["POST"])
@limiter.limit("10 per minute")
def submit():
    """Accept a text submission, run the detection signals, and return a label.

    Input (JSON):  {"text": "<user text>", "creator_id": "<unique-id>"}
    Output (JSON): see planning.md -> "Endpoint 1: POST /submit -> Output".
    """
    data = request.get_json(silent=True) or {}
    text = data.get("text")
    creator_id = data.get("creator_id")

    # 1. Validate input.
    if not text or not isinstance(text, str) or not text.strip():
        return jsonify({"error": "Field 'text' is required and must be non-empty."}), 400
    if not creator_id or not isinstance(creator_id, str):
        return jsonify({"error": "Field 'creator_id' is required."}), 400
    if len(text) > MAX_TEXT_LENGTH:
        return (
            jsonify({"error": f"Text exceeds maximum length of {MAX_TEXT_LENGTH} characters."}),
            400,
        )

    # 2. Signal 1 — Groq LLM assessment.
    try:
        groq_result = get_groq_score(text)
    except Exception as exc:  # noqa: BLE001 — surface signal failures to the client.
        return jsonify({"error": f"Groq signal failed: {exc}"}), 502

    groq_score = groq_result["ai_score"]

    # TODO (M4): Signal 2 — stylometric heuristics -> stylo_score.
    # TODO (M4): confidence_score = 0.6 * groq_score + 0.4 * stylo_score.
    # In M3 the Groq signal is our only score, so it stands in as the interim
    # confidence and drives the provisional attribution.
    confidence_score = groq_score
    attribution = score_to_attribution(confidence_score)

    submission_id = str(uuid.uuid4())

    # Persist a structured entry to the audit log on every submission.
    add_entry(
        content_id=submission_id,
        creator_id=creator_id,
        attribution=attribution,
        confidence=confidence_score,
        llm_score=groq_score,
        status="classified",
    )

    return jsonify(
        {
            "submission_id": submission_id,
            "creator_id": creator_id,
            "groq_score": groq_score,
            "groq_reason": groq_result["reason"],
            "attribution": attribution,
            "confidence_score": confidence_score,
            # Populated in later milestones:
            "stylo_score": None,
            "label": None,
            "status": "classified",
        }
    ), 200


@app.route("/appeal", methods=["POST"])
def appeal():
    """Appeal a prior submission's label. Implemented in M5."""
    return jsonify({"error": "Not implemented yet."}), 501


@app.route("/log", methods=["GET"])
def log():
    """Return the most recent audit log entries as JSON.

    For documentation and grading visibility. A real system would require auth.
    """
    return jsonify({"entries": get_log()}), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="127.0.0.1", port=port, debug=True)
