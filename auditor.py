import json
import os
from datetime import datetime, timezone
from config import LOG_FILE


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def log_classification(
    content_id: str,
    creator_id: str,
    attribution: str,
    confidence: float,
    llm_score: float,
    stylometric_score: float | None = None,
    lexical_score: float | None = None,
    content_type: str = "text",
    text_too_short: bool = False,
) -> None:
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    record = {
        "event_type": "classification",
        "timestamp": _now(),
        "content_id": content_id,
        "creator_id": creator_id,
        "content_type": content_type,
        "attribution": attribution,
        "confidence": round(confidence, 4),
        "llm_score": round(llm_score, 4),
        "stylometric_score": round(stylometric_score, 4) if stylometric_score is not None else None,
        "lexical_score": round(lexical_score, 4) if lexical_score is not None else None,
        "text_too_short": text_too_short,
        "status": "classified",
    }
    _append(record)
    print(f"[LOG] classification | {content_id} | {attribution} | conf={confidence:.2f}")


def log_certificate(content_id: str, creator_id: str, certificate_id: str, statement_confidence: float) -> None:
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    record = {
        "event_type": "certificate_issued",
        "timestamp": _now(),
        "content_id": content_id,
        "creator_id": creator_id,
        "certificate_id": certificate_id,
        "statement_confidence": round(statement_confidence, 4),
    }
    _append(record)
    print(f"[LOG] certificate | {content_id} | cert={certificate_id}")


def log_appeal(
    content_id: str,
    creator_reasoning: str,
    original_attribution: str,
    original_confidence: float,
) -> None:
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    record = {
        "event_type": "appeal",
        "timestamp": _now(),
        "content_id": content_id,
        "status": "under_review",
        "original_attribution": original_attribution,
        "original_confidence": round(original_confidence, 4),
        "creator_reasoning": creator_reasoning,
    }
    _append(record)
    print(f"[LOG] appeal | {content_id} | was={original_attribution}")


def get_log(limit: int = 20) -> list[dict]:
    if not os.path.exists(LOG_FILE):
        return []
    entries = []
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries[-limit:]


def _append(record: dict) -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
