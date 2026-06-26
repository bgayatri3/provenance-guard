## General Overview of Provenance Guard
### Description
Provenance Guard takes the user's input and scores it as high-confidence AI, high confidence human, or uncertain. It accomplishes this goal through 2 primary endpoints: `POST /submit` and `POST /appeal` that run on a Flask server. 

The submission endpoint takes in the user's input (and creator_id) and runs it through 2 signals (Groq LLM assesment + Stylometrics heuristics) and assigns the text a confidence score along with one of the 3 transparency labels noed above. It also adds the request to the audit log, and displays to the user the confidence score and label via logging data. Rate limiting is implemented on this endpoint. 

The appeal endpoint takes in a prior content ID and the user-entered reasoning for the appeal. Then, the appeal is recorded alongside the original decision, and the content's status is changed to `under_review`. 

### Overall Flow 
```
                                Provenance Guard Architecture

                                      +----------------------+
                                      |    Postman Testing   |
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
                        +-------+--------+          | -> under_review      |
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
                 |      Audit Log       |<--------------->|        Postman       |
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

Analysis of measurable statistical properties that differ between human and AI writing. AI text tends to be more uniform and lexically sophisticated; casual human writing is more variable and informal. Computable in pure Python. Each property is normalized to an AI-likeness sub-score in [0, 1] (0 = human, 1 = AI) and combined:
```
stylo_score = (
    0.30 * sophistication +   # avg word length + ratio of long (>=7 char) words
    0.25 * uniformity     +   # 1 - coefficient of variation of sentence length
    0.15 * formality      +   # 1 - informal markers (lowercase starts, contractions)
    0.30 * ai_markers         # density of AI cliché / transition phrases
)
```
**Calibration note (M4).** The original example set (sentence-length variance, type-token ratio, punctuation density, sentence complexity) was tested against annotated examples and revised:
- **Type-token ratio** sat at 0.86–0.90 for *every* sample regardless of authorship — it is length-dependent and contributed nothing despite 30% weight. Replaced by **lexical sophistication** (word length), which cleanly separates casual human text from formal text.
- **Punctuation density** tracked casual commas rather than AI-ness (the casual-human sample was the most punctuated). Replaced by **AI marker density** — the density of AI-favored transition/cliché phrases ("furthermore", "it is important to note", "paradigm", "stakeholders", …), which is the single feature that separates polished-AI text from polished-human text.
- **Sentence variance** is kept but expressed as the scale-free **coefficient of variation** (stddev/mean) so it is comparable across submission lengths.

This is a documented, deliberate change to the example formula (the spec offered it as "an example format"), driven by data rather than left to silently diverge.

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
Allows any user who previously submitted text to appeal the assigned transparency label. The user provides the content ID (the `submission_id` returned by `/submit`) and a short explanation of why they believe the result is incorrect. The original decision is preserved, while the status is updated to `under_review`. No automated re-classification is performed — appeals are queued for a human reviewer.

### Input
```
{ 
    "content_id": "...", 
    "creator_reasoning": "<user explanation>" 
}
```
### Processing
1. Verify that the `content_id` exists (404 if not).
2. Record the appeal reasoning (stored as `appeal_reasoning`) and timestamp (`appealed_at`).
3. Update the entry's status to `under_review`.
4. Preserve the original confidence score, signal scores, and transparency label.
5. Update the audit log entry in place with the appeal information.

A human reviewer would see:

- Original submitted text
- Original confidence score
- Original transparency label
- Appeal reasoning
- Submission timestamp
- Current status (`under_review`)
### Output
```
{ 
    "content_id": "...", 
    "status": "under_review", 
    "appeal_reasoning": "<user explanation>",
    "message": "Appeal successfully received and is now under review." 
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
Here Clausa was provided with the detection signals section, the overview, and diagrams of how the submit endpoint works. It began with a flash app sketeton and a stubbed function. I tested periodically after the first signal using Postman. 

### M4 (second signal + confidence scoring)
<!-- Which spec sections you'll provide (detection signals + uncertainty representation + diagram), what you'll ask for (second signal function + scoring logic), and what you'll check (do scores vary meaningfully between clearly AI and clearly human text?). -->
After asking clauda to wire in the second signal and confidence scoring, I tested with 6 examples from human, ai, and uncertain. With claude's suggestions I tweaked the styloheuristic algorithm because it always skewed the score no matter which. This demonstrated that the normalization was not effective. 

### M5 (production layer)
<!-- Which spec sections you'll provide (label variants + appeals workflow + diagram), what you'll ask for (label generation logic + the /appeal endpoint), and h -->
For the prodution layer, the label variants, appear workflow, and rate limiting sections were provided for code generation. Verification was accomplished through postman requests and examination of the logs. 