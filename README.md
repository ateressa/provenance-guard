# Provenance Guard

A backend system for attributing creative text content as human-authored or AI-generated. Any creative sharing platform could plug into it to classify submitted content, score confidence in that classification, surface a transparency label to users, and handle appeals from creators who believe they've been misclassified.

---

## Setup

```bash
git clone <repo-url>
cd provenance-guard
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add your GROQ_API_KEY
python app.py          # runs on http://localhost:5001
```

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/submit` | Submit text or code for attribution analysis |
| `POST` | `/appeal` | Contest a classification decision |
| `POST` | `/certify` | Request a Verified Human provenance certificate *(stretch)* |
| `GET`  | `/analytics` | Aggregated detection statistics *(stretch)* |
| `GET`  | `/log` | Retrieve audit log entries |

---

## Architecture Overview

The path a submission takes from input to transparency label:

```
POST /submit { text, creator_id }
        │
        ▼
  Rate Limiter
  10 req/min · 100 req/day per IP
  → 429 if exceeded
        │
        ▼
  ┌─────────────────────────────────┐
  │       Detection Pipeline        │
  │                                 │
  │  Signal 1: LLM-as-Judge        │
  │  Groq API → score 0.0–1.0      │
  │  weight: 60%                   │
  │                                 │
  │  Signal 2: Stylometric          │
  │  Pure Python → score 0.0–1.0   │
  │  weight: 40%                   │
  └──────────────┬──────────────────┘
                 │
                 ▼
        Confidence Scorer
        weighted average → single float
                 │
                 ▼
        Label Generator
        ≥ 0.75 → ai_generated
        ≤ 0.30 → human
        between → uncertain
                 │
                 ▼
        Audit Logger
        appends to logs/audit.jsonl
                 │
                 ▼
        HTTP Response
        { content_id, attribution, confidence, signals, label }
```

**Appeal flow:**

```
POST /appeal { content_id, creator_reasoning }
        │
        ▼
  Look up content_id in store
        │
        ▼
  Update status → "under_review"
        │
        ▼
  Append appeal record to audit log
  { event_type: "appeal", original_decision, creator_reasoning }
        │
        ▼
  HTTP Response { status: "under_review", original_attribution }
