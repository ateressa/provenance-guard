# Provenance Guard — Planning Document

---

## Architecture Narrative

A piece of text enters the system through a single HTTP endpoint: `POST /submit`. The caller sends a JSON body with the content and a content ID. The rate limiter is the first thing it touches — before any analysis runs, flask-limiter checks whether this IP has exceeded the submission quota. If it has, the request is rejected with a 429. If not, the text passes through.

The text then enters the detection pipeline, which runs two independent signals in sequence.

**Signal 1** is an LLM-as-judge call to the Groq API. The classifier sends the text to `llama-3.3-70b-versatile` with a prompt that asks it to evaluate whether the writing shows characteristics of AI generation. The LLM returns a label (`ai_generated` or `human`) and a raw confidence value between 0.0 and 1.0 — where 1.0 means "strongly AI" and 0.0 means "strongly human." This signal captures semantic and stylistic coherence patterns: things like unnaturally consistent tone, absence of hedging, and the specific brand of fluency that LLMs produce.

**Signal 2** is a stylometric heuristic computed in pure Python with no API call. It extracts four statistical properties of the text: sentence length variance, type-token ratio (vocabulary diversity), average word length, and punctuation density. Each property is individually scored and combined into a single heuristic score between 0.0 and 1.0. This signal captures surface statistical patterns: AI text tends to have lower sentence length variance, higher type-token ratios in short passages, and less idiosyncratic punctuation than human writing.

Once both signals have run, the confidence scorer combines them into a single float. Signal 1 carries 60% weight and Signal 2 carries 40% weight. The output is a single `confidence` value between 0.0 and 1.0, where values closer to 1.0 indicate stronger evidence of AI generation.

The transparency label generator reads that confidence score and maps it to one of three label variants:
- `confidence ≥ 0.80` → high-confidence AI label
- `confidence ≤ 0.20` → high-confidence human label
- `0.21–0.79` → uncertain label

The label is a structured object: a short status string, a plain-English explanation for non-technical readers, and the numeric confidence expressed as a percentage.

Before returning the response, the audit logger appends a structured record to `logs/audit.jsonl`. The record includes the timestamp, content ID, both signal scores, the combined confidence, the label assigned, and the full text of the label that was shown. This makes every decision reconstructable after the fact.

The HTTP response returns the attribution result, confidence score, label text, and a content ID the creator can use to file an appeal.

---

