import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import parse as urlparse

from .utils import ensure_dir, read_json, secure_api_key, stable_device_id, utc_now_iso, write_json


DEFAULT_SETTINGS = {
    "nas_interval_seconds": 60,
    "nas_path": "nas_storage",
    "forwarding_enabled": False,
    "forwarding_url": "",
    "forwarding_headers": {},
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
                statuses[device_id] = {
                    "last_seen": item.get("timestamp") or item.get("received_at"),
                    "latitude": item.get("latitude"),
                    "longitude": item.get("longitude"),
                    "accuracy": item.get("accuracy"),
                }
        return statuses

    def list_devices(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "id": device.get("id"),
                    "name": device.get("name"),
                    "created_at": device.get("created_at"),
                }
                for device in self.devices
            ]

    def create_device(self, name: str) -> dict[str, Any]:
        with self._lock:
            cleaned_name = self._validate_device_name(name)
            key = secure_api_key()
            device = {
                "id": stable_device_id(cleaned_name, key),
                "name": cleaned_name,
                "api_key": key,
                "created_at": utc_now_iso(),
            }
            self.devices.append(device)
            self._persist_devices()
            return dict(device)

    def update_device(self, device_id: str, name: str) -> dict[str, Any] | None:
        with self._lock:
            cleaned_name = self._validate_device_name(name, exclude_id=device_id)
            for device in self.devices:
                if device["id"] == device_id:
                    device["name"] = cleaned_name
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

            if "forwarding_enabled" in payload:
                self.settings["forwarding_enabled"] = bool(payload["forwarding_enabled"])

            if "forwarding_url" in payload:
                forward_url = str(payload["forwarding_url"]).strip()
                if forward_url and not is_http_url(forward_url):
                    forward_url = ""
                self.settings["forwarding_url"] = forward_url

            if "forwarding_headers" in payload:
                headers = payload["forwarding_headers"]
                self.settings["forwarding_headers"] = headers if isinstance(headers, dict) else {}

            if "theme" in payload:
                theme = str(payload["theme"]).strip()
                self.settings["theme"] = theme or DEFAULT_SETTINGS["theme"]
            self._persist_settings()
            return dict(self.settings)

    def store_gps_request(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self._append_gps_line(payload)
            self.pending_nas.append(payload)
            device_id = str(payload.get("device_id", "")).strip()
            if device_id:
                self.device_statuses[device_id] = {
                    "last_seen": payload.get("timestamp") or payload.get("received_at"),
                    "latitude": payload.get("latitude"),
                    "longitude": payload.get("longitude"),
                    "accuracy": payload.get("accuracy"),
                }
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
                try:
                    lat = float(item.get("latitude"))
                    lon = float(item.get("longitude"))
                except (TypeError, ValueError):
                    continue
                item_time = parse_time(item.get("timestamp")) or parse_time(item.get("received_at"))
                if left and item_time and item_time < left:
                    continue
                if right and item_time and item_time > right:
                    continue
                rows.append(
                    {
                        "device_id": item.get("device_id"),
                        "device_name": item.get("device_name"),
                        "latitude": lat,
                        "longitude": lon,
                        "accuracy": item.get("accuracy"),
                        "timestamp": item.get("timestamp") or item.get("received_at"),
                    }
                )
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
                    rows.append(
                        {
                            "device_id": item.get("device_id"),
                            "device_name": item.get("device_name"),
                            "timestamp": item.get("timestamp") or item.get("received_at"),
                            "latitude": item.get("latitude"),
                            "longitude": item.get("longitude"),
                            "accuracy": item.get("accuracy"),
                        }
                    )
            if limit < 1:
                return []
            return rows[-limit:]