```

---

## Detection Signals

### Signal 1: LLM-as-Judge (60% weight)

**What it measures:** Whether the text exhibits semantic and stylistic patterns characteristic of large language model output — unnaturally consistent tone, absence of genuine hedging or self-contradiction, formulaic transitions, balanced paragraph structure that feels optimized rather than composed, and the specific brand of fluency that comes from training on text rather than living through experience.

**Why I chose it:** An LLM reading another LLM's output has context that pure statistics can't: it knows what polished-but-hollow feels like from the inside. It can catch things like every sentence being a complete, correct thought; every paragraph building to a tidy conclusion; every transition being smooth. Human writing doesn't do that — it hedges, contradicts itself, goes on tangents, and runs out of steam.

**What it returns:** A structured response with `label` (ai_generated or human), `score` (0.0–1.0 where 1.0 = certain AI), and `reasoning` (one sentence naming the most decisive signal). Temperature is set to 0 for deterministic output.

**What it misses:** A highly skilled human writer whose prose is clean and consistent will score similarly to AI output. Professional editors, academic writers, and anyone who revises heavily will look AI-like to this signal. It's also unreliable on short texts (under ~100 words) where there's not enough content to establish a stylistic pattern.

---

### Signal 2: Stylometric Heuristics (40% weight)

**What it measures:** Four statistical properties of the text computed in pure Python — no API call:

- **Sentence length variance:** Standard deviation of word counts per sentence. AI writing tends toward uniform rhythm; human writing swings between fragments and long complex sentences.
- **Type-token ratio (TTR):** Unique words divided by total words. Evaluated only on texts over 100 words (unreliable below that length). Uses a bounded range — TTR below 0.55 scores as human-like, above 0.85 scores as AI-like, with linear interpolation between.
- **Average word length:** AI writing in formal registers clusters around 5.2 characters per word. Human writing varies more widely — either shorter (casual) or longer (academic) than that center.
- **Punctuation density:** Punctuation marks per 100 words. Human creative writing uses punctuation idiosyncratically (em-dashes, ellipses, semicolons in lists). AI writing defaults to grammatically standard punctuation. Weight: 10% of the stylometric score (the least reliable sub-feature).

**Sub-feature weights within stylometric:** sentence variance 35%, TTR 35%, avg word length 20%, punctuation density 10%.

**Why I chose it:** Provides a second independent signal that doesn't require an API call and can't be manipulated the same way as the LLM signal. If someone specifically prompts an AI to "write like a human," the LLM signal may be fooled while the statistical properties remain AI-characteristic. The two signals catch different failure modes.

**What it misses:** Any writing style that is statistically atypical for human writing — minimalist poetry, writing by non-native English speakers, highly edited prose, and proper-noun-heavy lists (film titles, citations) all produce misleading signals. These are documented edge cases, not surprises.

---

## Confidence Scoring

**Combination formula:**
```
confidence = (llm_score × 0.60) + (stylometric_score × 0.40)
```

Signal 1 carries higher weight because semantic and stylistic coherence is harder to fake than surface statistics. An AI system specifically prompted to vary its sentence lengths will defeat Signal 2 before it defeats Signal 1.

**Thresholds (calibrated from empirical testing):**

| Confidence | Attribution |
|---|---|
| ≥ 0.75 | `ai_generated` |
| ≤ 0.30 | `human` |
| 0.31–0.74 | `uncertain` |

The original planning thresholds were 0.80/0.20. Empirical testing across 10+ submissions showed the combined score tops out around 0.78 for clearly AI text and bottoms around 0.27 for clearly human text, given the LLM's natural scoring range (0.2–0.9 for the test inputs). Thresholds were adjusted to 0.75/0.30 based on observed signal behavior rather than planning estimates. This is documented in `planning.md`.

**Validation — two example submissions with noticeably different confidence scores:**

**Example 1 — High-confidence AI (confidence: 0.78 → `ai_generated`)**

Submitted text (excerpt):
> "Artificial intelligence represents a transformative paradigm shift in modern society. It is important to note that while the benefits of AI are numerous, it is equally essential to consider the ethical implications that arise from its widespread adoption. Furthermore, stakeholders across various sectors must collaborate to ensure responsible deployment..."

```json
{
  "attribution": "ai_generated",
  "confidence": 0.78,
  "signals": {
    "llm_judge": { "score": 0.90, "reasoning": "Formulaic opening, consistent tone, absence of personal voice." },
    "stylometric": { "score": 0.57 }
  }
}
```

**Example 2 — High-confidence human (confidence: 0.29 → `human`)**

Submitted text:
> "1.The Revenant (2pt) I had some hype going into this movie, seeing eh potential when it was announced a long time ago... -Best Mumble: Tom Hardy -Showed Up Everywhere: Domnhall Gleeson"

```json
{
  "attribution": "human",
  "confidence": 0.29,
  "signals": {
    "llm_judge": { "score": 0.20, "reasoning": "Casual language, typos ('eh potential'), personal disclosures, and invented categories ('Best Mumble') suggest a human voice." },
    "stylometric": { "score": 0.42 }
  }
}
```

The gap between 0.29 and 0.78 — 49 confidence points — reflects what the system is designed to capture. A score of 0.51 produces an uncertain label with "51%" visible to the reader; a score of 0.95 would produce an AI label with the same format. The percentage is never hidden.

---

## Transparency Labels

Three variants. All three are returned as structured objects: `status` (machine-readable), `display_text` (human-readable, shown to readers on the platform), and `confidence_pct` (the numeric confidence expressed as a percentage).

**High-confidence AI (`confidence ≥ 0.75`):**

```
"This content was likely generated by an AI. Our system's confidence is [X]%.
AI-assisted or AI-generated content may not reflect the lived experience or
original voice of the attributed creator. If you are the creator and believe
this classification is wrong, you may submit an appeal using your content ID."
```

**High-confidence Human (`confidence ≤ 0.30`):**

```
"This content appears to be human-authored. Our system's confidence is [X]%.
Our analysis found stylistic and semantic patterns consistent with human writing.
No further review is required — this label may be updated if an appeal is filed."
```

**Uncertain (`confidence 0.31–0.74`):**

```
"Attribution uncertain. Our system's confidence is [X]%.
Our analysis could not determine with confidence whether this content is
human-authored or AI-generated. The result should be treated as inconclusive.
If you are the creator, you may submit an appeal with supporting context."
```

In each label, `[X]%` is replaced at runtime with the actual confidence percentage. The number is always visible — readers can see whether a result is 51% or 95%, and those mean different things.

---

## Rate Limiting

**Limits:** 10 requests per minute, 100 requests per day, per IP address.

**Reasoning:**

The per-minute limit reflects the upper bound of realistic human usage. A writer reviewing their own work might submit 3–5 pieces in a session. 10 per minute gives that room without friction. At the same time, any script flooding the system would need 600 requests per hour to stay under the per-minute limit — the 100/day cap stops overnight automation cold.

The per-day limit of 100 is high enough that a platform's moderation team could manually review a batch of flagged submissions, but low enough that a single IP running bulk analysis would hit it before doing real damage to Groq API costs.

**Rate limit test output** (12 rapid requests to a fresh window):

```
200
200
200
200
200
200
200
200
200
200
429
429
```

10 × `200`, then 2 × `429`. Flask-Limiter returns the standard 429 response automatically. No custom error handling needed.

---

## Audit Log

Every attribution decision and appeal is appended to `logs/audit.jsonl`. The format is one JSON object per line. Sample entries:

**Classification event:**
```json
{
  "event_type": "classification",
  "timestamp": "2026-06-27T22:28:11Z",
  "content_id": "dc3ad871",
  "creator_id": "label-test",
  "attribution": "ai_generated",
  "confidence": 0.7832,
  "llm_score": 0.9,
  "stylometric_score": 0.6081,
  "text_too_short": false,
  "status": "classified"
}
```

**Appeal event:**
```json
{
  "event_type": "appeal",
  "timestamp": "2026-06-27T22:28:50Z",
  "content_id": "3902b6df",
  "status": "under_review",
  "original_attribution": "uncertain",
  "original_confidence": 0.6839,
  "creator_reasoning": "I wrote this myself from personal experience. I am a non-native English speaker and my writing style may appear more formal than typical."
}
```

**Human-authored classification:**
```json
{
  "event_type": "classification",
  "timestamp": "2026-06-27T22:28:22Z",
  "content_id": "2ccf540f",
  "creator_id": "label-test",
  "attribution": "human",
  "confidence": 0.2891,
  "llm_score": 0.2,
  "stylometric_score": 0.4228,
  "text_too_short": false,
  "status": "classified"
}
```

Use `GET /log?limit=N` to retrieve the most recent N entries as JSON. The `event_type` field (`classification` vs `appeal`) makes it straightforward to filter the queue by event type.

---

## Appeals Workflow

Creators who believe they've been misclassified submit `POST /appeal` with their `content_id` and a written explanation. The system:

1. Looks up the original decision by `content_id`
2. Updates the content's status to `"under_review"` in the in-memory store
3. Appends an appeal record to the audit log — including the original attribution, confidence, and the creator's reasoning
4. Returns a confirmation with the original decision visible

No automated re-classification occurs. A human reviewer querying `GET /log` and filtering for `event_type: "appeal"` sees the original confidence, both raw signal scores, and the creator's explanation side-by-side — enough context to make an informed override decision.

**Example appeal request:**
```bash
curl -X POST http://localhost:5001/appeal \
  -H "Content-Type: application/json" \
  -d '{
    "content_id": "3902b6df",
    "creator_reasoning": "I wrote this myself. I am a non-native English speaker and my formal register is a product of language learning, not AI generation."
  }'
