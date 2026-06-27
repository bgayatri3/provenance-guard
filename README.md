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
| Text | Attribution | Overall Confidence | Groq Confidence | Stylometric Confidence |
| --- | -- | -- | --- | --- |
| "ok so i finally tried that new ramen place downtown and honestly? underwhelming. the broth was fine but they put WAY too much sodium in it and i was thirsty for like three hours after. my friend got the spicy version and said it was better. probably won't go back unless someone drags me there" | likely_human | 0.132 | 0.2 | 0.03 |
| "The headphones have good sound quality for the price, especially if you're mostly listening to podcasts or casual music. Battery life has been consistent so far, although the touch controls occasionally register accidental taps. Overall, I'd probably recommend them if they're on sale" | uncertain | 0.324 | 0.2 | 0.51 |
| "Remote work has changed how many people approach productivity. Some employees appreciate the flexibility because it reduces commuting time and allows for a better work-life balance. Others find it harder to stay focused without a dedicated office space. In many cases, the effectiveness of remote work depends on the individual and the type of work being performed." | uncertain | 0.688 | 0.8 | 0.52 |
| "Artificial intelligence represents a transformative paradigm shift in modern society. It is important to note that while the benefits of AI are numerous, it is equally essential to consider the ethical implications. Furthermore, stakeholders across various sectors must collaborate to ensure responsible deployment." | likely_ai | 0.844 | 0.8 | 0.91 |


As shown in the examples above, scoring produces meaningful variation when text is more or less likely to be AI generated. The defined threshold and unique combination of the signal produce this intended result.

---
## Rate Limiting 
The `/submit` endpoint is protected using Flask-Limiter with a limit of 10 requests per minute per client. This limit was chosen because Provenance Guard is intended for interactive user; users can submit one piece of writing at a time for analysis. Ten requests per minute allows users to test multiple revisions without interruption. At the same time, automated spam, denial-of-service attempts, and excessive Groq API usage is discouraged.

---
## Audit Log
### Storage
Logs are stored in json in locally stored via SQLite. 

### Example of 3 Log Entries 
```
{
            "appeal_reasoning": null,
            "appealed_at": null,
            "attribution": "uncertain",
            "confidence": 0.6759999999999999,
            "content_id": "c8eb5ea8-c248-4a2c-9b61-92200d7786d8",
            "creator_id": "ratelimit-test",
            "llm_score": 0.8,
            "status": "classified",
            "stylo_score": 0.49,
            "timestamp": "2026-06-26T20:55:49.479Z"
        },
        {
            "appeal_reasoning": null,
            "appealed_at": null,
            "attribution": "uncertain",
            "confidence": 0.6759999999999999,
            "content_id": "934a6596-1c9b-4fc3-aad8-cb12c6debb79",
            "creator_id": "ratelimit-test",
            "llm_score": 0.8,
            "status": "classified",
            "stylo_score": 0.49,
            "timestamp": "2026-06-26T20:55:48.914Z"
        },
        {
            "appeal_reasoning": "I wrote this myself from personal experience. I am a non-native English speaker and my writing style may appear more formal than typical.",
            "appealed_at": "2026-06-26T20:52:24.672Z",
            "attribution": "uncertain",
            "confidence": 0.324,
            "content_id": "888fe81e-59f3-404d-9f63-375f98307fbc",
            "creator_id": "test-user-1",
            "llm_score": 0.2,
            "status": "under_review",
            "stylo_score": 0.51,
            "timestamp": "2026-06-25T23:53:32.039Z"
        }
}
```

---
## Limitations 
The stylometric heuristics are inherently less accurate than the Groq LLM classifier because they rely only on measurable writing characteristics (e.g., sentence length variance, vocabulary diversity, and punctuation) and cannot capture semantic meaning or context. To account for this, the final confidence score weights the Groq signal more heavily (60%) than the stylometric signal (40%). 

Additionally, stylometric analysis becomes less reliable for very short submission  because there is insufficient text to compute meaningful writing statistics. Often times these would be classified as uncertain. The current feature weights and confidence thresholds were selected heuristically rather than being calibrated on a large dataset. An improvment would be to evaluate the system on 100+ human-written, AI-generated, and mixed-authorship samples. This would allow the stylometric feature weights and overall confidence thresholds to be refined, improving accuracy and calibration across a wider range of writing styles.

---
## Spec Reflection 
### How the Spec Helped
The specification established the API contracts, processing pipeline, and expected behavior before implementation began. Defining the endpoints, confidence scoring, audit logging, and appeal workflow upfront made it easier to implement each component independently while ensuring they integrated correctly.

### Divergence 
Minor adjustments were made during development. For example, some manual refining the confidence score threshold was done. Also, I tried out some different stylometric heuristics to keep the system lightweight while still providing an independent detection signal since the original recommendation skewed confidence scores low. 

---
## AI usage
### AI Assistance Instance #1
Task: Generate an initial architecture diagram and API flow for the submission and appeal endpoints.

Output Used: ASCII diagrams illustrating the POST /submit and POST /appeal workflows.

Your Revisions: Updated the diagrams to match the final implementation, including the Groq classifier, stylometric heuristics, confidence scoring, transparency labels. 

### AI Assistance Instance #2
Task: Generate function to create logging SQLite 

Output Used: Python code generated for basic logging CRUD. 

Your Revisions: Modified some of the SQL statements to improve column naming, and added a delete logs for easier testing. 
