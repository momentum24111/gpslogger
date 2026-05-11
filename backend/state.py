import errno
import json
import threading
import time
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import parse as urlparse

from .gps_storage import (
    ERR_PATH_EMPTY,
    ERR_WRITE_FAILED,
    count_ndjson_lines,
    device_ndjson_filename,
    export_line_for_item,
    validate_absolute_writable_directory,
    validate_nas_path_string_for_settings,
)
from .utils import ensure_dir, read_json, secure_api_key, stable_device_id, utc_now_iso, write_json

DEVICE_DRAFT_TTL_SEC = 900

# Index 0..N-1 verweist auf Theme-Variablen --device-map-palette-{i} (Farben nur in theme.css).
DEVICE_MAP_COLOR_COUNT = 6
FORWARDING_BODY_SOURCES = {
    "latitude",
    "longitude",
    "device_name",
    "request_device",
    "accuracy",
    "battery",
    "speed",
    "direction",
    "altitude",
    "provider",
    "activity",
    "timestamp",
    "device_id",
}

DEFAULT_SETTINGS = {
    "nas_interval_seconds": 60,
    "nas_path": "",
    "forwardings": [],
    "theme": "light",
}


class ConfigFieldError(ValueError):
    """Ungültige Einstellungen mit maschinenlesbarem i18n-Schlüssel."""

    def __init__(self, error_key: str):
        self.error_key = error_key
        super().__init__(error_key)


def is_http_url(value: str) -> bool:
    try:
        parsed = urlparse.urlparse(value)
    except Exception:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