```

**Example response:**
```json
{
  "content_id": "3902b6df",
  "status": "under_review",
  "original_attribution": "uncertain",
  "original_confidence": 0.6839,
  "message": "Your appeal has been received and flagged for human review. No automated re-classification will occur."
}
```

---

---

## Stretch Features

### Ensemble Detection (Signal 3: Human Voice Markers)

A third independent signal measures features that AI writing suppresses in formal/analytical contexts: **contraction density**, **first-person pronoun density**, and **informal marker density** (colloquialisms, hedges, filler words).

**Why this signal adds value:** The LLM and stylometric signals both tend to score analytical human writing as ambiguous. Casual human writing with "honestly?", "I'd", "won't go back" scores clearly human on this signal even when sentence length variance is low. The lexical signal catches the AI-vs-human gap in register that the other two signals miss for informal content.

**Weighting (3-signal ensemble):**

| Signal | Weight | Rationale |
|---|---|---|
| LLM-as-judge | 60% | Captures semantic/stylistic coherence — hardest to fake |
| Stylometric | 30% | Surface statistical properties — faster but gameable |
| Lexical (human voice) | 10% | Strong for casual content; neutral for formal — used as correction |

**Example showing Signal 3 contribution:**

Human casual text (ramen review): LLM=0.20, Stylo=0.42, **Lexical=0.40** → confidence=0.287 → `human`
AI formal text: LLM=0.90, Stylo=0.57, **Lexical=0.95** → confidence=0.806 → `ai_generated`

The lexical signal is near-neutral (0.40) for the casual human text because it has some contractions and first-person pronouns. It scores near-maximum (0.95) for the AI text because it has zero contractions, zero first-person, and zero informal markers.

---

### Provenance Certificate

Creators can earn a **Verified Human** credential by submitting a written statement about their creative process through `POST /certify`. The system runs the statement through the full detection pipeline. If the statement itself scores as human (confidence ≤ 0.45), a certificate is issued and attached to the content record.

**Why a statement, not just a checkbox:** The verification step has to be something a script can't trivially pass. A human explaining their creative process in natural language produces different stylistic signals than a short auto-generated confirmation.

**Certificate request:**
```bash
curl -X POST http://localhost:5001/certify \
  -H "Content-Type: application/json" \
  -d '{
    "content_id": "bd3e7be4",
    "creator_statement": "I wrote this after a genuinely disappointing ramen experience last Tuesday. I remember being so thirsty afterward — that detail is something I would not have made up..."
  }'
