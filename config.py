import os
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
LLM_MODEL = "llama-3.3-70b-versatile"
LOG_FILE = "logs/audit.jsonl"

# Confidence thresholds — calibrated after empirical testing.
# Combined scores empirically top out ~0.78 for clearly AI text and bottom ~0.29
# for clearly human text given these signal weights. Original planning values of
# 0.80/0.20 were unreachable; adjusted to 0.75/0.30 to activate all three label states.
THRESHOLD_AI = 0.75       # >= this → high-confidence AI
THRESHOLD_HUMAN = 0.30    # <= this → high-confidence human
# anything between → uncertain

# Signal weights (3-signal ensemble)
WEIGHT_LLM = 0.60
WEIGHT_STYLOMETRIC = 0.30
WEIGHT_LEXICAL = 0.10

# Provenance certificate settings
CERT_MAX_CONFIDENCE = 0.45   # creator_statement must score <= this to earn certificate

# Stylometric normalization constants
SENT_VARIANCE_MAX = 50.0   # variance above this → human-like (score → 0)
TTR_HUMAN_THRESHOLD = 0.55 # TTR below this → human-like (repetitive, natural)
TTR_AI_THRESHOLD = 0.85    # TTR above this → AI-like (diverse, non-repetitive)
AVG_WORD_LEN_CENTER = 5.2  # AI writing clusters here
PUNCT_PER_100_MAX = 8.0    # above this → human-like punctuation density

# Rate limiting
RATE_LIMIT = "10 per minute;100 per day"

# Minimum text length for reliable scoring
MIN_RELIABLE_WORDS = 50
