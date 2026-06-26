# provenance-guard
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
## Multi-Signal Detection Pipeline
### 1. LLM-based classification (Groq)

The model to assesses whether text reads as human or AI-generated. Captures semantic and stylistic coherence holistically. This signal will produce a json in the following format. It may miss some lexical nuances captures in signal 2. 
```
{
  "ai_score": <float between 0 and 1>,
  "reason": "<one sentence>"
}
```
### 2. Stylometric heuristics

Analysis of measurable statistical properties that differ between human and AI writing. AI text tends to be more uniform and lexically sophisticated; casual human writing is more variable and informal. However, tone is not measured here. This is computable in pure Python. Each property is normalized to an AI-likeness sub-score in [0, 1] (0 = human, 1 = AI) and combined:
```
stylo_score = (
    0.30 * sophistication +   # avg word length + ratio of long (>=7 char) words
    0.25 * uniformity     +   # 1 - coefficient of variation of sentence length
    0.15 * formality      +   # 1 - informal markers (lowercase starts, contractions)
    0.30 * ai_markers         # density of AI cliché / transition phrases
)
```

### Final Score
These two signals are genuinely independent: one is semantic, one is structural. That makes the combination more informative than either alone. The Groq Signal and stylometric heuristic will produce individual confidence scores [0, 1] where 0 is purely human, and 1 is purely AI. They will be weighted as follows: 
 
> $ confidence=0.6×Groq +0.4×Stylometric  $ 

---
## Confidence Scoring System + Transparency Label Design
| Label | Confidence Score | Justification |
| ------| ---------------- | ------------- |
| high-confidence AI    | 0.70 – 1.00 | Both signals indicate the text is likely AI-generated. The combined score is sufficiently high to make a confident prediction while reducing false positives. |
| uncertain             | 0.30 – 0.69 | The signals disagree or neither provides strong evidence. Rather than overstate confidence, the system reports that the result is inconclusive. |
| high-confidence human | 0.00 – 0.29 | Both signals indicate the text is likely human-written. The low combined score reflects consistent evidence toward human authorship. |

---
## Example Scoring 
 <!-- include two example submissions with noticeably different confidence scores — one high-confidence and one lower-confidence case — showing the actual scores (you can lift these from your Milestone 4 testing). This is what shows your scoring produces meaningful variation, not a constant. -->
### Confident AI

### Confident Human

### Uncertain #1

### Uncertain #2

---
## Rate Limiting 
<!-- README documents the specific limits chosen and provides reasoning tied to realistic usage patterns on a writing platform — not just "I used the default." -->

---
## Audit Log
<!-- README documents the specific limits chosen and provides reasoning tied to realistic usage patterns on a writing platform — not just "I used the default." -->
### Storage
Logs are stored in json in locally stored via SQLite. 

### Example Log of 3 Log Entries 

---
## Limitations 
<!-- Known limitations section names at least one specific content type the system would likely misclassify, with explanation tied to the signals — not a generic disclaimer. -->

---
## Spec Reflection 
### How the Spec Helped

### Divergence 

---
## AI usage
### AI Assistance Instance #1
Task: Asked ChatGPT to review the label taxonomy and generate edge-case examples that sat between Review and Literary Analysis.

Output Used: Several generated examples were used to test whether the label definitions were sufficiently distinct before annotation began

Your Revisions: I refined the definitions by emphasizing the difference between evaluating a book (Review) and interpreting how a book creates meaning (Literary Analysis).

### AI Assistance Instance #2
Task: Asked ChatGPT to analyze model errors and identify common patterns in the misclassified examples.

Output Used: e AI identified recurring confusion between Question/Discussion and Review posts and suggested possible explanations for the pattern.

Your Revisions: I manually reviewed each incorrect prediction and verified the suggested patterns before incorporating them into the evaluation section. I also rejected the AI's initial assumption that Review and Literary Analysis would be the dominant source of confusion because the confusion matrix did not support that conclusion.