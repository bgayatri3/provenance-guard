## General Overview of Provenance Guard
### Description
Provenance Guard takes the user's input and scores it as high-confidence AI, high confidence human, or uncertain. It accomplishes this goal through 2 primary endpoints: `POST /submit` and `POST /appeal` that run on a Flask server. 

The submission endpoint takes in the user's input (and creator_id) and runs it through 2 signals (Groq LLM assesment + Stylometrics heuristics) and assigns the text a confidence score along with one of the 3 transparency labels noed above. It also adds the request to the audit log, and displays to the user the confidence score and label via a Gradio UI. Rate limiting is implemented on this endpoint. 

The appeal endpoint takes in takes in a prior submission ID and the user entered reasoning for the appeal. Then, the appeal is updated alongside the original decision, and the content's status is changed to "under review". 

The UI allows the user to enter and analyzen new text via a text box and submit for review button. They can also scroll through prior submissions and their status (3 labels or under review). The audit logs is always synced with the UI. 

### Overall Flow 
```
                                Provenance Guard Architecture

                                      +----------------------+
                                      |      Gradio UI       |
                                      |----------------------|
                                      | • Enter text         |
                                      | • Submit for review  |
                                      | • View submissions   |
                                      | • Submit appeals     |
                                      +----------+-----------+
                                                 |
                        POST /submit             |             POST /appeal
          (raw text)                            |      (submission ID + reason)
                                                 |
                                                 v
                                  +------------------------------+
                                  |        Flask Server          |
                                  +------------------------------+
                                   |                          |
                                   |                          |
                    Submission Flow |                          | Appeal Flow
                                   |                          |
                                   v                          v
                        +----------------+          +----------------------+
                        | Groq LLM       |          | Update Submission    |
                        | Assessment     |          | Status               |
                        +-------+--------+          | -> Under Review      |
                                |                   +----------+-----------+
                                | signal score                 |
                                v                              |
                        +----------------+                     |
                        | Stylometric    |                     |
                        | Heuristics     |                     |
                        +-------+--------+                     |
                                | signal score                |
                                +-------------+---------------+
                                              |
                                              | combined scores
                                              v
                                  +--------------------------+
                                  | Confidence Scoring       |
                                  +------------+-------------+
                                               |
                                               | confidence score
                                               v
                                  +--------------------------+
                                  | Transparency Label       |
                                  | • High-confidence AI     |
                                  | • High-confidence Human  |
                                  | • Uncertain              |
                                  +------------+-------------+
                                               |
                          +--------------------+--------------------+
                          |                                         |
                          | audit entry                             | label + confidence
                          v                                         v
                 +----------------------+                 +----------------------+
                 |      Audit Log       |<--------------->|      Gradio UI       |
                 | • submissions        |      synced     | • Results            |
                 | • labels             |                 | • Submission history |
                 | • confidence         |                 | • Current status     |
                 | • appeals            |                 +----------------------+
                 | • review status      |
                 +----------------------+
```
---
## Chosen Detection Signals
###
1. **LLM-based classification (Groq)**

The model to assesses whether text reads as human or AI-generated. Captures semantic and stylistic coherence holistically. This signal will produce a json in the following format. 
```
{
  "ai_score": <float between 0 and 1>,
  "reason": "<one sentence>"
}
```
###
2. **Stylometric heuristics**

Analysize of measurable statistical properties that differ between human and AI writing — sentence length variance, type-token ratio (vocabulary diversity), punctuation density, or average sentence complexity. AI text tends to be more uniform; human writing is more variable. Computable in pure Python. The properties are normalized and combined into a single AI-likeness score between 0 and 1. An example format is given: 
```
style_score = (
    0.35 * normalized_sentence_variance +
    0.30 * normalized_ttr +
    0.20 * normalized_punctuation +
    0.15 * normalized_complexity
)
```

### Final Score
These two signals are genuinely independent: one is semantic, one is structural. That makes the combination more informative than either alone. The Groq Signal and stylometric heuristic will produce individual confidence scores [0, 1] where 0 is purely human, and 1 is purely AI. They will be weighted as follows: 
 
> $ confidence=0.6×Groq +0.4×Stylometric  $ 

---
## Confidence Scoring System + Transparency Label Design
 <!-- What does a confidence score of 0.6 mean to your system? How will you map raw signal outputs to a calibrated score? What threshold separates "likely AI" from "uncertain" from "likely human"? -->

| Label | Confidence Score | Justification |
| ------| ---------------- | ------------- |
| high-confidence AI    | 0.70 – 1.00 | Both signals indicate the text is likely AI-generated. The combined score is sufficiently high to make a confident prediction while reducing false positives. |
| uncertain             | 0.30 – 0.69 | The signals disagree or neither provides strong evidence. Rather than overstate confidence, the system reports that the result is inconclusive. |
| high-confidence human | 0.00 – 0.29 | Both signals indicate the text is likely human-written. The low combined score reflects consistent evidence toward human authorship. |


---
## Endpoint 1: `POST /submit`

Accepts a text submission from the user, analyzes it using two independent AI-detection signals, computes a combined confidence score, assigns a transparency label, records the result in the audit log, and returns the analysis to the UI.

### Input
```
{ 
    "text": "<user text>",
    "creator_id: "<unique-id>"
}
```
### Processing
1. Validate that the submitted text is non-empty and within the maximum length.
2. Send the text to the Groq LLM classifier to obtain an AI-likeness score (0–1).
3. Compute stylometric features (e.g., sentence length variance, type-token ratio, punctuation density, sentence complexity) and normalize them into a stylometric score (0–1).
    * Compute the final confidence score: 0.6 × Groq Score + 0.4 × Stylometric Score
