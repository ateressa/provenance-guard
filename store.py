_store: dict[str, dict] = {}


def save(content_id: str, record: dict) -> None:
    _store[content_id] = record


def get(content_id: str) -> dict | None:
    return _store.get(content_id)


def update_status(content_id: str, status: str) -> bool:
    if content_id not in _store:
        return False
    _store[content_id]["status"] = status
    return True


def attach_certificate(content_id: str, certificate: dict) -> bool:
    if content_id not in _store:
        return False
    _store[content_id]["certificate"] = certificate
    _store[content_id]["status"] = "verified_human"
    return True


def all_records() -> list[dict]:
    return list(_store.values())
