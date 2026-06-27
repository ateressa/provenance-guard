import re
import math
from config import (
    SENT_VARIANCE_MAX,
    TTR_HUMAN_THRESHOLD,
    TTR_AI_THRESHOLD,
    AVG_WORD_LEN_CENTER,
    PUNCT_PER_100_MAX,
    MIN_RELIABLE_WORDS,
)


def _sentences(text: str) -> list[str]:
    parts = re.split(r'(?<=[.!?])\s+', text.strip())
    return [s for s in parts if s.strip()]


def _words(text: str) -> list[str]:
    return re.findall(r"\b[a-zA-Z']+\b", text.lower())


def _sentence_variance_score(sentences: list[str]) -> float:
    """
    Low variance (uniform sentence rhythm) → score near 1.0 (AI-like).
    High variance (mixed short/long sentences) → score near 0.0 (human-like).

    Normalization: variance above SENT_VARIANCE_MAX (50 words²) → 0.0 (human).
    Variance near 0 → 1.0 (AI).
    With fewer than 3 sentences, return 0.5 (neutral — insufficient data).
    """
    if len(sentences) < 3:
        return 0.5

    lengths = [len(s.split()) for s in sentences]
    mean = sum(lengths) / len(lengths)
    variance = sum((l - mean) ** 2 for l in lengths) / len(lengths)

    score = max(0.0, 1.0 - (variance / SENT_VARIANCE_MAX))
    return round(score, 4)


def _ttr_score(words: list[str]) -> float:
    """
    Type-token ratio = unique words / total words.
    High TTR in short passages → AI-like (score near 1.0).
    Low TTR → human-like repetition (score near 0.0).

    TTR is unreliable below 100 words: nearly any short text has high TTR
    because words aren't repeated enough to depress the ratio. Return 0.5
    (neutral) for short texts rather than a meaningless AI-leaning score.

    For longer texts, use a bounded range: TTR <= TTR_HUMAN_THRESHOLD (0.55)
    scores as 0.0 (human-like), TTR >= TTR_AI_THRESHOLD (0.85) scores as 1.0
    (AI-like). TTR between those bounds is normalized linearly. This prevents
    inflated TTR from proper-noun-heavy human writing (film lists, citations)
    from being scored as AI-like — the old floor-at-zero formula treated any
    TTR as proportionally AI-leaning, even at 0.72 which is typical human range.
    """
    if len(words) < 100:
        return 0.5

    ttr = len(set(words)) / len(words)
    score = (ttr - TTR_HUMAN_THRESHOLD) / (TTR_AI_THRESHOLD - TTR_HUMAN_THRESHOLD)
    return round(max(0.0, min(1.0, score)), 4)


def _avg_word_length_score(words: list[str]) -> float:
    """
    AI writing clusters near AVG_WORD_LEN_CENTER (5.2 chars).
    Human writing varies more widely — both shorter and longer extremes.

    Score = 1 - abs(avg_len - center) / 3.
    Clamped to [0, 1]: diverging far from center → score near 0 (human-like).
    """
    if not words:
        return 0.5

    avg = sum(len(w) for w in words) / len(words)
    score = max(0.0, 1.0 - abs(avg - AVG_WORD_LEN_CENTER) / 3.0)
    return round(score, 4)


def _punctuation_density_score(text: str, words: list[str]) -> float:
    """
    Punctuation marks per 100 words.
    Low density (< 3/100) → AI-like, score near 1.0.
    High density (> PUNCT_PER_100_MAX = 8/100) → human-like, score near 0.0.

    Human creative writing: em-dashes, ellipses, exclamations, fragments.
    AI writing: grammatically standard, minimal extra punctuation.
    """
    if not words:
        return 0.5

    punct_count = len(re.findall(r'[,;:!?\-—…"]', text))
    density = (punct_count / len(words)) * 100
    score = max(0.0, 1.0 - (density / PUNCT_PER_100_MAX))
    return round(score, 4)


def classify_stylometric(text: str) -> dict:
    """
    Signal 2: stylometric heuristics.

    Returns:
        {
            "score": float (0.0–1.0, where 1.0 = strong AI signal),
            "features": {
                "sentence_variance": float,
                "ttr": float,
                "avg_word_length": float,
                "punctuation_density": float,
                "raw": {
                    "sentence_count": int,
                    "word_count": int,
                    "variance": float,
                    "ttr_raw": float,
                    "avg_word_len_raw": float,
                    "punct_per_100": float,
                }
            }
        }
    """
    sentences = _sentences(text)
    words = _words(text)

    sv_score = _sentence_variance_score(sentences)
    ttr_score = _ttr_score(words)
    awl_score = _avg_word_length_score(words)
    pd_score = _punctuation_density_score(text, words)

    # Weighted average: sentence variance and TTR are most reliable;
    # punctuation density is least reliable (formal AI text uses natural commas).
    combined = (sv_score * 0.35 + ttr_score * 0.35 + awl_score * 0.20 + pd_score * 0.10)

    # Raw values for debugging / audit
    word_count = len(words)
    lengths = [len(s.split()) for s in sentences]
    mean = sum(lengths) / len(lengths) if lengths else 0
    variance = sum((l - mean) ** 2 for l in lengths) / len(lengths) if lengths else 0
    ttr_raw = len(set(words)) / word_count if word_count else 0
    avg_word_len_raw = sum(len(w) for w in words) / word_count if word_count else 0
    punct_count = len(re.findall(r'[,;:!?\-—…"]', text))
    punct_per_100 = (punct_count / word_count * 100) if word_count else 0

    return {
        "score": round(combined, 4),
        "features": {
            "sentence_variance": sv_score,
            "ttr": ttr_score,
            "avg_word_length": awl_score,
            "punctuation_density": pd_score,
            "raw": {
                "sentence_count": len(sentences),
                "word_count": word_count,
                "variance": round(variance, 2),
                "ttr_raw": round(ttr_raw, 4),
                "avg_word_len_raw": round(avg_word_len_raw, 2),
                "punct_per_100": round(punct_per_100, 2),
            },
        },
    }
