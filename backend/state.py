import json
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import parse as urlparse

from .utils import ensure_dir, read_json, secure_api_key, stable_device_id, utc_now_iso, write_json

DEVICE_DRAFT_TTL_SEC = 900

# Index 0..N-1 verweist auf Theme-Variablen --device-map-palette-{i} (Farben nur in theme.css).
DEVICE_MAP_COLOR_COUNT = 6
FORWARDING_BODY_SOURCES = {
    "latitude",
    "longitude",
    "device_name",
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
    "nas_path": "nas_storage",
    "forwardings": [],
    "theme": "light",
}


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
                self.settings["nas_path"] = nas_path or DEFAULT_SETTINGS["nas_path"]

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
                return {"saved_count": 0}

            nas_root = Path(self.settings["nas_path"])
            if not nas_root.is_absolute():
                nas_root = self.root / nas_root
            ensure_dir(nas_root)

            for item in pending:
                received = item.get("received_at", utc_now_iso())
                try:
                    parsed = datetime.fromisoformat(received.replace("Z", "+00:00"))
                except ValueError:
                    parsed = datetime.now(timezone.utc)
                date_part = parsed.strftime("%Y-%m-%d")
                device_name = item.get("device_name", "unknown").replace("/", "_")
                device_dir = nas_root / date_part / device_name
                ensure_dir(device_dir)
                target = device_dir / "gps.ndjson"
                with target.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(item, ensure_ascii=False) + "\n")

            self.pending_nas = []
            self._persist_pending()
            self.mark_nas_run(saved_count=len(pending), error=None)
            return {"saved_count": len(pending), "nas_path": str(nas_root)}

    def query_positions(self, device_id: str | None, ts_from: str | None, ts_to: str | None) -> list[dict[str, Any]]:
        if not self.gps_path.exists():
            return []

        def parse_time(value: str | None):
            if not value:
                return None
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None

        left = parse_time(ts_from)
        right = parse_time(ts_to)

        rows: list[dict[str, Any]] = []
        with self.gps_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                item = json.loads(line)
                if device_id and item.get("device_id") != device_id:
                    continue
                item_time = parse_time(item.get("timestamp")) or parse_time(item.get("received_at"))
                if left and item_time and item_time < left:
                    continue
                if right and item_time and item_time > right:
                    continue
                row = self._position_row_from_stored(item)
                if row is not None:
                    rows.append(row)
        return rows

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

