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

from .locale_bundle import format_inactivity_duration, normalize_ui_language, translate
from .gps_storage import (
    ERR_INVALID_PATH,
    ERR_PATH_EMPTY,
    ERR_STORAGE_DISABLED,
    ERR_WRITE_FAILED,
    compute_interval_seconds,
    count_ndjson_lines,
    device_ndjson_filename,
    export_line_for_item,
    validate_absolute_writable_directory,
    validate_nas_path_string_for_settings,
)
from .utils import ensure_dir, http_post_json, read_json, secure_api_key, stable_device_id, utc_now_iso, write_json

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
    "nas_storage_enabled": False,
    "nas_interval_value": 1,
    "nas_interval_unit": "hours",
    "nas_interval_seconds": 3600,
    "nas_path": "",
    "forwardings": [],
    "telegram_webhook_url": "",
    "theme": "light",
    "language": "de",
    "inactivity_notification_enabled": False,
    "inactivity_threshold_value": 5,
    "inactivity_threshold_unit": "minutes",
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
        self.ingest_seq_path = self.data_dir / "ingest_seq_next.json"
        self.status_path = self.data_dir / "device_statuses.json"
        self.forward_log_path = self.data_dir / "forwarding_errors.log"
        self.export_meta_path = self.data_dir / "nas_export_meta.json"
        self.inactivity_notify_state_path = self.data_dir / "device_inactivity_notify_state.json"

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
        self._device_inactivity_warned: dict[str, bool] = self._load_inactivity_notify_state_locked()
        self._inactivity_runtime_block: dict[str, Any] | None = None

        self._migrate_settings_forwardings()
        self._migrate_devices_map_color()
        self._migrate_legacy_nas_path_default()
        self._migrate_nas_storage_interval_and_flags()
        self._migrate_gps_ingest_seq_and_pending_queue()
        self._persist_devices()
        self._persist_settings()
        self._persist_pending()
        self._persist_statuses()

    def _load_inactivity_notify_state_locked(self) -> dict[str, bool]:
        raw = read_json(self.inactivity_notify_state_path, {})
        warned = raw.get("warn_sent")
        if not isinstance(warned, dict):
            return {}
        out: dict[str, bool] = {}
        for k, v in warned.items():
            key = str(k).strip()
            if key:
                out[key] = bool(v)
        return out

    def _persist_inactivity_notify_state_locked(self) -> None:
        write_json(
            self.inactivity_notify_state_path,
            {"warn_sent": {k: bool(v) for k, v in self._device_inactivity_warned.items()}},
        )

    def _prune_inactivity_flags_for_deleted_devices_locked(self) -> None:
        known = {str(d.get("id", "")).strip() for d in self.devices if isinstance(d, dict)}
        stale_keys = [k for k in self._device_inactivity_warned if k not in known]
        if stale_keys:
            for k in stale_keys:
                del self._device_inactivity_warned[k]
            self._persist_inactivity_notify_state_locked()

    @staticmethod
    def _parse_status_time_utc(value: Any) -> datetime | None:
        if value is None or str(value).strip() == "":
            return None
        try:
            parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def tick_device_inactivity_notifications(self) -> None:
        """Wird etwa alle 60s vom Hintergrund-Thread aufgerufen."""
        now = datetime.now(timezone.utc)

        def threshold_seconds(settings_copy: dict[str, Any]) -> tuple[int, int, str]:
            try:
                th_val = int(settings_copy.get("inactivity_threshold_value", 5))
            except (TypeError, ValueError):
                th_val = 5
            th_val = max(1, min(th_val, 525600))
            unit = str(settings_copy.get("inactivity_threshold_unit") or "minutes").strip().lower()
            if unit not in ("minutes", "hours"):
                unit = "minutes"
            sec = th_val * 3600 if unit == "hours" else th_val * 60
            sec = max(60, sec)
            return sec, th_val, unit

        with self._lock:
            self._prune_inactivity_flags_for_deleted_devices_locked()
            settings_copy = dict(self.settings)
            enabled = bool(settings_copy.get("inactivity_notification_enabled"))
            webhook = str(settings_copy.get("telegram_webhook_url") or "").strip()
            if not enabled:
                self._inactivity_runtime_block = None
                return
            threshold_sec, th_numeric, unit = threshold_seconds(settings_copy)
            lang = normalize_ui_language(str(settings_copy.get("language") or ""))
            duration_label = format_inactivity_duration(lang, th_numeric, unit)
            devices = [
                {"id": str(d.get("id", "")).strip(), "name": str(d.get("name", "") or d.get("id", "")).strip()}
                for d in self.devices
                if isinstance(d, dict) and str(d.get("id", "")).strip()
            ]
            statuses = {k: dict(v) for k, v in self.device_statuses.items()}
            warned_snapshot = dict(self._device_inactivity_warned)

        would_send_missing_hook = False
        to_warn: list[tuple[str, str, str]] = []
        to_clear: list[tuple[str, str, str]] = []

        for d in devices:
            did = d["id"]
            name = d["name"]
            if not name:
                name = did
            st = statuses.get(did) or {}
            last_raw = st.get("last_seen")
            t_seen = AppState._parse_status_time_utc(last_raw)
            if t_seen is None:
                continue
            age_sec = (now - t_seen).total_seconds()
            stale = age_sec >= threshold_sec
            is_warned = bool(warned_snapshot.get(did))

            if stale and not is_warned:
                if not webhook:
                    would_send_missing_hook = True
                    continue
                msg = translate(
                    lang,
                    "settings.notifications.inactivity.warningMessage",
                    {"deviceName": name, "duration": duration_label},
                )
                to_warn.append((did, name, msg))
            elif (not stale) and is_warned:
                if not webhook:
                    would_send_missing_hook = True
                    continue
                msg = translate(
                    lang,
                    "settings.notifications.inactivity.clearMessage",
                    {"deviceName": name},
                )
                to_clear.append((did, name, msg))

        block_rt: dict[str, Any] | None = None
        if would_send_missing_hook:
            log_line = translate(lang, "settings.notifications.inactivity.logSkippedNoWebhook")
            detail = translate(lang, "settings.notifications.inactivity.blockedNoWebhookStatus")
            block_rt = {"reason": "no_webhook", "detail": detail, "since": utc_now_iso()}
            print(f"[inactivity-monitor] {log_line}")

        new_warned = dict(warned_snapshot)

        for did, name, msg in to_warn:
            ok = self.send_telegram_webhook_notification(msg)
            if ok:
                new_warned[did] = True
                print(f"[inactivity-monitor] Warnung gesendet für Gerät {name} ({did})")
            else:
                print(f"[inactivity-monitor] Warnung für {name} ({did}) konnte nicht gesendet werden")

        for did, name, msg in to_clear:
            ok = self.send_telegram_webhook_notification(msg)
            if ok:
                new_warned.pop(did, None)
                print(f"[inactivity-monitor] Entwarnung gesendet für Gerät {name} ({did})")
            else:
                print(f"[inactivity-monitor] Entwarnung für {name} ({did}) konnte nicht gesendet werden")

        with self._lock:
            if not bool(self.settings.get("inactivity_notification_enabled")):
                self._inactivity_runtime_block = None
                return
            self._device_inactivity_warned = {k: v for k, v in new_warned.items() if v}
            self._persist_inactivity_notify_state_locked()
            self._inactivity_runtime_block = block_rt

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
                if device_id in self._device_inactivity_warned:
                    del self._device_inactivity_warned[device_id]
                    self._persist_inactivity_notify_state_locked()
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
            block = dict(self._inactivity_runtime_block) if self._inactivity_runtime_block else None
            return {
                "device_count": len(self.devices),
                "pending_nas_count": int(sum(self._count_unexported_gps_by_device_locked().values())),
                "stored_status_count": len(self.device_statuses),
                "last_nas_run_at": self.last_nas_run_at,
                "last_nas_saved_count": self.last_nas_saved_count,
                "last_nas_error": self.last_nas_error,
                "inactivity_notification_enabled": bool(self.settings.get("inactivity_notification_enabled")),
                "inactivity_notify_block": block,
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
            if "nas_storage_enabled" in payload:
                self.settings["nas_storage_enabled"] = bool(payload["nas_storage_enabled"])

            if "nas_interval_value" in payload or "nas_interval_unit" in payload:
                try:
                    iv = int(payload.get("nas_interval_value", self.settings.get("nas_interval_value", 1)))
                except (TypeError, ValueError):
                    iv = 1
                iv = max(1, iv)
                unit = str(
                    payload.get("nas_interval_unit") or self.settings.get("nas_interval_unit") or "hours"
                ).strip().lower()
                if unit not in ("hours", "days"):
                    raise ConfigFieldError("settings.storage.error.intervalUnitInvalid")
                self.settings["nas_interval_value"] = iv
                self.settings["nas_interval_unit"] = unit
                self.settings["nas_interval_seconds"] = compute_interval_seconds(iv, unit)

            if "nas_interval_seconds" in payload and "nas_interval_value" not in payload and "nas_interval_unit" not in payload:
                try:
                    sec = max(5, int(payload["nas_interval_seconds"]))
                except (TypeError, ValueError):
                    sec = int(DEFAULT_SETTINGS["nas_interval_seconds"])
                if sec >= 86400:
                    self.settings["nas_interval_unit"] = "days"
                    self.settings["nas_interval_value"] = max(1, sec // 86400)
                else:
                    self.settings["nas_interval_unit"] = "hours"
                    self.settings["nas_interval_value"] = max(1, (sec + 3599) // 3600)
                self.settings["nas_interval_seconds"] = compute_interval_seconds(
                    int(self.settings["nas_interval_value"]), str(self.settings["nas_interval_unit"])
                )

            if "nas_path" in payload:
                self.settings["nas_path"] = str(payload["nas_path"]).strip()

            if "theme" in payload:
                theme = str(payload["theme"]).strip()
                self.settings["theme"] = theme or DEFAULT_SETTINGS["theme"]

            if "language" in payload:
                lang = str(payload.get("language") or "").strip().lower()
                if lang not in ("de", "en"):
                    raise ConfigFieldError("settings.system.error.languageInvalid")
                self.settings["language"] = lang

            if "inactivity_notification_enabled" in payload:
                self.settings["inactivity_notification_enabled"] = bool(payload["inactivity_notification_enabled"])

            if "inactivity_threshold_value" in payload or "inactivity_threshold_unit" in payload:
                try:
                    iv = int(
                        payload.get("inactivity_threshold_value", self.settings.get("inactivity_threshold_value", 5))
                    )
                except (TypeError, ValueError):
                    iv = 5
                iv = max(1, min(iv, 525600))
                unit = str(
                    payload.get("inactivity_threshold_unit")
                    or self.settings.get("inactivity_threshold_unit")
                    or "minutes"
                ).strip().lower()
                if unit not in ("minutes", "hours"):
                    raise ConfigFieldError("settings.notifications.inactivity.error.unitInvalid")
                self.settings["inactivity_threshold_value"] = iv
                self.settings["inactivity_threshold_unit"] = unit

            if "telegram_webhook_url" in payload:
                raw_tw = str(payload.get("telegram_webhook_url") or "").strip()
                if raw_tw and not is_http_url(raw_tw):
                    raise ConfigFieldError("settings.notifications.error.webhookUrlInvalid")
                self.settings["telegram_webhook_url"] = raw_tw

            if bool(self.settings.get("nas_storage_enabled")):
                self._validate_nas_path_when_storage_enabled(str(self.settings.get("nas_path") or ""))

            self._persist_settings()
            return dict(self.settings)

    def send_telegram_webhook_notification(self, message: str) -> bool:
        """Sendet ausschließlich über die persistierte `telegram_webhook_url` (JSON-Body `{\"message\": ...}`)."""
        text = str(message or "").strip()
        if not text:
            return False
        with self._lock:
            url = str(self.settings.get("telegram_webhook_url") or "").strip()
        if not url:
            return False
        ok, code, detail = http_post_json(url, {"message": text}, timeout=12.0)
        if not ok:
            hint = f"Telegram-Webhook: HTTP {code}" if code else f"Telegram-Webhook: {detail or 'Fehler'}"
            self.append_forwarding_error(hint.strip()[:500])
        return ok

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

    def _migrate_nas_storage_interval_and_flags(self) -> None:
        """Intervall als Wert+Einheit; aktiviert-Flag; aus legacy nas_interval_seconds ableiten."""
        changed = False
        s = self.settings
        if "nas_storage_enabled" not in s:
            s["nas_storage_enabled"] = False
            changed = True
        if "nas_interval_unit" not in s or "nas_interval_value" not in s:
            try:
                old_sec = max(5, int(s.get("nas_interval_seconds", 60)))
            except (TypeError, ValueError):
                old_sec = 3600
            if old_sec >= 86400:
                s["nas_interval_unit"] = "days"
                s["nas_interval_value"] = max(1, old_sec // 86400)
            else:
                s["nas_interval_unit"] = "hours"
                s["nas_interval_value"] = max(1, (old_sec + 3599) // 3600)
            changed = True
        try:
            iv = max(1, int(s.get("nas_interval_value", 1)))
        except (TypeError, ValueError):
            iv = 1
        unit = str(s.get("nas_interval_unit") or "hours").strip().lower()
        if unit not in ("hours", "days"):
            unit = "hours"
            changed = True
        s["nas_interval_value"] = iv
        s["nas_interval_unit"] = unit
        new_sec = compute_interval_seconds(iv, unit)
        if int(s.get("nas_interval_seconds", 0)) != new_sec:
            s["nas_interval_seconds"] = new_sec
            changed = True
        if changed:
            self._persist_settings()

    def _validate_nas_path_when_storage_enabled(self, nas_path: str) -> None:
        text = str(nas_path or "").strip()
        if not text:
            raise ConfigFieldError(ERR_PATH_EMPTY)
        err = validate_nas_path_string_for_settings(text)
        if err:
            raise ConfigFieldError(err)
        try:
            p = Path(text)
        except Exception:
            raise ConfigFieldError(ERR_INVALID_PATH)
        v_err = validate_absolute_writable_directory(p)
        if v_err:
            raise ConfigFieldError(v_err)

    def _migrate_gps_ingest_seq_and_pending_queue(self) -> None:
        """ingest_seq in gps.ndjson ergänzen; nächste Seq-Nummer reparieren; pending_nas entfällt als Export-Queue."""
        with self._lock:
            self._backfill_gps_ingest_seq_locked()
            self._repair_ingest_seq_next_locked()
            self.pending_nas = []
            self._persist_pending()

    def _gps_max_ingest_seq_locked(self) -> int:
        m = 0
        if not self.gps_path.exists():
            return m
        try:
            with self.gps_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(item, dict):
                        continue
                    raw = item.get("ingest_seq")
                    if raw is None:
                        continue
                    try:
                        m = max(m, int(raw))
                    except (TypeError, ValueError):
                        continue
        except OSError:
            return m
        return m

    def _backfill_gps_ingest_seq_locked(self) -> None:
        if not self.gps_path.exists():
            return
        needs = False
        try:
            with self.gps_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(item, dict) and item.get("ingest_seq") is None:
                        needs = True
                        break
        except OSError:
            return
        if not needs:
            return
        items: list[dict[str, Any]] = []
        try:
            with self.gps_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(obj, dict):
                        items.append(obj)
        except OSError:
            return
        n = 1
        for obj in items:
            obj["ingest_seq"] = n
            n += 1
        tmp = self.gps_path.with_suffix(".ndjson.tmp")
        try:
            with tmp.open("w", encoding="utf-8") as w:
                for obj in items:
                    w.write(json.dumps(obj, ensure_ascii=False) + "\n")
            tmp.replace(self.gps_path)
        except OSError:
            tmp.unlink(missing_ok=True)
            return
        write_json(self.ingest_seq_path, {"next": n})

    def _repair_ingest_seq_next_locked(self) -> None:
        max_seq = self._gps_max_ingest_seq_locked()
        raw = read_json(self.ingest_seq_path, {})
        cur_next = 1
        if isinstance(raw, dict) and raw.get("next") is not None:
            try:
                cur_next = max(1, int(raw["next"]))
            except (TypeError, ValueError):
                cur_next = 1
        new_next = max(cur_next, max_seq + 1)
        if new_next != cur_next or not self.ingest_seq_path.exists():
            write_json(self.ingest_seq_path, {"next": new_next})

    def _allocate_ingest_seq_locked(self) -> int:
        if not self.ingest_seq_path.exists():
            self._repair_ingest_seq_next_locked()
        raw = read_json(self.ingest_seq_path, {"next": 1})
        n = 1
        if isinstance(raw, dict) and raw.get("next") is not None:
            try:
                n = max(1, int(raw["next"]))
            except (TypeError, ValueError):
                n = 1
        write_json(self.ingest_seq_path, {"next": n + 1})
        return n

    def _max_exported_ingest_by_device_locked(self) -> dict[str, int]:
        meta = self._read_export_meta()
        raw = meta.get("device_max_exported_ingest_seq")
        out: dict[str, int] = {}
        if isinstance(raw, dict):
            for k, v in raw.items():
                try:
                    out[str(k)] = int(v)
                except (TypeError, ValueError):
                    pass
        return out

    def _count_unexported_gps_by_device_locked(self) -> Counter[str]:
        wm = self._max_exported_ingest_by_device_locked()
        c: Counter[str] = Counter()
        if not self.gps_path.exists():
            return c
        try:
            with self.gps_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(item, dict):
                        continue
                    did = str(item.get("device_id", "")).strip()
                    if not did:
                        continue
                    if self._position_row_from_stored(item) is None:
                        continue
                    try:
                        seq = int(item.get("ingest_seq"))
                    except (TypeError, ValueError):
                        continue
                    if seq > int(wm.get(did, 0)):
                        c[did] += 1
        except OSError:
            return c
        return c

    def _unexported_gps_groups_locked(self) -> dict[str, list[dict[str, Any]]]:
        wm = self._max_exported_ingest_by_device_locked()
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        if not self.gps_path.exists():
            return groups
        try:
            with self.gps_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(item, dict):
                        continue
                    did = str(item.get("device_id", "")).strip()
                    if not did:
                        continue
                    if self._position_row_from_stored(item) is None:
                        continue
                    try:
                        seq = int(item.get("ingest_seq"))
                    except (TypeError, ValueError):
                        continue
                    if seq > int(wm.get(did, 0)):
                        groups[did].append(item)
        except OSError:
            return groups
        for did in groups:
            groups[did].sort(key=lambda it: int(it.get("ingest_seq") or 0))
        return groups

    def _device_registry_name_locked(self, did: str) -> str | None:
        for d in self.devices:
            if isinstance(d, dict) and str(d.get("id", "")).strip() == did:
                n = str(d.get("name", "") or "").strip()
                return n or None
        return None

    def _read_export_meta(self) -> dict[str, Any]:
        raw = read_json(self.export_meta_path, {})
        if not isinstance(raw, dict):
            raw = {}
        d = raw.get("device_last_export_at")
        if not isinstance(d, dict):
            d = {}
        cleaned_times = {str(k): str(v) for k, v in d.items() if k is not None}
        wx = raw.get("device_max_exported_ingest_seq")
        wmap: dict[str, int] = {}
        if isinstance(wx, dict):
            for k, v in wx.items():
                try:
                    wmap[str(k)] = int(v)
                except (TypeError, ValueError):
                    pass
        return {"device_last_export_at": cleaned_times, "device_max_exported_ingest_seq": wmap}

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

    def get_storage_overview(
        self,
        nas_path_override: str | None = None,
        *,
        nas_storage_enabled_override: bool | None = None,
    ) -> dict[str, Any]:
        """Status für die UI: Zähler immer; Pfad/Dateien nur bei aktivierter Speicherung und gesetztem Pfad."""
        with self._lock:
            raw_path = str(
                nas_path_override if nas_path_override is not None else (self.settings.get("nas_path") or "")
            ).strip()
            if nas_storage_enabled_override is not None:
                storage_on = bool(nas_storage_enabled_override)
            else:
                storage_on = bool(self.settings.get("nas_storage_enabled"))

            pending_by_id = self._count_unexported_gps_by_device_locked()
            meta = self._read_export_meta()
            last_export_map: dict[str, str] = dict(meta.get("device_last_export_at") or {})

            devices_out: list[dict[str, Any]] = []
            path_valid = False
            nas_root_resolved = ""

            if storage_on and raw_path:
                try:
                    nas_root = Path(raw_path)
                except Exception:
                    nas_root = None
                else:
                    if nas_root.is_absolute():
                        v_err = validate_absolute_writable_directory(nas_root)
                        if not v_err:
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
                "nas_storage_enabled": storage_on,
                "devices": devices_out,
            }

    def store_gps_request(self, payload: dict[str, Any]) -> None:
        with self._lock:
            payload = dict(payload)
            payload["ingest_seq"] = self._allocate_ingest_seq_locked()
            self._append_gps_line(payload)
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
            self._persist_statuses()

    def flush_pending_to_nas(self) -> dict[str, Any]:
        with self._lock:
            if not bool(self.settings.get("nas_storage_enabled")):
                return {
                    "ok": False,
                    "saved_count": 0,
                    "error_key": ERR_STORAGE_DISABLED,
                    "by_device": {},
                    "nas_path_resolved": "",
                }

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

            groups = self._unexported_gps_groups_locked()
            if not any(groups.values()):
                self.pending_nas = []
                self._persist_pending()
                self.mark_nas_run(saved_count=0, error=None)
                return {
                    "ok": True,
                    "saved_count": 0,
                    "by_device": {},
                    "nas_path_resolved": str(nas_root.resolve()),
                }

            lines_by_path: dict[Path, str] = {}
            by_device_counts: dict[str, int] = {}
            new_watermarks: dict[str, int] = {}

            for did, items in groups.items():
                if not items:
                    continue
                reg_name = self._device_registry_name_locked(did)
                name = reg_name or str(items[0].get("device_name") or "device")
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
                new_watermarks[did] = max(int(it.get("ingest_seq") or 0) for it in items)

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

            self.pending_nas = []
            self._persist_pending()

            meta = self._read_export_meta()
            inner = dict(meta.get("device_last_export_at") or {})
            wmap = dict(meta.get("device_max_exported_ingest_seq") or {})
            now = utc_now_iso()
            for did, max_seq in new_watermarks.items():
                inner[did] = now
                wmap[did] = max_seq
            meta["device_last_export_at"] = inner
            meta["device_max_exported_ingest_seq"] = wmap
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

