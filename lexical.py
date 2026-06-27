import re

# Words that contract in natural English speech — AI writing avoids these
_CONTRACTIONS = {
    "don't", "cant", "won't", "didn't", "isn't", "aren't", "wasn't", "weren't",
    "haven't", "hasn't", "hadn't", "wouldn't", "couldn't", "shouldn't",
    "i'm", "i've", "i'll", "i'd", "you're", "you've", "you'll", "you'd",
    "he's", "she's", "it's", "they're", "they've", "they'll", "they'd",
    "we're", "we've", "we'll", "we'd", "that's", "there's", "here's",
    "let's", "who's", "what's", "how's", "where's", "doesn't", "ain't",
    "could've", "would've", "should've", "must've", "might've",
}

# First-person pronouns — AI writing in analytical/formal mode suppresses these
_FIRST_PERSON = {"i", "me", "my", "mine", "myself", "we", "us", "our", "ours", "ourselves"}

# Informal markers — colloquialisms, hedges, and filler words rare in AI output
_INFORMAL = {
    "ok", "okay", "yeah", "yep", "nope", "honestly", "tbh", "imo", "lol",
    "hmm", "hm", "um", "uh", "anyway", "literally", "basically", "actually",
    "kinda", "gonna", "wanna", "gotta", "sorta", "dunno", "nah", "eh",
    "welp", "ugh", "omg", "wtf", "lmao", "tbf", "fwiw", "iirc",
}


def classify_lexical(text: str) -> dict:
    """
    Signal 3: Human voice markers.

    Measures three features that AI writing suppresses in formal/analytical contexts:
    - Contraction density: natural speech patterns that AI avoids
    - First-person density: direct personal voice (AI defaults to third-person/passive)
    - Informal marker density: colloquialisms, hedges, filler words

    Returns:
        {
            "score": float (0.0–1.0, where 1.0 = strong AI signal / no human markers),
            "features": { contraction_score, first_person_score, informal_score, raw }
        }
    """
    # Tokenize preserving apostrophes for contractions
    words = re.findall(r"\b[\w']+\b", text.lower())
    if len(words) < 10:
        return {
            "score": 0.5,
            "features": {
                "contraction_score": 0.5,
                "first_person_score": 0.5,
                "informal_score": 0.5,
                "raw": {"word_count": len(words), "note": "too short for reliable scoring"},
            },
        }

    total = len(words)

    contraction_count = sum(1 for w in words if w in _CONTRACTIONS)
    first_person_count = sum(1 for w in words if w in _FIRST_PERSON)
    informal_count = sum(1 for w in words if w in _INFORMAL)

    contraction_density = (contraction_count / total) * 100
    first_person_density = (first_person_count / total) * 100
    informal_density = (informal_count / total) * 100

    # Score each feature: 0.0 = strongly human-like, 1.0 = strongly AI-like
    # Normalization anchors chosen so typical human casual writing scores < 0.40
    contraction_score = max(0.0, 1.0 - contraction_density / 4.0)   # 4+ per 100 → near 0
    first_person_score = max(0.0, 1.0 - first_person_density / 6.0)  # 6+ per 100 → near 0
    informal_score = max(0.0, 1.0 - informal_density / 3.0)          # 3+ per 100 → near 0

    # Weighted within signal: contractions and first-person equally important,
    # informal markers carry less weight (rarer even in human casual writing)
    combined = (
        contraction_score * 0.40
        + first_person_score * 0.40
        + informal_score * 0.20
    )

    return {
        "score": round(max(0.0, min(1.0, combined)), 4),
        "features": {
            "contraction_score": round(contraction_score, 4),
            "first_person_score": round(first_person_score, 4),
            "informal_score": round(informal_score, 4),
            "raw": {
                "word_count": total,
                "contraction_count": contraction_count,
                "contraction_density": round(contraction_density, 2),
                "first_person_count": first_person_count,
                "first_person_density": round(first_person_density, 2),
                "informal_count": informal_count,
                "informal_density": round(informal_density, 2),
            },
        },
    }