```

**Certificate response:**
```json
{
  "content_id": "bd3e7be4",
  "status": "verified_human",
  "certificate": {
    "certificate_id": "cert-b3dd9c18",
    "display_text": "Verified Human — This content has been verified as human-authored through Provenance Guard's creator verification process. The creator provided a written statement that scored 71% human confidence.",
    "issued_at": "2026-06-27T22:56:19Z",
    "statement_confidence": 0.2931
  }
}
```

Certificates are attached to the content record in the store and logged in the audit log with `event_type: "certificate_issued"`. Content already classified as `ai_generated` is ineligible — the creator must file an appeal first.

---

### Analytics Dashboard

`GET /analytics` aggregates all audit log entries and returns detection statistics:

```json
{
  "total_submissions": 57,
  "attribution_breakdown": {
    "ai_generated": { "count": 7, "pct": 12.3 },
    "human":        { "count": 7, "pct": 12.3 },
    "uncertain":    { "count": 43, "pct": 75.4 }
  },
  "avg_confidence_by_attribution": {
    "ai_generated": 0.7881,
    "human": 0.2864,
    "uncertain": 0.4776
  },
  "appeal_rate": 0.035,
  "appeals_filed": 2,
  "certificates_issued": 1,
  "content_type_breakdown": { "text": 55, "code": 2 }
}
```

The `avg_confidence_by_attribution` field is the additional metric: it shows whether the system is making calibrated claims. A well-calibrated system should show `human` confidence clearly below 0.30, `ai_generated` clearly above 0.75, and `uncertain` between them. The numbers above (0.29 / 0.48 / 0.79) confirm this.

---

### Multi-Modal Support (Text + Code)

The submission endpoint accepts an optional `content_type` field (`"text"` or `"code"`, default `"text"`). Code submissions use a code-specific detection pipeline:

**Code Signal 1 (LLM):** A code-specific prompt looks for AI code patterns: comprehensive docstrings on every function, explanatory comments describing what each line does (rather than why), perfect naming convention consistency, and absence of debugging residue (TODO/FIXME/HACK comments, commented-out experiments).

**Code Signal 2 (structural):** Pure Python metrics — comment density (AI code is heavily commented), line length variance (AI code is uniform), docstring coverage per function (AI = near 100%), and debug marker presence (human code has TODO/FIXME; AI code is clean).

**Example — human-written code (messy, pragmatic):**
```bash
curl -X POST http://localhost:5001/submit \
  -H "Content-Type: application/json" \
  -d '{"content_type": "code", "creator_id": "dev", "text": "def get_user(id):\n    # TODO: add caching\n    u = db.query(...)\n    # FIXME: sometimes stale\n    return u[0]"}'
