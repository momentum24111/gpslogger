"""Laden und Formatierung von UI-Sprachdateien für serverseitige Telegram-Nachrichten."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def normalize_ui_language(language: str | None) -> str:
    lang = str(language or "").strip().lower()
    return lang if lang in ("de", "en") else "de"


def _nested_get(root: dict, dotted_key: str) -> str | None:
    cur: object = root
    for part in dotted_key.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur if isinstance(cur, str) else None


@lru_cache(maxsize=4)
def _load_language_file(lang_code: str) -> dict[str, object]:
    path = ROOT / "static" / "languages" / f"{lang_code}.json"
    if not path.exists():
        path = ROOT / "static" / "languages" / "de.json"
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def translate(language: str | None, key: str, vars: dict[str, object] | None = None) -> str:
    lang = normalize_ui_language(language)
    bundle = _load_language_file(lang)
    raw = _nested_get(bundle, key) or _nested_get(_load_language_file("de"), key) or key
    if not vars:
        return raw
    out = raw
    for name, val in vars.items():
        out = out.replace("{" + str(name) + "}", "" if val is None else str(val))
    return out


def invalidate_locale_cache() -> None:
    """Hauptsächlich für Tests oder Hot-Reload."""
    _load_language_file.cache_clear()


def format_inactivity_duration(language: str | None, value: int, unit: str) -> str:
    """Lokalisierte Dauer-Anzeige (Minuten/Stunden mit Singular)."""
    v = max(1, int(value))
    u = str(unit or "minutes").strip().lower()
    lang = normalize_ui_language(language)
    if u == "hours":
        tmpl_key_one = "settings.notifications.inactivity.durationHoursOne"
        tmpl_key_many = "settings.notifications.inactivity.durationHoursMany"
    else:
        tmpl_key_one = "settings.notifications.inactivity.durationMinutesOne"
        tmpl_key_many = "settings.notifications.inactivity.durationMinutesMany"
    key = tmpl_key_one if v == 1 else tmpl_key_many
    return translate(lang, key, {"count": v})
