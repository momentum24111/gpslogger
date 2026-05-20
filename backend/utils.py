import hashlib
import json
import secrets
import socket
from datetime import datetime, timezone
from pathlib import Path
from urllib import error as urlerror
from urllib import request as urlrequest


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


def http_post_json(url: str, payload: dict, *, timeout: float = 12.0) -> tuple[bool, int, str | None]:
    """POST mit JSON-Body. Liefert (ok, http_status, detail). Bei Netzwerkfehlern ist http_status 0."""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urlrequest.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            code = int(getattr(resp, "status", 200) or 200)
            return (200 <= code < 300, code, None)
    except urlerror.HTTPError as exc:
        code = int(getattr(exc, "code", 0) or 0)
        return (False, code, str(exc))
    except (urlerror.URLError, TimeoutError, socket.timeout, OSError) as exc:
        return (False, 0, str(exc))