The appeal flow is separate. A creator who believes they've been misclassified calls `POST /appeal` with their content ID and a written explanation of why the classification is wrong. The appeal handler looks up the original decision in the in-memory store, updates the content's status to `"under_review"`, and appends the appeal (including the creator's reasoning and the original decision) to the audit log. No automated re-classification happens — a human reviewer would handle that. The API returns a confirmation with the updated status.

---

## Detection Signals

### Signal 1: LLM-as-Judge (Semantic + Stylistic Coherence)

**What it measures:** Whether the text exhibits the semantic and stylistic patterns characteristic of large language model output — unnaturally consistent tone, absence of genuine hedging or uncertainty, specific fluency patterns (smooth transitions, balanced paragraph structure, formulaic openings), and the tendency of LLMs to avoid contradicting themselves even when nuance would call for it.

**Why this differs between human and AI writing:** Human writers show inconsistency that reflects genuine thought: they hedge, contradict themselves, use idiosyncratic phrasing, vary their energy across a piece, and include irrelevant tangents. LLMs optimize toward coherent, well-structured output that reads as polished — but that polish is itself a signal. A poem that is simultaneously structurally perfect and emotionally inert is more likely generated than written.

**Blind spots:** This signal cannot distinguish a highly skilled human writer from AI output. A professional editor's clean prose and an LLM's clean prose look the same to a semantic classifier. It also fails on intentionally minimalist writing, and it can misread heavily edited human work (a piece revised twenty times looks more "AI-like" on this dimension). Short texts (under ~100 words) give the LLM very little signal to work with, making scores unreliable.

---

### Signal 2: Stylometric Heuristics (Surface Statistical Properties)

**What it measures:** Four statistical features computed directly from the text, no API call:

- **Sentence length variance:** the standard deviation of word counts across sentences. Low variance = unusually uniform sentence rhythm.
- **Type-token ratio (TTR):** unique word count divided by total word count. In short passages, AI tends to avoid word repetition more consistently than humans.
- **Average word length:** a proxy for vocabulary register. AI writing in creative contexts often skews toward mid-length, "safe" vocabulary.
- **Punctuation density:** punctuation marks per 100 words. Human creative writing uses punctuation idiosyncratically (em-dashes, ellipses, fragments); AI writing tends toward grammatically standard punctuation.

Each feature is normalized to a 0–1 score (where 1 = strong AI indicator) using empirically chosen thresholds. The four normalized scores are averaged to produce the final heuristic score.

**Why this differs between human and AI writing:** LLMs are trained to produce fluent, grammatically standard text. That training produces statistical regularities at the surface level — consistent sentence rhythm, standard punctuation, non-repetitive vocabulary — that human writers, especially creative writers, don't exhibit. Humans write in bursts: long complex sentences followed by fragments. They repeat words for emphasis. They overuse the em-dash.

**Blind spots:** This signal is easily defeated by any AI system trained specifically on human writing samples, or by post-processing that adds stylistic variation. It also misclassifies writing by non-native English speakers, whose surface statistics often differ from native-speaker norms in ways this signal interprets as AI-like. Academic writing from human authors scores misleadingly AI-like due to formal register norms. Very short texts (under 5 sentences) produce unreliable variance scores.

---

## Transparency Label Text (Verbatim)

These are the exact strings the system returns. All three variants are required to communicate the confidence level meaningfully to a non-technical reader.

**High-confidence AI (confidence ≥ 0.80):**
```
"This content was likely generated by an AI. Our system's confidence is [X]%.
AI-assisted or AI-generated content may not reflect the lived experience or
original voice of the attributed creator. If you are the creator and believe
this classification is wrong, you may submit an appeal using your content ID."
```

**High-confidence Human (confidence ≤ 0.20):**
```
"This content appears to be human-authored. Our system's confidence is [X]%.
Our analysis found stylistic and semantic patterns consistent with human writing.
No further review is required — this label may be updated if an appeal is filed."
```

**Uncertain (confidence 0.21–0.79):**
```
"Attribution uncertain. Our system's confidence is [X]%.
Our analysis could not determine with confidence whether this content is
human-authored or AI-generated. The result should be treated as inconclusive.
If you are the creator, you may submit an appeal with supporting context."
```

In each label, `[X]%` is replaced at runtime with the numeric confidence expressed as a percentage (e.g., "Our system's confidence is 72%"). The confidence is shown to the reader — it is not hidden inside the system.

---

## False Positive Analysis

**Scenario:** A human poet submits a carefully revised, formally structured poem. The LLM-as-judge classifier flags it as high-confidence AI (Signal 1 score: 0.82) because the piece is polished and tonally consistent. The stylometric heuristics return a moderate AI-leaning score (Signal 2 score: 0.58) because the poet favors short, regular lines with low sentence-length variance. Combined score: `(0.82 × 0.60) + (0.58 × 0.40) = 0.724`.

At 0.724, the system lands in the uncertain band (0.21–0.79) and returns the **uncertain label** — not a high-confidence AI label. This is the correct behavior: the system is not confident enough to make a strong attribution claim, and the label text reflects that explicitly ("our system could not determine with confidence...").

**What the label says:** The uncertain label communicates ambiguity to the reader in plain language, recommends treating attribution "with appropriate context," and does not assert that the content is AI-generated. The confidence is shown as a percentage (72%) — visible, not hidden.

**How the creator appeals:** The poet receives a content ID in the response. They call `POST /appeal` with their content ID and a written explanation ("This poem took three years to write; here are earlier drafts..."). The system immediately sets status to `"under_review"`, logs the appeal alongside the original 0.724 score, and returns a confirmation. A human reviewer then sees both the original decision and the creator's reasoning. The system never silently overrides the label without human involvement.

**Design implication:** The uncertain band (0.21–0.79) is intentionally wide. A system that is too quick to assign high-confidence labels will produce more false positives — harming human creators — while a wider uncertain band shifts the burden to human review, where it belongs.

---

## Appeals Workflow (Implementation-Ready)

**Who can submit an appeal:** Any caller with a valid `content_id` returned by `POST /submit`. The system does not require authentication — in a production system, this would be gated to verified creators on the platform. For this project, the content ID itself is the credential.

**What they provide:**
- `content_id`: the ID from the original submission response
- `creator_reasoning`: a free-text string explaining why the classification is wrong (required, minimum 10 characters)

**What the system does when an appeal is received:**
1. Looks up `content_id` in the in-memory store. Returns 404 if not found.
2. Updates the stored record's `status` field from `"classified"` to `"under_review"`.
3. Builds an appeal record containing: `content_id`, `timestamp`, `creator_reasoning`, `original_attribution`, `original_confidence`, `original_signal_scores`, and `status: "under_review"`.
4. Appends the appeal record to `logs/audit.jsonl` with `"event_type": "appeal"` so it's distinguishable from classification events.
5. Returns the updated status and original decision to the caller.

No automated re-classification occurs. The system flags it for human review and stops.

**What a human reviewer sees when they open the appeal queue:**

A reviewer querying `GET /log` and filtering for `event_type: "appeal"` sees entries like this:

```json
{
  "event_type": "appeal",
  "timestamp": "2026-06-27T14:32:11Z",
  "content_id": "a3f9b2",
  "status": "under_review",
  "original_attribution": "ai_generated",
  "original_confidence": 0.83,
  "original_signal_scores": {
    "llm_judge": 0.87,
    "stylometric": 0.76
  },
  "creator_reasoning": "I wrote this poem over three years. The uniform rhythm is intentional — it follows a strict villanelle form I chose deliberately."
}
```

The reviewer sees: the original classification and confidence, both raw signal scores (so they can judge which signal drove the decision), and the creator's explanation. They can compare the creator's reasoning against the signal breakdown and make an informed override decision. The log entry is immutable — the reviewer's decision would be a separate appended record.

---

## API Surface

### `POST /submit`

**Purpose:** Submit text content for attribution analysis.

**Rate limit:** 10 requests per minute per IP (documented in README).

**Request body:**
```json
{
  "content_id": "string (optional — generated if not provided)",
  "text": "string (the content to analyze)"
}
```

**Response:**
```json
{
  "content_id": "string",
  "attribution": "ai_generated | human | uncertain",
  "confidence": 0.0,
  "signals": {
    "llm_judge": { "score": 0.0, "label": "string", "reasoning": "string" },
    "stylometric": { "score": 0.0, "features": { "sentence_variance": 0.0, "ttr": 0.0, "avg_word_length": 0.0, "punctuation_density": 0.0 } }
  },
  "label": {
    "status": "string",
    "display_text": "string",
    "confidence_pct": 0
  }
}
```

**Error responses:** `400` (missing text), `429` (rate limited)

---

### `POST /appeal`

**Purpose:** Contest an attribution decision.

**Request body:**
```json
{
  "content_id": "string",
  "creator_reasoning": "string (why the creator believes the classification is wrong)"
}
```

**Response:**
```json
{
  "content_id": "string",
  "status": "under_review",
  "original_attribution": "string",
  "original_confidence": 0.0,
  "message": "string"
}
```

**Error responses:** `400` (missing fields), `404` (content_id not found)

---

### `GET /log`

**Purpose:** Return recent audit log entries for inspection. (For grader verification and README documentation.)

**Query params:** `?limit=N` (default 20)

**Response:**
```json
{
  "entries": [ ...list of audit records... ],
  "count": 0
}
```

---

## Architecture

### Submission Flow

```
Client
  │
  │  POST /submit  { text, content_id }
  ▼
┌─────────────────┐
│  Rate Limiter   │  10 req/min/IP — reject with 429 if exceeded
└────────┬────────┘
         │ text passes through
         ▼
┌─────────────────────────────────────────────────────┐
│                 Detection Pipeline                   │
│                                                     │
│  ┌─────────────────────┐   ┌──────────────────────┐ │
│  │  Signal 1           │   │  Signal 2             │ │
│  │  LLM-as-Judge       │   │  Stylometric          │ │
│  │  (Groq API)         │   │  Heuristics           │ │
│  │                     │   │  (pure Python)        │ │
│  │  IN:  raw text      │   │  IN:  raw text        │ │
│  │  OUT: label + 0.0–1 │   │  OUT: 0.0–1 score     │ │
│  └──────────┬──────────┘   └──────────┬────────────┘ │
│             │ score (weight 0.60)      │ score (weight 0.40)
│             └──────────┬──────────────┘              │
│                        ▼                             │
│           ┌────────────────────────┐                 │
│           │   Confidence Scorer    │                 │
│           │   weighted average     │                 │
│           │   → single float 0–1   │                 │
│           └────────────┬───────────┘                 │
└────────────────────────┼────────────────────────────┘
                         │ confidence score
                         ▼
              ┌──────────────────────┐
              │  Label Generator     │
              │  ≥0.80 → AI label    │
              │  ≤0.20 → Human label │
              │  else  → Uncertain   │
              └──────────┬───────────┘
                         │ label object
                         ▼
              ┌──────────────────────┐
              │    Audit Logger      │
              │  appends to          │
              │  logs/audit.jsonl    │
              │  (timestamp, signals,│
              │  confidence, label)  │
              └──────────┬───────────┘
                         │
                         ▼
                    HTTP Response
              { content_id, attribution,
                confidence, signals, label }
```

---

### Appeal Flow

```
Client (creator)
  │
  │  POST /appeal  { content_id, creator_reasoning }
  ▼
┌──────────────────────────┐
│   Appeal Handler         │
│                          │
│  1. Look up content_id   │
│     in memory store      │
│     → 404 if not found   │
│                          │
│  2. Update status        │
│     "under_review"       │
│                          │
│  3. Build appeal record  │
│     { original_decision, │
│       creator_reasoning, │
│       timestamp }        │
└──────────────┬───────────┘
               │ appeal record
               ▼
    ┌──────────────────────┐
    │   Audit Logger       │
    │   appends appeal     │
    │   to audit.jsonl     │
    │   (type: "appeal")   │
    └──────────┬───────────┘
               │
               ▼
          HTTP Response
    { content_id, status: "under_review",
      original_attribution, message }
```

---

## Signal 3: Human Voice Markers (Lexical Signal) — Stretch Feature

**What it measures:** Three features that AI writing suppresses in formal and analytical writing modes:
- **Contraction density** (per 100 words): natural speech patterns (`don't`, `I've`, `won't`) that AI defaults to avoiding
- **First-person density** (per 100 words): direct personal voice (`I`, `me`, `my`, `we`) that AI suppresses in favor of third-person or passive constructions
- **Informal marker density** (per 100 words): colloquialisms, hedges, filler words (`honestly`, `ok`, `kinda`, `ugh`) that are absent from AI formal output

**Why this differs between human and AI writing:** AI in analytical/creative mode avoids contractions and first-person because it defaults to a formal register that feels "professional." Human casual writing is saturated with these features. When a text has zero contractions, zero first-person pronouns, and zero informal markers, that absence is itself a signal.

**Blind spots:** This signal is strong for casual content (reviews, personal essays) and weak for formal human content (academic writing, professional criticism). A human film critic writing in analytical mode will score similarly to AI on this signal. The low weight (10%) reflects this limitation — it adds a correction for casual text without overriding the other signals for formal text.

**Sub-feature weights within lexical signal:** contractions 40%, first-person 40%, informal markers 20%.

---

## Confidence Score Design

The combined score uses a weighted average:

```
confidence = (llm_score × 0.60) + (stylometric_score × 0.40)
```

Signal 1 carries higher weight because semantic and stylistic coherence is harder to fake than surface statistics. Signal 2 catches cases the LLM misses (very short text, highly stylized human writing that the LLM finds ambiguous) but is easier to game.

**Label thresholds (calibrated):**

| Confidence | Attribution | Rationale |
|---|---|---|
| ≥ 0.75 | `ai_generated` (high confidence) | Both signals align on AI; label makes a clear claim |
| ≤ 0.30 | `human` (high confidence) | Both signals align on human |
| 0.31–0.74 | `uncertain` | Signals disagree or are individually weak; defer to human review |

*Original planning values were 0.80/0.20. Empirical testing showed the combined score tops out ~0.78 for clearly AI text and bottoms ~0.29 for clearly human text, given these signal weights and the LLM's natural scoring range. Thresholds adjusted to 0.75/0.30 to activate all three label states without overfitting to specific test cases.*

The uncertain band is intentionally wide. A system that overclaims confidence harms human creators through false positives. The cost of a missed AI detection is lower than the cost of wrongly attributing a human's work to an AI.

**What a specific score means:**

A confidence of 0.60 means: the LLM signal and stylometric signal both lean AI-leaning, but neither is strong enough to cross the 0.80 threshold. The system is saying "the evidence points toward AI generation, but there is meaningful doubt." The label for 0.60 is the *uncertain* label — not a softened AI label. 0.60 and 0.95 produce different labels entirely, not just different percentage numbers inside the same label.

A confidence of 0.51 means: the signals are essentially in disagreement or both near-neutral. The system has barely more evidence for AI than human. The uncertain label applies, and the confidence percentage shown is 51% — visible to the reader as nearly a coin flip.

A confidence of 0.95 means: both signals are strongly aligned on AI generation. The LLM classifier returned high-confidence AI, and stylometric features are consistent with that assessment. This is the only case where the system makes a direct attribution claim.

**Raw signal normalization:**

Signal 1 (LLM) outputs a score directly as part of the prompt response — the LLM is asked to return a float between 0.0 and 1.0 alongside its label. No further normalization needed.

Signal 2 (stylometric) normalizes each of its four features independently before averaging:

- Sentence length variance: score = `max(0, 1 - (variance / 50))` — variance above 50 words² scores near 0 (human-like); below 10 scores near 1 (AI-like)
- Type-token ratio: score = `min(1, ttr / 0.85)` — TTR above 0.85 in short passages is AI-characteristic; below 0.60 is human-characteristic
- Average word length: score = `1 - abs(avg_len - 5.2) / 3` — AI writing clusters near 5.2 chars; human writing varies more widely
- Punctuation density: score = `max(0, 1 - (punct_per_100 / 8))` — below 3 per 100 words scores AI-like; above 8 scores human-like

The four normalized scores are averaged to produce Signal 2's final 0–1 output.

These thresholds are set as constants in `config.py` and can be adjusted after testing against sample texts.

---

## File Structure (planned)

```
provenance-guard/
├── app.py              ← Flask app, route definitions, rate limiter setup
├── classifier.py       ← Signal 1: LLM-as-judge via Groq
├── stylometrics.py     ← Signal 2: heuristic feature extraction
├── scorer.py           ← Confidence weighting + label generation
├── auditor.py          ← Audit log append (same .jsonl pattern as repairsafe)
├── store.py            ← In-memory content store (dict: content_id → record)
├── config.py           ← GROQ_API_KEY, LLM_MODEL, LOG_FILE, thresholds
├── logs/
│   └── audit.jsonl     ← Append-only structured audit log
├── planning.md         ← This file
├── README.md           ← Label text, rate-limit reasoning, sample log entries
└── requirements.txt    ← flask, flask-limiter, groq, python-dotenv
```

---

## Anticipated Edge Cases

### Edge Case 1: A villanelle or highly repetitive poem
A villanelle (a 19-line poem with a strict repeating refrain) has extremely low sentence length variance, intentional word repetition, and regular rhythm — all of which the stylometric signal interprets as AI-characteristic. The type-token ratio is low because the refrain lines repeat verbatim. Signal 2 would score this 0.70–0.80 even for a human-written villanelle. Signal 1 (LLM-as-judge) may partially compensate by recognizing the form, but is likely to be confused by the repetition as well.

**Expected behavior:** Combined score lands in the uncertain band (0.50–0.70). The system returns the uncertain label rather than falsely attributing the work as AI. If the creator appeals, the reviewer has context to override.

**What the system cannot do:** Distinguish between a human-written villanelle and an AI-generated villanelle. Both look statistically identical to Signal 2. This is an acknowledged limitation documented in the README.

---

### Edge Case 2: A non-native English speaker's creative writing
A writer whose first language is not English may produce text with short, syntactically simple sentences, low punctuation density, basic vocabulary, and high uniformity — because they are writing carefully within the bounds of their second language, not because they used AI. The stylometric signal scores all of these as AI-characteristic. Signal 1 may also be confused because the simplicity and consistency resembles LLM output.

**Expected behavior:** Combined score may push above 0.70–0.80, potentially into the high-confidence AI zone even though the writing is entirely human. This is the highest-risk false positive scenario in the system.

**What the system cannot do:** Distinguish stylistic simplicity driven by language learning from AI generation. This is a documented limitation. The appeals workflow is the mitigation — the creator can submit an appeal, and a human reviewer who reads the creator_reasoning in context can identify the cause.

---

### Edge Case 3: A very short submission (under 50 words)
Short texts provide insufficient signal for both detectors. Signal 1 (LLM) explicitly notes that under ~100 words makes it unreliable. Signal 2's sentence variance calculation is statistically meaningless with fewer than 4–5 sentences.

**Expected behavior:** Both signals return near-neutral scores (0.45–0.55). Combined confidence lands near 0.50 — deeply in the uncertain band. The uncertain label is returned with a confidence of approximately 50%, which accurately communicates to the reader that the system has almost no basis for a claim.

**Mitigation:** The system will include a `text_too_short` warning flag in the response when the submission is under 50 words, alerting the caller that scores are unreliable at this length.

---

## AI Tool Plan

For each implementation milestone: which spec sections to provide, what to ask the AI tool to generate, and how to verify the output before accepting it.

---

### M3 — Submission Endpoint + First Signal

**Spec sections to provide:**
- `## Detection Signals` (Signal 1 description: what it measures, output format, blind spots)
- `## Architecture` (submission flow diagram — labels on every arrow)
- `## API Surface` (POST /submit contract: request body, response schema)

**What to ask the AI tool to generate:**
1. Flask app skeleton: `app.py` with `POST /submit` stub that accepts `text` + `creator_id`, returns a hardcoded response so the route can be verified before logic is added
2. `classifier.py`: the LLM-as-judge function with the full system prompt, three-line output format (`Label:` / `Score:` / `Reasoning:`), parse logic, and `caution`-style fallback on parse error

**How to verify before wiring in:**
- Check function signature matches spec: returns `{"label": str, "score": float, "reasoning": str}` — not a binary flag, not a raw string
- Call `classify_llm()` directly on 3 inputs before touching `app.py`: one clearly AI text, one clearly human text, one short ambiguous text
- Confirm the score is a float in 0.0–1.0, not a label name
- Confirm fallback fires correctly by temporarily mangling the output format
- Only wire into the endpoint after standalone tests pass

---

### M4 — Second Signal + Confidence Scoring

**Spec sections to provide:**
- `## Detection Signals` (Signal 2: four sub-features, normalization formulas, blind spots)
- `## Confidence Score Design` (weighted average formula, threshold table, what 0.60 means vs 0.95)
- `## Architecture` (submission flow diagram — specifically the confidence scorer box and its inputs)

**What to ask the AI tool to generate:**
1. `stylometrics.py`: the four sub-feature functions (sentence variance, TTR, avg word length, punctuation density), normalization formulas from spec, equal-weight average
2. `scorer.py`: `combine_scores(llm, stylo)` using the 60/40 weights, `attribution_from_score()` using the threshold constants from `config.py`

**What to check — do scores vary meaningfully?**
- Run both signals independently on all four milestone test inputs before combining
- Print signal scores side by side: do they agree on clearly AI text? Disagree on borderline text? Agreement = both signals working; disagreement = uncertainty the combined score should reflect
- Verify the scoring formula exactly matches planning spec: `(llm × 0.60) + (stylo × 0.40)` — AI tools sometimes silently swap weights or average without weighting
- Verify thresholds match constants in `config.py`, not hardcoded literals in `scorer.py`
- Confirm all three label states (`ai_generated` / `uncertain` / `human`) are reachable across the four test inputs — if all four land in `uncertain`, the thresholds need calibration

---

### M5 — Production Layer (Labels + Appeals)

**Spec sections to provide:**
- `## Transparency Label Text (Verbatim)` (exact strings for all three variants, `[X]%` substitution)
- `## Appeals Workflow (Implementation-Ready)` (who can appeal, what they provide, what the system does, what a reviewer sees)
- `## Architecture` (appeal flow diagram — status update and audit log arrows)

**What to ask the AI tool to generate:**
1. `_build_label(confidence)` function: maps float → dict with `status`, `display_text`, `confidence_pct`; must branch on `THRESHOLD_AI` and `THRESHOLD_HUMAN` constants, not hardcoded numbers
2. `POST /appeal` endpoint: looks up `content_id`, updates status, calls `auditor.log_appeal()`, returns confirmation

**How to verify:**

*Labels:*
- Ask the generated function to produce all three variants with inputs `0.10`, `0.50`, `0.85` and compare the output text character-by-character against the verbatim strings in this spec
- Confirm `[X]%` is replaced with the actual percentage, not the raw float
- Confirm the status field uses the machine-readable key (`ai_generated`, `human`, `uncertain`), not the display text

*Appeals:*
- Submit a test piece, save the `content_id`, then call `POST /appeal`
- Immediately call `GET /log` and verify: (1) an entry with `event_type: "appeal"` exists, (2) `status` is `"under_review"`, (3) `creator_reasoning` is populated with what was submitted, (4) `original_attribution` and `original_confidence` match the original classification
- Call `POST /appeal` again with the same `content_id` — verify the store reflects `status: "under_review"` rather than reverting

---

## Open Questions (to resolve before implementing)

1. **Content ID generation:** UUID4 generated server-side if caller doesn't provide one. Caller-provided IDs let platforms track content across their own systems.
2. **In-memory store scope:** The store is per-process and not persisted. Appeals on previously submitted content only work within the same server session. Acceptable for this project; production would use a database.
3. **Stylometric thresholds:** The normalization thresholds for each heuristic feature need calibration against sample texts. These will be set as constants in `config.py` after testing.
4. **LLM temperature:** Signal 1 classifier will use `temperature=0` for deterministic output, same as the repairsafe classifier.
