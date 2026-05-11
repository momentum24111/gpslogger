"""Validierung des NAS-/Export-Verzeichnisses und Hilfen für NDJSON-Dateinamen."""

from __future__ import annotations

import errno
import json
import re
import uuid
from pathlib import Path
from typing import Any

# Fehlerschlüssel für die UI (i18n unter settings.storage.error.*)
ERR_PATH_EMPTY = "settings.storage.error.pathEmpty"
ERR_PATH_NOT_ABSOLUTE = "settings.storage.error.pathNotAbsolute"
ERR_PATH_NOT_FOUND = "settings.storage.error.pathNotFound"
ERR_NOT_A_DIRECTORY = "settings.storage.error.notADirectory"
ERR_PERMISSION_DENIED = "settings.storage.error.permissionDenied"
ERR_INVALID_PATH = "settings.storage.error.invalidPath"
ERR_WRITE_TEST_FAILED = "settings.storage.error.writeTestFailed"
ERR_WRITE_FAILED = "settings.storage.error.writeFailed"


def sanitize_device_ndjson_stem(device_name: str, *, max_len: int = 64) -> str:
    """Sicherer Dateiname-Stamm aus dem Gerätenamen (keine Pfadsegmente)."""
    raw = str(device_name or "").strip()
    stem = re.sub(r"[^\w\-.]+", "_", raw, flags=re.UNICODE)
    stem = stem.strip("._")
    if not stem:
        stem = "device"
    return stem[:max_len]


def device_ndjson_filename(device_name: str, device_id: str) -> str:
    """Eindeutiger NDJSON-Dateiname: primär Gerätename, plus Geräte-ID."""
    stem = sanitize_device_ndjson_stem(device_name)
    did = re.sub(r"[^a-zA-Z0-9]", "", str(device_id or ""))[:16] or "id"
    return f"{stem}_{did}.ndjson"


def validate_absolute_writable_directory(dir_path: Path) -> str | None:
    """
    Prüft Existenz, Verzeichnis, Schreibrechte und Anlegen/Löschen einer Testdatei.
    Rückgabe: None bei Erfolg, sonst i18n-Fehlerschlüssel.
    """
    try:
        if not dir_path.is_absolute():
            return ERR_PATH_NOT_ABSOLUTE
        if not dir_path.exists():
            return ERR_PATH_NOT_FOUND
        if not dir_path.is_dir():
            return ERR_NOT_A_DIRECTORY
        if not dir_path.parts:
            return ERR_INVALID_PATH
    except OSError:
        return ERR_INVALID_PATH

    probe = dir_path / f".gpslogger_write_probe_{uuid.uuid4().hex}"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        if exc.errno in (errno.EACCES, errno.EPERM):
            return ERR_PERMISSION_DENIED
        if exc.errno in (errno.ENOENT, errno.ENOTDIR):
            return ERR_PATH_NOT_FOUND
        return ERR_WRITE_TEST_FAILED
    except Exception:
        return ERR_WRITE_TEST_FAILED
    return None


def count_ndjson_lines(path: Path) -> int:
    """Zählt nicht-leere Zeilen (eine JSON-Zeile pro Position)."""
    if not path.exists() or not path.is_file():
        return 0
    n = 0
    with path.open("rb") as handle:
        for line in handle:
            if line.strip():
                n += 1
    return n


def build_ndjson_export_record(item: dict[str, Any]) -> dict[str, Any]:
    """Vollständiger JSON-Datensatz pro Zeile für NDJSON-Export."""
    out: dict[str, Any] = {
        "timestamp": item.get("timestamp") or item.get("received_at"),
        "device_id": item.get("device_id"),
        "device_name": item.get("device_name"),
        "latitude": item.get("latitude"),
        "longitude": item.get("longitude"),
        "accuracy": item.get("accuracy"),
        "battery": item.get("battery"),
        "speed": item.get("speed"),
        "direction": item.get("direction"),
        "altitude": item.get("altitude"),
        "provider": item.get("provider"),
        "activity": item.get("activity"),
        "request_device": item.get("request_device"),
        "device": item.get("device"),
        "time": item.get("time"),
        "received_at": item.get("received_at"),
        "ingest_route": item.get("ingest_route"),
    }
    if item.get("extra_fields") is not None:
        out["extra_fields"] = item.get("extra_fields")
    if item.get("raw_body") is not None:
        out["raw_body"] = item.get("raw_body")
    return {k: v for k, v in out.items() if v is not None}


def export_line_for_item(item: dict[str, Any]) -> str:
    rec = build_ndjson_export_record(item)
    return json.dumps(rec, ensure_ascii=False) + "\n"


def validate_nas_path_string_for_settings(path_str: str) -> str | None:
    """Leer erlaubt; sonst muss der Pfad absolut sein. Keine Verzeichnisprüfung beim Speichern der Einstellungen."""
    text = str(path_str or "").strip()
    if not text:
        return None
    try:
        p = Path(text)
    except Exception:
        return ERR_INVALID_PATH
    if not p.is_absolute():
        return ERR_PATH_NOT_ABSOLUTE
    return None