```
Result: `confidence=0.31, attribution=uncertain` — LLM scores 0.20 (correctly recognizes human patterns), structural scores 0.47.

**Example — AI-generated code (polished, complete):**
Docstrings on every function, full type annotations, comprehensive error handling, zero TODOs.
Result: `confidence=0.71, attribution=uncertain` — LLM scores 0.90, structural scores 0.40.

---

## Known Limitations

**Proper-noun-heavy creative writing (lists, criticism with citations)** will have an artificially high type-token ratio because every film title, director name, and proper noun is a unique token. The stylometric signal's TTR sub-feature interprets high vocabulary diversity as AI-characteristic, even when it's driven by content rather than AI generation. A year-end film ranking with 40 director names in the "honorable mentions" section will score misleadingly AI-like on TTR.

This was discovered during testing (the Blackhat/Blackhat film criticism text) and partially mitigated by switching TTR normalization from a floor-at-zero formula to a bounded range (0.55 human anchor, 0.85 AI anchor). That fix reduced the impact but didn't eliminate it. TTR remains the weakest sub-feature and is given the lowest weight within the stylometric signal.

**Writing by non-native English speakers** is the highest-risk false positive scenario in the system. Short, syntactically simple sentences, limited punctuation, and careful vocabulary control are all surface features the stylometric signal reads as AI-characteristic — because they overlap with how AI generates "safe," grammatically correct output. The LLM signal provides some correction (it can recognize the register of a careful second-language writer), but not reliably.

If deployed for real, both of these cases would require a more sophisticated TTR calculation (adjusted for text length and proper-noun density) and a domain-specific training set for the stylometric thresholds — rather than the manually-estimated constants used here.

---

## Spec Reflection

**One way the spec helped:** Writing out the false positive scenario in `planning.md` before building anything forced a decision that shaped the entire system: make the uncertain band wide. The spec asked me to trace a misclassified human poet through the system — what does the label say, what can they do? That exercise made it clear that a system that is too eager to assign high-confidence labels will harm real creators. The 0.31–0.74 uncertain band and the wide gap between thresholds came directly from writing that scenario out. Without the spec, I would have set tighter thresholds and created more false positives.

**One way implementation diverged:** The planning document specified confidence thresholds of 0.80 (AI) and 0.20 (human), and a TTR normalization of `score = min(1.0, ttr / 0.85)`. Both changed substantially after testing. The thresholds moved to 0.75/0.30 because empirical scoring showed the combined signal tops out around 0.78 for clearly AI text — the original thresholds were unreachable. The TTR formula changed from floor-at-zero to a bounded range (0.55–0.85) after the Blackhat film criticism test showed that proper-noun-heavy human writing was scoring as strongly AI-like. Both changes were driven by observing real signal behavior, not by changing the design goals. The spec described what I wanted the system to do; testing revealed what the signals actually do; calibration bridged the gap.

---

## AI Usage

**Instance 1: Flask skeleton and classifier function**

I directed the AI to generate a Flask app skeleton with a `POST /submit` stub and a first-pass LLM classifier function, giving it my detection signals section and architecture diagram from `planning.md` as context.

What it produced was structurally correct — the route was wired, the Groq call was made, the response was returned. What I revised: the LLM prompt in the generated classifier was vague ("evaluate whether this text was written by a human or AI"). I rewrote the entire system message from scratch, adding specific behavioral signals to look for (absent hedging, formulaic openings, balanced paragraph structure), a structured three-line output format (`Label:` / `Score:` / `Reasoning:`), and `temperature=0` for deterministic output. The AI gave me the scaffolding; the prompt that drives the signal quality was written by hand.

**Instance 2: Stylometric heuristics and confidence scoring**

I directed the AI to generate the stylometric heuristics function and the confidence scorer, giving it my planning.md spec for each sub-feature (sentence variance, TTR, average word length, punctuation density) and the 60/40 weighting formula.

The generated code was structurally correct and matched the spec. What I caught and overrode: the TTR normalization formula was `score = min(1.0, ttr / 0.85)` — a floor-at-zero formula that treats any TTR, however human-typical, as proportionally AI-leaning. This didn't show up as wrong until I tested with the Blackhat film criticism text (543 words, TTR = 0.72 due to proper nouns), which scored 0.85 AI-leaning on TTR despite being unmistakably human writing. I replaced the formula with a bounded range `(ttr - 0.55) / (0.85 - 0.55)` so that typical human TTR (0.55–0.72) maps to the lower half of the scale rather than the upper half. The generated formula was technically faithful to the spec as written; the spec was wrong, and testing revealed it.

---

## File Structure

```
provenance-guard/
├── app.py              ← Flask routes, rate limiter, label generation, all endpoints
├── classifier.py       ← Signal 1: LLM-as-judge via Groq (text)
├── code_analyzer.py    ← Signal 1+2 for code content type [stretch]
├── stylometrics.py     ← Signal 2: sentence variance, TTR, word length, punctuation
├── lexical.py          ← Signal 3: contraction density, first-person, informal markers [stretch]
├── scorer.py           ← 3-signal weighted ensemble + attribution thresholds
├── auditor.py          ← Append-only audit log (classifications, appeals, certificates)
├── store.py            ← In-memory content store (content_id → record)
├── config.py           ← All constants: thresholds, weights, limits, model, cert settings
├── logs/
│   └── audit.jsonl     ← Structured audit log
├── planning.md         ← Architecture narrative, signal design, API surface, diagrams
└── requirements.txt    ← flask, flask-limiter, groq, python-dotenv
```
