from config import WEIGHT_LLM, WEIGHT_STYLOMETRIC, WEIGHT_LEXICAL, THRESHOLD_AI, THRESHOLD_HUMAN


def combine_scores(llm_score: float, stylometric_score: float, lexical_score: float) -> float:
    """
    3-signal ensemble: weighted average.

    Weights per planning.md (updated for ensemble):
        Signal 1 (LLM-as-judge):   60%  — semantic/stylistic coherence
        Signal 2 (Stylometric):    30%  — surface statistical properties
        Signal 3 (Lexical):        10%  — human voice markers

    LLM carries the most weight because it captures semantic patterns that
    pure statistics cannot. Stylometric catches cases where the LLM is fooled
    by intentional style variation. Lexical adds a small correction for casual
    human writing (contractions, first-person, informal markers) that both
    other signals may miss.

    All inputs are 0.0–1.0 where 1.0 = strong AI signal.
    Output is 0.0–1.0 with the same convention.
    """
    confidence = (
        llm_score * WEIGHT_LLM
        + stylometric_score * WEIGHT_STYLOMETRIC
        + lexical_score * WEIGHT_LEXICAL
    )
    return round(max(0.0, min(1.0, confidence)), 4)


def attribution_from_score(confidence: float) -> str:
    if confidence >= THRESHOLD_AI:
        return "ai_generated"
    if confidence <= THRESHOLD_HUMAN:
        return "human"
    return "uncertain"
