import hashlib
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def secure_api_key() -> str:
    return secrets.token_urlsafe(32)


def stable_device_id(name: str, key: str) -> str:
    digest = hashlib.sha1(f"{name}:{key}".encode("utf-8")).hexdigest()
    return digest[:12]


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def read_json(path: Path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, data) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)