class AppState:
    def __init__(self, root_path: Path):
        self.root = root_path
        self.data_dir = self.root / "data"
        ensure_dir(self.data_dir)

        self.devices_path = self.data_dir / "devices.json"
        self.settings_path = self.data_dir / "settings.json"
        self.gps_path = self.data_dir / "gps.ndjson"
        self.pending_path = self.data_dir / "pending_nas.json"
        self.status_path = self.data_dir / "device_statuses.json"
        self.forward_log_path = self.data_dir / "forwarding_errors.log"
        self.export_meta_path = self.data_dir / "nas_export_meta.json"

        self._lock = threading.RLock()
        self.devices: list[dict[str, Any]] = read_json(self.devices_path, [])
        self.settings: dict[str, Any] = {**DEFAULT_SETTINGS, **read_json(self.settings_path, {})}
        self.pending_nas: list[dict[str, Any]] = read_json(self.pending_path, [])
        self.device_statuses: dict[str, dict[str, Any]] = read_json(self.status_path, {})
        if not self.device_statuses and self.gps_path.exists():
            self.device_statuses = self._rebuild_statuses_from_gps()
        self.last_nas_run_at: str | None = None
        self.last_nas_saved_count: int = 0
        self.last_nas_error: str | None = None
        self._device_drafts: dict[str, tuple[float, str]] = {}

        self._migrate_settings_forwardings()
        self._migrate_devices_map_color()
        self._migrate_legacy_nas_path_default()
        self._persist_devices()
        self._persist_settings()
        self._persist_pending()
        self._persist_statuses()

    def _persist_devices(self) -> None:
        write_json(self.devices_path, self.devices)

    def _persist_settings(self) -> None:
        write_json(self.settings_path, self.settings)

    def _persist_pending(self) -> None:
        write_json(self.pending_path, self.pending_nas)

    def _persist_statuses(self) -> None:
        write_json(self.status_path, self.device_statuses)

    def _migrate_devices_map_color(self) -> None:
        """Für bestehende Geräte ohne map_color_index: stabiler Default aus Listenposition."""
        changed = False
        for i, device in enumerate(self.devices):
            if not isinstance(device, dict):
                continue
            if device.get("map_color_index") is None:
                device["map_color_index"] = i % DEVICE_MAP_COLOR_COUNT
                changed = True
        if changed:
            self._persist_devices()

    def _migrate_legacy_nas_path_default(self) -> None:
        """Alter Platzhalter-Default `nas_storage` entfernen."""
        if str(self.settings.get("nas_path", "")).strip() == "nas_storage":
            self.settings["nas_path"] = ""
            self._persist_settings()

    @staticmethod
    def normalize_map_color_index(raw: Any) -> int:
        try:
            idx = int(raw)
        except (TypeError, ValueError):
            raise ValueError("map_color_index muss eine ganze Zahl sein")
        if idx < 0 or idx >= DEVICE_MAP_COLOR_COUNT:
            raise ValueError(f"map_color_index muss zwischen 0 und {DEVICE_MAP_COLOR_COUNT - 1} liegen")
        return idx

    def _migrate_settings_forwardings(self) -> None:
        """Legacy: eine globale Weiterleitung → Liste forwardings[]."""
        data = self.settings
        existing = data.get("forwardings")
        if isinstance(existing, list) and len(existing) > 0:
            data["forwardings"] = [self._normalize_forwarding_entry(f) for f in existing if isinstance(f, dict)]
        else:
            fwd_list: list[dict[str, Any]] = []
            legacy_url = str(data.get("forwarding_url", "")).strip()
            legacy_on = bool(data.get("forwarding_enabled"))
            legacy_headers = data.get("forwarding_headers")
            if legacy_url or legacy_on or (isinstance(legacy_headers, dict) and len(legacy_headers) > 0):
                fwd_list.append(
                    {
                        "id": str(uuid.uuid4()),
                        "name": "Weiterleitung",
                        "url": legacy_url,
                        "headers": dict(legacy_headers) if isinstance(legacy_headers, dict) else {},
                        "enabled": legacy_on and bool(legacy_url),
                    }
                )
            data["forwardings"] = fwd_list
        for k in ("forwarding_enabled", "forwarding_url", "forwarding_headers"):
            data.pop(k, None)

    def _normalize_forwarding_entry(self, raw: dict[str, Any]) -> dict[str, Any]:
        hid = str(raw.get("id") or "").strip() or str(uuid.uuid4())
        headers = raw.get("headers")
        headers_d = dict(headers) if isinstance(headers, dict) else {}

        if "incoming_headers_only" in raw:
            incoming_headers_only = bool(raw["incoming_headers_only"])
        else:
            leg_merge = raw.get("merge_incoming_headers")
            if leg_merge is False:
                incoming_headers_only = False
            elif len(headers_d) > 0:
                incoming_headers_only = False
            else:
                incoming_headers_only = True

        if "forward_body_from_source" in raw:
            forward_body_from_source = bool(raw["forward_body_from_source"])
        else:
            forward_body_from_source = True

        body_fields_raw = raw.get("body_fields")
        body_fields: list[dict[str, str]] = []
        if isinstance(body_fields_raw, list):
            for entry in body_fields_raw:
                if not isinstance(entry, dict):
                    continue
                param = str(entry.get("param", "")).strip()
                source = str(entry.get("source", "")).strip()
                if not param or not source:
                    continue
                if source not in FORWARDING_BODY_SOURCES:
                    continue
                body_fields.append({"param": param, "source": source})

        return {
            "id": hid,
            "name": str(raw.get("name", "")).strip() or "Weiterleitung",
            "url": str(raw.get("url", "")).strip(),
            "headers": headers_d,
            "enabled": bool(raw.get("enabled")),
            "incoming_headers_only": incoming_headers_only,
            "forward_body_from_source": forward_body_from_source,
            "body_fields": body_fields,
        }

    @staticmethod
    def _validate_forwarding_body_fields(body_fields: Any) -> list[dict[str, str]]:
        if body_fields is None:
            return []
        if not isinstance(body_fields, list):
            raise ValueError("body_fields muss eine Liste sein")
        normalized: list[dict[str, str]] = []
        for entry in body_fields:
            if not isinstance(entry, dict):
                continue
            param = str(entry.get("param", "")).strip()
            source = str(entry.get("source", "")).strip()
            if not param:
                continue
            if source not in FORWARDING_BODY_SOURCES:
                raise ValueError(f"Unbekannte Body-Quelle: {source}")
            normalized.append({"param": param, "source": source})
        return normalized

    def _purge_device_drafts(self) -> None:
        now = time.time()
        dead = [k for k, (ts, _) in self._device_drafts.items() if now - ts > DEVICE_DRAFT_TTL_SEC]
        for k in dead:
            del self._device_drafts[k]

    def _append_gps_line(self, item: dict[str, Any]) -> None:
        with self.gps_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    def _rebuild_statuses_from_gps(self) -> dict[str, dict[str, Any]]:
        statuses: dict[str, dict[str, Any]] = {}
        with self.gps_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                item = json.loads(line)
                device_id = str(item.get("device_id", "")).strip()
                if not device_id:
                    continue
                row = self._position_row_from_stored(item)
                if row is None:
                    continue
                st: dict[str, Any] = {
                    "last_seen": row.get("timestamp") or item.get("received_at"),
                    "latitude": row.get("latitude"),
                    "longitude": row.get("longitude"),
                    "accuracy": row.get("accuracy"),
                }
                for k in (
                    "device",
                    "battery",
                    "speed",
                    "direction",
                    "altitude",
                    "provider",
                    "activity",
                    "ingest_route",
                ):
                    if item.get(k) is not None:
                        st[k] = item[k]
                statuses[device_id] = st
        return statuses

    @staticmethod
    def _position_row_from_stored(item: dict[str, Any]) -> dict[str, Any] | None:
        """Eine Zeile für API/UI aus gespeichertem GPS-Datensatz (nur mit gültigen Koordinaten)."""
        try:
            lat = float(item.get("latitude"))
            lon = float(item.get("longitude"))
        except (TypeError, ValueError):
            return None
        base: dict[str, Any] = {
            "device_id": item.get("device_id"),
            "device_name": item.get("device_name"),
            "latitude": lat,
            "longitude": lon,
            "accuracy": item.get("accuracy"),
            "timestamp": item.get("timestamp") or item.get("received_at"),
        }
        for key in (
            "device",
            "battery",
            "speed",
            "direction",
            "altitude",
            "provider",
            "activity",
            "time",
            "ingest_route",
        ):
            if key in item and item[key] is not None:
                base[key] = item[key]
        return base

    def list_devices(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "id": device.get("id"),
                    "name": device.get("name"),
                    "created_at": device.get("created_at"),
                    "api_key": device.get("api_key"),
                    "map_color_index": int(device.get("map_color_index", 0)) % DEVICE_MAP_COLOR_COUNT,
                }
                for device in self.devices
            ]

    def create_device_draft(self) -> dict[str, Any]:
        with self._lock:
            self._purge_device_drafts()
            token = str(uuid.uuid4())
            key = secure_api_key()
            self._device_drafts[token] = (time.time(), key)
            return {"draft_token": token, "api_key": key}

    def _validate_new_device_api_key(self, key: str) -> str:
        k = str(key).strip()
        if not k:
            raise ValueError("API-Key darf nicht leer sein")
        if len(k) < 8:
            raise ValueError("API-Key muss mindestens 8 Zeichen haben")
        if len(k) > 128:
            raise ValueError("API-Key darf maximal 128 Zeichen lang sein")
        if any(c.isspace() for c in k):
            raise ValueError("API-Key darf keine Leerzeichen enthalten")
        for d in self.devices:
            if d.get("api_key") == k:
                raise ValueError("Dieser API-Key ist bereits vergeben")
        return k

    def commit_device_draft(
        self, draft_token: str, name: str, api_key_override: str | None = None
    ) -> dict[str, Any]:
        with self._lock:
            self._purge_device_drafts()
            entry = self._device_drafts.get(str(draft_token).strip())
            if not entry:
                raise ValueError("Entwurf abgelaufen oder ungültig. Bitte neu öffnen.")
            _, draft_key = entry
            cleaned_name = self._validate_device_name(name)
            override = str(api_key_override).strip() if api_key_override is not None else ""
            if override:
                final_key = self._validate_new_device_api_key(override)
            else:
                final_key = draft_key
            device = {
                "id": stable_device_id(cleaned_name, final_key),
                "name": cleaned_name,
                "api_key": final_key,
                "created_at": utc_now_iso(),
                "map_color_index": len(self.devices) % DEVICE_MAP_COLOR_COUNT,
            }
            self.devices.append(device)
            del self._device_drafts[str(draft_token).strip()]
            self._persist_devices()
            return dict(device)

    def _validate_device_api_key_for_update(self, key: str, device_id: str) -> str:
        k = str(key).strip()
        if len(k) < 8:
            raise ValueError("API-Key muss mindestens 8 Zeichen lang sein")
        if len(k) > 128:
            raise ValueError("API-Key darf maximal 128 Zeichen lang sein")
        if any(ch.isspace() for ch in k):
            raise ValueError("API-Key darf keine Leerzeichen enthalten")
        for d in self.devices:
            if d.get("id") == device_id:
                continue
            if d.get("api_key") == k:
                raise ValueError("Dieser API-Key ist bereits vergeben")
        return k

    def update_device(
        self,
        device_id: str,
        name: str,
        *,
        map_color_index: int | None = None,
        api_key: str | None = None,
    ) -> dict[str, Any] | None:
        with self._lock:
            cleaned_name = self._validate_device_name(name, exclude_id=device_id)
            cleaned_key = self._validate_device_api_key_for_update(api_key, device_id) if api_key is not None else None
            for device in self.devices:
                if device["id"] == device_id:
                    device["name"] = cleaned_name
                    if cleaned_key is not None:
                        device["api_key"] = cleaned_key
                    if map_color_index is not None:
                        device["map_color_index"] = map_color_index % DEVICE_MAP_COLOR_COUNT
                    elif device.get("map_color_index") is None:
                        device["map_color_index"] = 0
                    self._persist_devices()
                    return dict(device)
            return None

    def _validate_device_name(self, name: str, exclude_id: str | None = None) -> str:
        cleaned_name = str(name).strip()
        if not cleaned_name:
            raise ValueError("Name ist erforderlich")
        if len(cleaned_name) > 80:
            raise ValueError("Name darf maximal 80 Zeichen lang sein")
        for device in self.devices:
            if exclude_id and device.get("id") == exclude_id:
                continue
            if str(device.get("name", "")).strip().lower() == cleaned_name.lower():
                raise ValueError("Gerätename existiert bereits")
        return cleaned_name

    def delete_device(self, device_id: str) -> bool:
        with self._lock:
            before = len(self.devices)
            self.devices = [d for d in self.devices if d["id"] != device_id]
            changed = len(self.devices) != before
            if changed:
                if device_id in self.device_statuses:
                    del self.device_statuses[device_id]
                self._persist_devices()
                self._persist_statuses()
            return changed

    def rotate_device_key(self, device_id: str) -> dict[str, Any] | None:
        with self._lock:
            for device in self.devices:
                if device["id"] == device_id:
                    new_key = secure_api_key()
                    device["api_key"] = new_key
                    self._persist_devices()
                    return {
                        "id": device["id"],
                        "name": device["name"],
                        "api_key": new_key,
                    }
            return None

    def get_device_by_key(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            for device in self.devices:
                if device["api_key"] == key:
                    return dict(device)
            return None

    def get_settings(self) -> dict[str, Any]:
        with self._lock:
            return dict(self.settings)

    def get_runtime_stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "device_count": len(self.devices),
                "pending_nas_count": len(self.pending_nas),
                "stored_status_count": len(self.device_statuses),
                "last_nas_run_at": self.last_nas_run_at,
                "last_nas_saved_count": self.last_nas_saved_count,
                "last_nas_error": self.last_nas_error,
            }

    def append_forwarding_error(self, message: str) -> None:
        with self._lock:
            entry = {
                "time": utc_now_iso(),
                "message": str(message).strip(),
            }
            with self.forward_log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def get_forwarding_errors(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            if not self.forward_log_path.exists():
                return []
            items: list[dict[str, Any]] = []
            with self.forward_log_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        items.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
            if limit < 1:
                return []
            return items[-limit:]

    def clear_forwarding_errors(self) -> None:
        with self._lock:
            if self.forward_log_path.exists():
                self.forward_log_path.unlink()

    def mark_nas_run(self, saved_count: int, error: str | None = None) -> None:
        with self._lock:
            self.last_nas_run_at = utc_now_iso()
            self.last_nas_saved_count = int(saved_count)
            self.last_nas_error = str(error).strip() if error else None

    def update_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if "nas_interval_seconds" in payload:
                try:
                    self.settings["nas_interval_seconds"] = max(5, int(payload["nas_interval_seconds"]))
                except (TypeError, ValueError):
                    self.settings["nas_interval_seconds"] = DEFAULT_SETTINGS["nas_interval_seconds"]

            if "nas_path" in payload:
                nas_path = str(payload["nas_path"]).strip()
                err_key = validate_nas_path_string_for_settings(nas_path)
                if err_key:
                    raise ConfigFieldError(err_key)
                self.settings["nas_path"] = nas_path

            if "theme" in payload:
                theme = str(payload["theme"]).strip()
                self.settings["theme"] = theme or DEFAULT_SETTINGS["theme"]
            self._persist_settings()
            return dict(self.settings)

    def list_forwardings(self) -> list[dict[str, Any]]:
        with self._lock:
            raw = self.settings.get("forwardings")
            if not isinstance(raw, list):
                return []
            return [dict(self._normalize_forwarding_entry(x)) for x in raw if isinstance(x, dict)]

    def create_forwarding(
        self,
        name: str,
        url: str,
        headers: dict[str, Any],
        enabled: bool,
        *,
        incoming_headers_only: bool = True,
        forward_body_from_source: bool = True,
        body_fields: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            u = str(url).strip()
            if not u:
                raise ValueError("URL ist erforderlich")
            if not is_http_url(u):
                raise ValueError("URL muss mit http:// oder https:// beginnen")
            n = str(name).strip() or "Weiterleitung"
            h = dict(headers) if isinstance(headers, dict) else {}
            normalized_body_fields = self._validate_forwarding_body_fields(body_fields)
            if not bool(forward_body_from_source) and len(normalized_body_fields) == 0:
                raise ValueError("Body-Konfiguration erforderlich, wenn Body-Übernahme deaktiviert ist")
            entry = {
                "id": str(uuid.uuid4()),
                "name": n,
                "url": u,
                "headers": h,
                "enabled": bool(enabled),
                "incoming_headers_only": bool(incoming_headers_only),
                "forward_body_from_source": bool(forward_body_from_source),
                "body_fields": normalized_body_fields,
            }
            forwardings = list(self.settings.get("forwardings") or [])
            if not isinstance(forwardings, list):
                forwardings = []
            forwardings.append(entry)
            self.settings["forwardings"] = forwardings
            self._persist_settings()
            return dict(self._normalize_forwarding_entry(entry))

    def update_forwarding(
        self,
        forward_id: str,
        name: str,
        url: str,
        headers: dict[str, Any],
        enabled: bool,
        *,
        incoming_headers_only: bool = True,
        forward_body_from_source: bool = True,
        body_fields: list[dict[str, str]] | None = None,
    ) -> dict[str, Any] | None:
        with self._lock:
            u = str(url).strip()
            if not u:
                raise ValueError("URL ist erforderlich")
            if not is_http_url(u):
                raise ValueError("URL muss mit http:// oder https:// beginnen")
            n = str(name).strip() or "Weiterleitung"
            h = dict(headers) if isinstance(headers, dict) else {}
            normalized_body_fields = self._validate_forwarding_body_fields(body_fields)
            if not bool(forward_body_from_source) and len(normalized_body_fields) == 0:
                raise ValueError("Body-Konfiguration erforderlich, wenn Body-Übernahme deaktiviert ist")
            forwardings = list(self.settings.get("forwardings") or [])
            if not isinstance(forwardings, list):
                return None
            for i, f in enumerate(forwardings):
                if isinstance(f, dict) and str(f.get("id")) == str(forward_id):
                    forwardings[i] = {
                        "id": str(forward_id),
                        "name": n,
                        "url": u,
                        "headers": h,
                        "enabled": bool(enabled),
                        "incoming_headers_only": bool(incoming_headers_only),
                        "forward_body_from_source": bool(forward_body_from_source),
                        "body_fields": normalized_body_fields,
                    }
                    self.settings["forwardings"] = forwardings
                    self._persist_settings()
                    return dict(self._normalize_forwarding_entry(forwardings[i]))
            return None

    def delete_forwarding(self, forward_id: str) -> bool:
        with self._lock:
            forwardings = list(self.settings.get("forwardings") or [])
            if not isinstance(forwardings, list):
                return False
            before = len(forwardings)
            forwardings = [f for f in forwardings if not (isinstance(f, dict) and str(f.get("id")) == str(forward_id))]
            if len(forwardings) == before:
                return False
            self.settings["forwardings"] = forwardings
            self._persist_settings()
            return True

    def set_forwarding_enabled(self, forward_id: str, enabled: bool) -> dict[str, Any] | None:
        with self._lock:
            forwardings = list(self.settings.get("forwardings") or [])
            if not isinstance(forwardings, list):
                return None
            for f in forwardings:
                if isinstance(f, dict) and str(f.get("id")) == str(forward_id):
                    f["enabled"] = bool(enabled)
                    self.settings["forwardings"] = forwardings
                    self._persist_settings()
                    return dict(self._normalize_forwarding_entry(f))
            return None

    def _read_export_meta(self) -> dict[str, Any]:
        raw = read_json(self.export_meta_path, {})
        if not isinstance(raw, dict):
            return {"device_last_export_at": {}}
        d = raw.get("device_last_export_at")
        if not isinstance(d, dict):
            d = {}
        cleaned = {str(k): str(v) for k, v in d.items() if k is not None}
        return {"device_last_export_at": cleaned}

    def _write_export_meta(self, meta: dict[str, Any]) -> None:
        write_json(self.export_meta_path, meta)

    @staticmethod
    def _restore_export_file(path: Path, existed_before: bool, original_size: int) -> None:
        if not path.exists():
            return
        if not existed_before:
            path.unlink(missing_ok=True)
            return
        with path.open("r+b") as handle:
            handle.truncate(original_size)

    def get_storage_overview(self, nas_path_override: str | None = None) -> dict[str, Any]:
        """Status für die UI: Pfadprüfung, Dateien, Zähler pending/gespeichert pro Gerät."""
        with self._lock:
            raw_path = str(
                nas_path_override if nas_path_override is not None else (self.settings.get("nas_path") or "")
            ).strip()
            pending_by_id: Counter[str] = Counter()
            for item in self.pending_nas:
                did = str(item.get("device_id", "")).strip()
                if did:
                    pending_by_id[did] += 1
            meta = self._read_export_meta()
            last_export_map: dict[str, str] = dict(meta.get("device_last_export_at") or {})

            devices_out: list[dict[str, Any]] = []
            path_error_key: str | None = None
            path_valid = False
            nas_root_resolved = ""

            if not raw_path:
                path_error_key = ERR_PATH_EMPTY
            else:
                try:
                    nas_root = Path(raw_path)
                except Exception:
                    path_error_key = "settings.storage.error.invalidPath"
                    nas_root = None
                else:
                    if not nas_root.is_absolute():
                        path_error_key = "settings.storage.error.pathNotAbsolute"
                    else:
                        v_err = validate_absolute_writable_directory(nas_root)
                        if v_err:
                            path_error_key = v_err
                        else:
                            path_valid = True
                            nas_root_resolved = str(nas_root.resolve())

            for device in self.devices:
                if not isinstance(device, dict):
                    continue
                did = str(device.get("id", "")).strip()
                name = str(device.get("name", "") or "device")
                if not did:
                    continue
                fname = device_ndjson_filename(name, did)
                file_path = ""
                stored_lines = 0
                file_exists = False
                file_status = "would_create"
                if path_valid and nas_root_resolved:
                    try:
                        p = Path(nas_root_resolved) / fname
                        file_path = str(p.resolve())
                        if p.exists() and p.is_file():
                            file_exists = True
                            file_status = "exists"
                            stored_lines = count_ndjson_lines(p)
                        elif p.exists() and not p.is_file():
                            file_status = "blocked"
                    except OSError:
                        file_status = "blocked"

                devices_out.append(
                    {
                        "device_id": did,
                        "device_name": name,
                        "ndjson_filename": fname,
                        "file_path": file_path,
                        "file_exists": file_exists,
                        "file_status": file_status,
                        "stored_line_count": stored_lines,
                        "pending_unsaved_count": int(pending_by_id.get(did, 0)),
                        "last_export_at": last_export_map.get(did),
                    }
                )

            # Pending für unbekannte Geräte-IDs (z. B. nach Löschen)
            known_ids = {str(d.get("id", "")).strip() for d in self.devices if isinstance(d, dict)}
            for did, cnt in pending_by_id.items():
                if did in known_ids or cnt <= 0:
                    continue
                fname = device_ndjson_filename("device", did)
                file_path = ""
                stored_lines = 0
                file_exists = False
                file_status = "would_create"
                if path_valid and nas_root_resolved:
                    try:
                        p = Path(nas_root_resolved) / fname
                        file_path = str(p.resolve())
                        if p.exists() and p.is_file():
                            file_exists = True
                            file_status = "exists"
                            stored_lines = count_ndjson_lines(p)
                    except OSError:
                        file_status = "blocked"
                devices_out.append(
                    {
                        "device_id": did,
                        "device_name": did,
                        "ndjson_filename": fname,
                        "file_path": file_path,
                        "file_exists": file_exists,
                        "file_status": file_status,
                        "stored_line_count": stored_lines,
                        "pending_unsaved_count": int(cnt),
                        "last_export_at": last_export_map.get(did),
                    }
                )

            return {
                "nas_path_effective": raw_path,
                "nas_path_resolved": nas_root_resolved,
                "path_valid": path_valid,
                "path_error_key": path_error_key,
                "devices": devices_out,
            }

    def store_gps_request(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self._append_gps_line(payload)
            self.pending_nas.append(payload)
            device_id = str(payload.get("device_id", "")).strip()
            if device_id:
                st: dict[str, Any] = {
                    "last_seen": payload.get("timestamp") or payload.get("received_at"),
                    "latitude": payload.get("latitude"),
                    "longitude": payload.get("longitude"),
                    "accuracy": payload.get("accuracy"),
                }
                for k in (
                    "device",
                    "battery",
                    "speed",
                    "direction",
                    "altitude",
                    "provider",
                    "activity",
                    "ingest_route",
                ):
                    if payload.get(k) is not None:
                        st[k] = payload[k]
                self.device_statuses[device_id] = st
            self._persist_pending()
            self._persist_statuses()

    def flush_pending_to_nas(self) -> dict[str, Any]:
        with self._lock:
            pending = list(self.pending_nas)
            if not pending:
                self.mark_nas_run(saved_count=0, error=None)
                return {"ok": True, "saved_count": 0, "by_device": {}, "nas_path_resolved": ""}

            raw_path = str(self.settings.get("nas_path") or "").strip()
            if not raw_path:
                self.mark_nas_run(0, error=ERR_PATH_EMPTY)
                return {"ok": False, "saved_count": 0, "error_key": ERR_PATH_EMPTY, "by_device": {}}

            try:
                nas_root = Path(raw_path)
            except Exception:
                self.mark_nas_run(0, error="settings.storage.error.invalidPath")
                return {
                    "ok": False,
                    "saved_count": 0,
                    "error_key": "settings.storage.error.invalidPath",
                    "by_device": {},
                }

            v_err = validate_absolute_writable_directory(nas_root)
            if v_err:
                self.mark_nas_run(0, error=v_err)
                return {"ok": False, "saved_count": 0, "error_key": v_err, "by_device": {}}

            valid_pending = [i for i in pending if str(i.get("device_id", "")).strip()]
            invalid_pending = [i for i in pending if not str(i.get("device_id", "")).strip()]

            if not valid_pending:
                self.pending_nas = invalid_pending
                self._persist_pending()
                self.mark_nas_run(0, error=None)
                return {"ok": True, "saved_count": 0, "by_device": {}, "nas_path_resolved": str(nas_root.resolve())}

            groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for item in valid_pending:
                did = str(item.get("device_id", "")).strip()
                groups[did].append(item)

            lines_by_path: dict[Path, str] = {}
            by_device_counts: dict[str, int] = {}
            for did, items in groups.items():
                name = str(items[0].get("device_name") or "device")
                fname = device_ndjson_filename(name, did)
                path = nas_root / fname
                try:
                    if path.resolve().parent != nas_root.resolve():
                        self.mark_nas_run(0, error="settings.storage.error.invalidPath")
                        return {
                            "ok": False,
                            "saved_count": 0,
                            "error_key": "settings.storage.error.invalidPath",
                            "by_device": {},
                        }
                except Exception:
                    self.mark_nas_run(0, error="settings.storage.error.invalidPath")
                    return {
                        "ok": False,
                        "saved_count": 0,
                        "error_key": "settings.storage.error.invalidPath",
                        "by_device": {},
                    }
                blob = "".join(export_line_for_item(it) for it in items)
                lines_by_path[path] = lines_by_path.get(path, "") + blob
                by_device_counts[did] = len(items)

            snapshots: dict[Path, tuple[bool, int]] = {}
            for path in lines_by_path:
                existed = path.exists()
                size = path.stat().st_size if existed else 0
                snapshots[path] = (existed, size)

            try:
                for path, blob in lines_by_path.items():
                    with path.open("a", encoding="utf-8") as handle:
                        handle.write(blob)
            except OSError as exc:
                for path, (existed, orig_size) in snapshots.items():
                    self._restore_export_file(path, existed, orig_size)
                err_key = ERR_WRITE_FAILED
                if exc.errno in (errno.EACCES, errno.EPERM):
                    err_key = "settings.storage.error.permissionDenied"
                elif exc.errno == errno.ENOSPC:
                    err_key = "settings.storage.error.noSpace"
                self.mark_nas_run(0, error=err_key)
                return {"ok": False, "saved_count": 0, "error_key": err_key, "by_device": {}}

            self.pending_nas = invalid_pending
            self._persist_pending()

            meta = self._read_export_meta()
            inner = dict(meta.get("device_last_export_at") or {})
            now = utc_now_iso()
            for did in groups:
                inner[did] = now
            meta["device_last_export_at"] = inner
            self._write_export_meta(meta)

            total_written = sum(by_device_counts.values())
            self.mark_nas_run(total_written, error=None)
            return {
                "ok": True,
                "saved_count": total_written,
                "by_device": by_device_counts,
                "nas_path_resolved": str(nas_root.resolve()),
            }

    def query_positions(
        self,
        device_names: list[str] | None,
        ts_from: str | None,
        ts_to: str | None,
        *,
        limit: int = 500,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], bool]:
        if not self.gps_path.exists():
            return [], False

        def parse_time_utc(value: Any) -> datetime | None:
            if not value:
                return None
            try:
                parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
            except ValueError:
                return None
            if parsed.tzinfo is None:
                # Legacy ohne Offset als UTC interpretieren.
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)

        left = parse_time_utc(ts_from)
        right = parse_time_utc(ts_to)
        normalized_device_names: set[str] | None = None
        if isinstance(device_names, list) and len(device_names) > 0:
            normalized_device_names = {str(name).strip().lower() for name in device_names if str(name).strip()}
            if not normalized_device_names:
                normalized_device_names = None
        safe_limit = max(1, min(5000, int(limit)))
        safe_offset = max(0, int(offset))

        rows: list[dict[str, Any]] = []
        skipped = 0
        has_more = False
        skipped_invalid_timestamp = 0
        with self.gps_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if normalized_device_names is not None:
                    item_device_name = str(item.get("device_name", "")).strip().lower()
                    if item_device_name not in normalized_device_names:
                        continue
                item_time = parse_time_utc(item.get("timestamp")) or parse_time_utc(item.get("received_at"))
                if (left or right) and item_time is None:
                    skipped_invalid_timestamp += 1
                    continue
                if left and item_time and item_time < left:
                    continue
                if right and item_time and item_time > right:
                    continue
                row = self._position_row_from_stored(item)
                if row is not None:
                    if skipped < safe_offset:
                        skipped += 1
                        continue
                    if len(rows) >= safe_limit:
                        has_more = True
                        break
                    rows.append(row)
        if skipped_invalid_timestamp:
            print(
                f"[positions] skipped {skipped_invalid_timestamp} entries with invalid or missing timestamps "
                "for from/to filtering"
            )
        return rows, has_more

    def get_device_statuses(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {key: dict(value) for key, value in self.device_statuses.items()}

    def get_recent_gps_requests(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            if not self.gps_path.exists():
                return []
            rows: list[dict[str, Any]] = []
            with self.gps_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    pr = self._position_row_from_stored(item)
                    if pr is None:
                        continue
                    out = dict(pr)
                    out["received_at"] = item.get("received_at")
                    rows.append(out)
            if limit < 1:
                return []
            return rows[-limit:]

    def get_latest_gps_requests_by_device(self) -> dict[str, dict[str, Any]]:
        """Letzten gespeicherten GPS-Request je Gerät (inkl. raw_body/headers)."""
        with self._lock:
            if not self.gps_path.exists():
                return {}
            latest: dict[str, dict[str, Any]] = {}
            with self.gps_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    device_id = str(item.get("device_id", "")).strip()
                    if not device_id:
                        continue
                    if self._position_row_from_stored(item) is None:
                        continue
                    latest[device_id] = item
            return latest