4. Assign one of three transparency labels: High-confidence Human, Uncertain, High-confidence AI based on thresholds above
5. Create a unique submission ID.
6. Store the creator_id, submission, individual scores, overll score, label, timestamp, and status in the audit log via SQLite
### Output Example
```
{ 
    "submission_id": "...", 
    "creator_id": "...", 
    "confidence_score": 0.80, 
    "groq_score": 0.90,
    "stylo_score": 0.70,
    "label": "High-confidence AI", 
    "status": "Completed" 
}
```
### Rate Limiting 

The `/submit` endpoint is protected using **Flask-Limiter** to prevent abuse and excessive API usage. Requests are limited on a per-client basis (e.g., **10 requests per minute**). Clients that exceed the limit receive an HTTP **429 Too Many Requests** response and must wait until the rate limit resets before submitting additional requests.

This limit was chosen because the tool is interactive, and not intended for bulk analysis. Users are still able to test multiple submissions in quick succession while automated abuse is discouraged. 

---
## Endpoint 2: `POST /appeal`
Allows any user who previously submitted text to appeal the assigned transparency label. The user provides the submission ID and a short explanation of why they believe the result is incorrect. The original decision is preserved, while the submission status is updated to Under Review.

### Input
```
{ 
    "submission_id": "...", 
    "appeal_reason": "<user explanation>" 
}
```
### Processing
1. Verify that the submission ID exists.
2. Record the appeal reason and timestamp.
3. Update the submission status to Under Review.
4. Preserve the original confidence score and transparency label.
5. Update the audit log with the appeal information.

A human reviewer would see:

- Original submitted text
- Original confidence score
- Original transparency label
- Appeal reason
- Submission timestamp
- Current status ("Under Review")
### Output
```
{ 
    "submission_id": "...", 
    "status": "Under Review", 
    "message": "Appeal successfully submitted." 
}
```
---
## Anticipated Edge Cases
**1. Creative writing (poetry, song lyrics, or fiction)**

These works often use repetitive phrasing, unconventional punctuation, or intentionally simple vocabulary, which may cause the stylometric heuristics to incorrectly classify them as AI-generated.

**2. Very short submissions**

Inputs consisting of only one or two sentences provide too little information for reliable stylometric analysis, making the confidence score less dependable and more likely to fall into the "Uncertain" category.

**3. Human-edited AI text**

Content that was initially generated by AI but substantially rewritten by a person may retain some AI characteristics while exhibiting human writing patterns, causing the two detection signals to disagree.

**4. Highly polished professional writing.**

Academic papers, technical documentation, or carefully edited business writing often have consistent sentence structure and vocabulary, making them appear more AI-like than casual human writing.


---
## Architecture

### Overall Flow for `POST /submit`
```
+--------+                                          +---------+
| Client |                                          | Backend |
+--------+                                          +---------+
    |                                                   |
    | POST /submit                                      |
    | (raw text, creator_id)                            |
    +-------------------------------------------------->|
                                                        |
                                                        v
                                               +----------------+
                                               | Signal 1 Model |
                                               +----------------+
                                                        |
                                                        | signal 1 score
                                                        v
                                               +----------------+
                                               | Signal 2 Model |
                                               +----------------+
                                                        |
                                                        | signal 2 score
                                                        v
                                               +----------------------+
                                               | Confidence Scoring   |
                                               +----------------------+
                                                        |
                                                        | combined score
                                                        v
                                               +----------------------+
                                               | Transparency Label   |
                                               +----------------------+
                                                        |
                          +-----------------------------+----------------------------+
                          |                                                          |
                          | audit record                                             | label text +
                          | (raw text, scores, label)                                | confidence
                          v                                                          v
                   +----------------+                                        +---------------+
                   |   Audit Log    |                                        | HTTP Response |
                   +----------------+                                        +---------------+
```

### Overall Flow for `POST /appeal`
```
+--------+                                          +---------+
| Client |                                          | Backend |
+--------+                                          +---------+
    |                                                   |
    | POST /appeal                                      |
    | (submission ID, appeal reason)                    |
    +-------------------------------------------------->|
                                                        |
                                                        v
                                              +------------------+
                                              | Status Update    |
                                              +------------------+
                                                        |
                          +-----------------------------+---------------------------+
                          |                                                         |
                          | audit record                                            | updated status
                          | (ID, appeal, status)                                    |
                          v                                                         v
                   +----------------+                                       +---------------+
                   |   Audit Log    |                                       | HTTP Response |
                   +----------------+                                       +---------------+
```

---
## AI Tool Plan
### M3 (submission endpoint + first signal)
<!-- Which spec sections you'll provide to the AI tool (hint: your detection signals section + the diagram), what you'll ask it to generate (Flask app skeleton + the first signal function), and how you'll verify the output (test with a few inputs directly before wiring into the endpoint). -->

### M4 (second signal + confidence scoring)
<!-- Which spec sections you'll provide (detection signals + uncertainty representation + diagram), what you'll ask for (second signal function + scoring logic), and what you'll check (do scores vary meaningfully between clearly AI and clearly human text?). -->

### M5 (production layer)
<!-- Which spec sections you'll provide (label variants + appeals workflow + diagram), what you'll ask for (label generation logic + the /appeal endpoint), and h -->