"""Provenance Guard — Flask server.

The `POST /submit` route validates input, runs both detection signals (Groq LLM
+ stylometrics), blends them into a confidence score, assigns a transparency
label, and records a structured audit entry. `POST /appeal` is stubbed for M5.
See planning.md.
"""

import os
import uuid

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from audit_log import add_entry, clear_logs, get_log, init_db, record_appeal
from scoring import combine_scores, score_to_attribution, score_to_label
from signals.groq_signal import get_groq_score
from signals.stylometric_signal import get_stylometric_score

load_dotenv()

# Reject submissions longer than this many characters (see "Edge Cases").
MAX_TEXT_LENGTH = 10_000


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

    # 3. Signal 2 — stylometric heuristics (pure Python, no external call).
    stylo_score = round(get_stylometric_score(text)["stylo_score"],2)

    # 4. Blend per planning.md: confidence = 0.6*groq + 0.4*stylo.
    confidence_score = combine_scores(groq_score, stylo_score)
    label = score_to_label(confidence_score)
    attribution = score_to_attribution(confidence_score)

    submission_id = str(uuid.uuid4())

    # 5. Persist a structured entry to the audit log on every submission.
    add_entry(
        content_id=submission_id,
        creator_id=creator_id,
        attribution=attribution,
        confidence=confidence_score,
        llm_score=groq_score,
        stylo_score=stylo_score,
        status="classified",
    )

    return jsonify(
        {
            "submission_id": submission_id,
            "creator_id": creator_id,
            "groq_score": groq_score,
            "groq_reason": groq_result["reason"],
            "stylo_score": stylo_score,
            "confidence_score": confidence_score,
            "attribution": attribution,
            "label": label,
            "status": "classified",
        }
    ), 200


@app.route("/appeal", methods=["POST"])
def appeal():
    """Appeal a prior classification.

    Input (JSON):  {"content_id": "<id>", "creator_reasoning": "<explanation>"}
    Updates the entry's status to "under_review", logs the appeal reasoning
    alongside the preserved original decision, and returns a confirmation. No
    automated re-classification is performed.
    """
    data = request.get_json(silent=True) or {}
    content_id = data.get("content_id")
    creator_reasoning = data.get("creator_reasoning")

    # Validate input.
    if not content_id or not isinstance(content_id, str):
        return jsonify({"error": "Field 'content_id' is required."}), 400
    if not creator_reasoning or not isinstance(creator_reasoning, str) or not creator_reasoning.strip():
        return jsonify({"error": "Field 'creator_reasoning' is required and must be non-empty."}), 400

    # Update status to "under_review" and log the appeal against the original entry.
    updated = record_appeal(content_id, creator_reasoning.strip())
    if updated is None:
        return jsonify({"error": f"No submission found with content_id '{content_id}'."}), 404

    return jsonify(
        {
            "content_id": content_id,
            "status": updated["status"],
            "appeal_reasoning": updated["appeal_reasoning"],
            "message": "Appeal successfully received and is now under review.",
        }
    ), 200


@app.route("/log", methods=["GET"])
def log():
    """Return the most recent audit log entries as JSON.

    For documentation and grading visibility. A real system would require auth.
    """
    return jsonify({"entries": get_log()}), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/clearlogs", methods=["DELETE"])
def clearlogs():
    return clear_logs()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="127.0.0.1", port=port, debug=True)
