import json
import socket
import queue
import threading
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import parse as urlparse
from urllib import error as urlerror
from urllib import request as urlrequest

from .openapi_spec import build_openapi_spec
from .state import AppState, ConfigFieldError
from .utils import utc_now_iso

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "static"
THEMES_DIR = ROOT / "themes"
state = AppState(ROOT)
forward_queue: queue.Queue[dict] = queue.Queue(maxsize=5000)
save_lock = threading.Lock()
sse_lock = threading.Lock()
sse_subscribers: list[queue.Queue] = []
STARTED_AT = time.time()
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}
INTERNAL_HEADER_BLOCKLIST = {
    "x-gpslogger-test",
}
INTERNAL_HEADER_PREFIX_BLOCKLIST = (
    "x-forwarded-",
    "forwarded",
    "x-real-ip",
    "x-proxy-",
)

RESTART_WEBHOOK_URL = "http://127.0.0.1:9000/"


def _fire_restart_webhook() -> None:
    try:
        req = urlrequest.Request(RESTART_WEBHOOK_URL, data=b"", method="POST")
        urlrequest.urlopen(req, timeout=5)
    except Exception as exc:
        print(f"[restart] webhook error: {exc}")


def schedule_restart_via_webhook() -> None:
    threading.Thread(target=_fire_restart_webhook, daemon=True).start()


def _sse_register() -> queue.Queue:
    q: queue.Queue[bytes] = queue.Queue(maxsize=64)
    with sse_lock:
        sse_subscribers.append(q)
    return q


def _sse_unregister(q: queue.Queue) -> None:
    with sse_lock:
        try:
            sse_subscribers.remove(q)
        except ValueError:
            pass


def broadcast_position_event(payload: dict) -> None:
    """Sendet ein SSE-Event an alle verbundenen Karten-Clients (JSON in data:)."""
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    line = b"data: " + raw + b"\n\n"
    with sse_lock:
        for q in list(sse_subscribers):
            try:
                q.put_nowait(line)
            except queue.Full:
                try:
                    q.get_nowait()
                except queue.Empty:
                    pass
                try:
                    q.put_nowait(line)
                except queue.Full:
                    pass


def json_response(handler: BaseHTTPRequestHandler, payload: dict, status=HTTPStatus.OK):
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


def parse_bearer_token(handler: BaseHTTPRequestHandler) -> str | None:
    auth_header = handler.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    return auth_header.removeprefix("Bearer ").strip()


def parse_iso_timestamp(value: str) -> str | None:
    text = value.strip()
    if not text:
        return None
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
        return text
    except ValueError:
        return None


def parse_query_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_device_filters(query: dict[str, list[str]]) -> list[str]:
    raw_values: list[str] = []
    for key in ("device", "devices"):
        raw_values.extend(query.get(key, []))
    parsed: list[str] = []
    for value in raw_values:
        for chunk in str(value).split(","):
            name = chunk.strip()
            if name:
                parsed.append(name)
    # Duplikate entfernen, Reihenfolge beibehalten.
    return list(dict.fromkeys(parsed))


def parse_coordinate(value: str, left: float, right: float) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed < left or parsed > right:
        return None
    return parsed


def parse_accuracy(value: str | None) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed < 0:
        return None
    return parsed


def optional_form_str(fields: dict, key: str) -> str | None:
    v = fields.get(key)
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def parse_optional_float_field(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_battery_value(value) -> float | str | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    text = str(value).strip()
    try:
        return float(text)
    except ValueError:
        return text


def sanitize_forward_headers(headers: dict) -> dict:
    cleaned: dict[str, str] = {}
    for key, value in headers.items():
        key_text = str(key).strip()
        value_text = str(value).strip()
        if not key_text or not value_text:
            continue
        if key_text.lower() in HOP_BY_HOP_HEADERS:
            continue
        cleaned[key_text] = value_text
    return cleaned


def select_replay_headers(headers: dict) -> dict:
    """Geräte-Header übernehmen, aber interne/proxy Header strikt entfernen."""
    cleaned = sanitize_forward_headers(headers or {})
    selected: dict[str, str] = {}
    for key, value in cleaned.items():
        lower_key = key.lower()
        if lower_key in INTERNAL_HEADER_BLOCKLIST:
            continue
        if any(lower_key.startswith(prefix) for prefix in INTERNAL_HEADER_PREFIX_BLOCKLIST):
            continue
        selected[key] = value
    return selected


def lookup_header_ci(headers: dict, names: tuple[str, ...]) -> str | None:
    lower_map = {str(k).lower(): v for k, v in headers.items()}
    for name in names:
        key = name.lower()
        if key in lower_map:
            val = lower_map[key]
            if val is None:
                return None
            text = str(val).strip()
            return text if text else None
    return None


def build_outgoing_forward_headers(fwd: dict, source_headers: dict) -> dict:
    source_headers = sanitize_forward_headers(source_headers or {})
    iho = fwd.get("incoming_headers_only")
    if iho is None:
        iho = True
    else:
        iho = bool(iho)
    if iho:
        return dict(source_headers)
    headers: dict[str, str] = {}
    ct = lookup_header_ci(source_headers, ("content-type",))
    if ct:
        headers["Content-Type"] = ct
    headers.update(sanitize_forward_headers(fwd.get("headers") or {}))
    return headers


def build_replay_request(method: str, headers: dict, raw_body: str, captured_at: str) -> dict:
    replay_headers = select_replay_headers(headers)
    content_type = lookup_header_ci(replay_headers, ("content-type",)) or "application/x-www-form-urlencoded"
    return {
        "method": str(method or "POST").upper(),
        "headers": replay_headers,
        "content_type": content_type,
        "body": str(raw_body or ""),
        "captured_at": str(captured_at or utc_now_iso()),
        "body_unchanged": True,
    }


def resolve_body_source_value(item: dict, source: str) -> str:
    source_key = str(source or "").strip()
    if source_key == "latitude":
        v = item.get("latitude")
    elif source_key == "longitude":
        v = item.get("longitude")
    elif source_key == "device_name":
        v = item.get("device_name")
    elif source_key == "request_device":
        v = item.get("request_device")
    elif source_key == "accuracy":
        v = item.get("accuracy")
    elif source_key == "battery":
        v = item.get("battery")
    elif source_key == "speed":
        v = item.get("speed")
    elif source_key == "direction":
        v = item.get("direction")
    elif source_key == "altitude":
        v = item.get("altitude")
    elif source_key == "provider":
        v = item.get("provider")
    elif source_key == "activity":
        v = item.get("activity")
    elif source_key == "timestamp":
        v = item.get("timestamp") or item.get("received_at")
    elif source_key == "device_id":
        v = item.get("device_id")
    else:
        v = None
    return "" if v is None else str(v)


def build_configured_forward_body(item: dict, body_fields: list[dict]) -> str:
    pairs: list[tuple[str, str]] = []
    for entry in body_fields:
        if not isinstance(entry, dict):
            continue
        param = str(entry.get("param", "")).strip()
        source = str(entry.get("source", "")).strip()
        if not param or not source:
            continue
        value = resolve_body_source_value(item, source)
        pairs.append((param, value))
    return urlparse.urlencode(pairs)


def build_test_forwarding_record(device: dict, status: dict) -> dict:
    timestamp = str(status.get("last_seen") or utc_now_iso())
    fields = {
        "latitude": status.get("latitude"),
        "longitude": status.get("longitude"),
        "accuracy": status.get("accuracy"),
        "timestamp": timestamp,
    }
    if status.get("battery") is not None:
        fields["battery"] = status.get("battery")
    if status.get("speed") is not None:
        fields["speed"] = status.get("speed")
    if status.get("direction") is not None:
        fields["direction"] = status.get("direction")
    if status.get("altitude") is not None:
        fields["altitude"] = status.get("altitude")
    if status.get("provider") is not None:
        fields["provider"] = status.get("provider")
    if status.get("activity") is not None:
        fields["activity"] = status.get("activity")
    if status.get("device") is not None:
        fields["device"] = status.get("device")
    raw_body = urlparse.urlencode({k: "" if v is None else str(v) for k, v in fields.items()})
    replay = build_replay_request(
        "POST",
        {"Content-Type": "application/x-www-form-urlencoded"},
        raw_body,
        utc_now_iso(),
    )
    return {
        "device_id": device.get("id"),
        "device_name": device.get("name"),
        "latitude": status.get("latitude"),
        "longitude": status.get("longitude"),
        "accuracy": status.get("accuracy"),
        "timestamp": timestamp,
        "ingest_route": "/api/forwarding-test",
        "headers": {
            "Content-Type": "application/x-www-form-urlencoded",
        },
        "raw_body": raw_body,
        "replay_request": replay,
        "received_at": utc_now_iso(),
    }


def is_http_url(value: str) -> bool:
    try:
        parsed = urlparse.urlparse(value)
    except Exception:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def forward_record_to_forwardings(item: dict, forwardings: list[dict], *, allow_disabled: bool = False) -> dict:
    stats = {"attempted": 0, "delivered": 0, "failed": 0, "attempts": []}
    replay_request = item.get("replay_request") if isinstance(item.get("replay_request"), dict) else None
    raw_in_headers = item.get("headers") or {}
    raw_body_text = item.get("raw_body", "") or ""
    replay_available = replay_request is not None
    source_headers = replay_request.get("headers", {}) if replay_available else raw_in_headers
    source_body_text = replay_request.get("body", "") if replay_available else raw_body_text
    source_method = replay_request.get("method", "POST") if replay_available else "POST"
    source_content_type = replay_request.get("content_type", "") if replay_available else lookup_header_ci(raw_in_headers, ("content-type",))
    original_request_device = str(item.get("request_device") or "")
    device_display_name = str(item.get("device_name") or "")
    for fwd in forwardings:
        if not isinstance(fwd, dict):
            continue
        if not allow_disabled and not fwd.get("enabled"):
            continue
        url = str(fwd.get("url", "")).strip()
        if not url or not is_http_url(url):
            continue
        stats["attempted"] += 1
        attempt_detail = {
            "forwarding_id": str(fwd.get("id", "")),
            "forwarding_name": str(fwd.get("name", "")).strip() or "Weiterleitung",
            "target_url": url,
            "stage": "before_request",
            "request_sent": False,
            "ok": False,
            "http_status": None,
            "error": "",
            "exception_type": "",
            "response_excerpt": "",
            "replay_available": replay_available,
            "replay_used": replay_available,
            "request_method": str(source_method or "POST").upper(),
            "request_content_type": str(source_content_type or ""),
            "body_unchanged": bool(replay_request.get("body_unchanged", False)) if replay_available else False,
            "replay_reason": "captured_from_original_request" if replay_available else "missing_replay_request_fallback_to_legacy_fields",
            "body_source": "replay_original" if replay_available else "legacy_fallback",
            "header_source": "incoming" if bool(fwd.get("incoming_headers_only", True)) else "builder",
            "original_request_device": original_request_device,
            "device_display_name": device_display_name,
            "sent_device_value": "",
            "final_request_method": "",
            "final_request_url": "",
            "final_request_headers": {},
            "final_request_body_text": "",
            "response_status": None,
            "response_body_text": "",
        }
        stats["attempts"].append(attempt_detail)
        try:
            headers = build_outgoing_forward_headers(fwd, source_headers)
            if fwd.get("forward_body_from_source", True):
                payload_bytes = str(source_body_text or "").encode("utf-8")
            else:
                body_fields = fwd.get("body_fields")
                if not isinstance(body_fields, list) or len(body_fields) == 0:
                    attempt_detail["stage"] = "before_request"
                    attempt_detail["request_sent"] = False
                    attempt_detail["error"] = "Body-Konfiguration fehlt (body_fields leer)"
                    attempt_detail["exception_type"] = "BodyConfigError"
                    attempt_detail["replay_reason"] = "body_fields_missing"
                    stats["failed"] += 1
                    continue
                configured_body = build_configured_forward_body(item, body_fields)
                payload_bytes = configured_body.encode("utf-8")
                attempt_detail["body_unchanged"] = False
                attempt_detail["replay_reason"] = "configured_body_fields"
                attempt_detail["body_source"] = "configured_body_fields"
            method = attempt_detail["request_method"] or "POST"
            final_body_text = payload_bytes.decode("utf-8", errors="replace")
            attempt_detail["stage"] = "request"
            req = urlrequest.Request(url=url, data=payload_bytes, headers=headers, method=method)
            attempt_detail["final_request_method"] = method
            attempt_detail["final_request_url"] = url
            attempt_detail["final_request_headers"] = {k: v for k, v in req.header_items()}
            attempt_detail["final_request_body_text"] = final_body_text
            parsed_final = urlparse.parse_qs(final_body_text, keep_blank_values=True)
            device_param_values = parsed_final.get("device")
            if isinstance(device_param_values, list) and device_param_values:
                attempt_detail["sent_device_value"] = str(device_param_values[-1])
            with urlrequest.urlopen(req, timeout=6) as resp:
                attempt_detail["request_sent"] = True
                attempt_detail["http_status"] = int(getattr(resp, "status", 200))
                attempt_detail["response_status"] = attempt_detail["http_status"]
                response_text = resp.read().decode("utf-8", errors="replace")
                attempt_detail["response_body_text"] = response_text[:2000]
                attempt_detail["stage"] = "response"
                pass
            attempt_detail["ok"] = True
            stats["delivered"] += 1
        except urlerror.HTTPError as exc:
            attempt_detail["stage"] = "response"
            attempt_detail["request_sent"] = True
            attempt_detail["http_status"] = int(getattr(exc, "code", 0) or 0)
            attempt_detail["error"] = str(exc)
            attempt_detail["exception_type"] = exc.__class__.__name__
            try:
                body = exc.read().decode("utf-8", errors="replace")
                attempt_detail["response_excerpt"] = body[:300]
                attempt_detail["response_body_text"] = body[:2000]
            except Exception:
                attempt_detail["response_excerpt"] = ""
                attempt_detail["response_body_text"] = ""
            attempt_detail["response_status"] = attempt_detail["http_status"]
            stats["failed"] += 1
            label = str(fwd.get("name", "")).strip() or fwd.get("id", "")
            print(f"[forwarding] error ({label}): {exc}")
            state.append_forwarding_error(f"{label}: HTTP {attempt_detail['http_status']} {exc}")
        except (urlerror.URLError, TimeoutError, socket.timeout) as exc:
            attempt_detail["stage"] = "request"
            attempt_detail["request_sent"] = False
            attempt_detail["error"] = str(exc)
            attempt_detail["exception_type"] = exc.__class__.__name__
            stats["failed"] += 1
            label = str(fwd.get("name", "")).strip() or fwd.get("id", "")
            print(f"[forwarding] error ({label}): {exc}")
            state.append_forwarding_error(f"{label}: {exc}")
        except Exception as exc:
            attempt_detail["stage"] = "evaluation"
            attempt_detail["request_sent"] = False
            attempt_detail["error"] = str(exc)
            attempt_detail["exception_type"] = exc.__class__.__name__
            stats["failed"] += 1
            label = str(fwd.get("name", "")).strip() or fwd.get("id", "")
            print(f"[forwarding] error ({label}): {exc}")
            state.append_forwarding_error(f"{label}: {exc}")
    return stats


def forwarding_worker():
    while True:
        item = forward_queue.get()
        try:
            settings = state.get_settings()
            forwardings = settings.get("forwardings") or []
            if not isinstance(forwardings, list):
                continue
            forward_record_to_forwardings(item, forwardings, allow_disabled=False)
        except Exception as exc:
            print(f"[forwarding] error: {exc}")
            state.append_forwarding_error(str(exc))
        finally:
            forward_queue.task_done()


def save_scheduler():
    while True:
        try:
            settings = state.get_settings()
            if not bool(settings.get("nas_storage_enabled")):
                time.sleep(15)
                continue
            interval = int(settings.get("nas_interval_seconds") or 3600)
            interval = max(3600, interval)
            time.sleep(interval)
            with save_lock:
                state.flush_pending_to_nas()
        except Exception as exc:
            print(f"[nas-scheduler] error: {exc}")
            state.mark_nas_run(saved_count=0, error=str(exc))


def discover_themes() -> list[str]:
    if not THEMES_DIR.exists():
        return ["light"]
    themes = []
    for path in THEMES_DIR.iterdir():
        if path.is_dir() and (path / "theme.css").exists():
            themes.append(path.name)
    return sorted(themes) or ["light"]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def _sse_positions_stream(self):
        q = _sse_register()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            self.wfile.write(b"retry: 3000\n\n")
            self.wfile.flush()
            while True:
                try:
                    chunk = q.get(timeout=25.0)
                    self.wfile.write(chunk)
                    self.wfile.flush()
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            _sse_unregister(q)

    def _read_urlencoded_body(self, max_length: int = 1024 * 1024):
        content_type = self.headers.get("Content-Type", "")
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > max_length:
            return None, None, "Ungueltige Request-Groesse"
        raw_body = self.rfile.read(length).decode("utf-8", errors="replace")
        if "application/x-www-form-urlencoded" not in content_type:
            return None, None, "Nur x-www-form-urlencoded wird unterstuetzt"
        fields = {k: v[-1] for k, v in urlparse.parse_qs(raw_body, keep_blank_values=True).items()}
        return raw_body, fields, None

    def _finish_gps_ingest(self, device: dict, fields: dict, raw_body: str, ingest_route: str):
        latitude = fields.get("latitude") or fields.get("lat")
        longitude = fields.get("longitude") or fields.get("lon") or fields.get("lng")
        accuracy = fields.get("accuracy")
        if latitude is None or longitude is None:
            return json_response(self, {"error": "latitude und longitude sind erforderlich"}, HTTPStatus.BAD_REQUEST)
        lat = parse_coordinate(latitude, -90.0, 90.0)
        lon = parse_coordinate(longitude, -180.0, 180.0)
        if lat is None or lon is None:
            return json_response(self, {"error": "Ungueltige Koordinaten"}, HTTPStatus.BAD_REQUEST)
        normalized_accuracy = parse_accuracy(str(accuracy) if accuracy is not None else None)
        if accuracy is not None and str(accuracy).strip() != "" and normalized_accuracy is None:
            return json_response(self, {"error": "Ungueltige accuracy"}, HTTPStatus.BAD_REQUEST)

        if ingest_route == "/api/gps":
            timestamp = fields.get("timestamp") or utc_now_iso()
            normalized_timestamp = parse_iso_timestamp(timestamp)
            if normalized_timestamp is None:
                return json_response(self, {"error": "timestamp muss ISO-Format haben"}, HTTPStatus.BAD_REQUEST)
        else:
            time_candidate = optional_form_str(fields, "time") or optional_form_str(fields, "timestamp")
            if time_candidate:
                normalized_timestamp = parse_iso_timestamp(time_candidate)
                if normalized_timestamp is None:
                    return json_response(self, {"error": "time muss ISO-Format haben"}, HTTPStatus.BAD_REQUEST)
            else:
                normalized_timestamp = utc_now_iso()

        headers_dict = {k: v for k, v in self.headers.items()}
        received_at = utc_now_iso()
        record = {
            "device_id": device["id"],
            "device_name": device["name"],
            "request_device": optional_form_str(fields, "device"),
            "latitude": lat,
            "longitude": lon,
            "accuracy": normalized_accuracy,
            "timestamp": normalized_timestamp,
            "ingest_route": ingest_route,
            "extra_fields": fields,
            "raw_body": raw_body,
            "headers": headers_dict,
            "replay_request": build_replay_request(self.command, headers_dict, raw_body, received_at),
            "received_at": received_at,
        }
        if ingest_route == "/api/current-location":
            record["device"] = optional_form_str(fields, "device")
            record["battery"] = parse_battery_value(fields.get("battery"))
            record["speed"] = parse_optional_float_field(fields.get("speed"))
            record["direction"] = parse_optional_float_field(fields.get("direction"))
            record["altitude"] = parse_optional_float_field(fields.get("altitude"))
            record["provider"] = optional_form_str(fields, "provider")
            record["activity"] = optional_form_str(fields, "activity")
            record["time"] = optional_form_str(fields, "time")

        state.store_gps_request(record)
        pos_row = state._position_row_from_stored(record)
        if pos_row:
            broadcast_position_event({"type": "position", "position": pos_row})
        try:
            forward_queue.put_nowait(record)
        except queue.Full:
            msg = "queue voll, request wird nicht weitergeleitet"
            print(f"[forwarding] warning: {msg}")
            state.append_forwarding_error(msg)
        return json_response(self, {"ok": True})

    def _handle_gps_ingest(self, ingest_route: str):
        token = parse_bearer_token(self)
        if not token:
            return json_response(self, {"error": "Authorization Bearer fehlt"}, HTTPStatus.UNAUTHORIZED)
        device = state.get_device_by_key(token)
        if not device:
            return json_response(self, {"error": "Ungueltiger API-Key"}, HTTPStatus.UNAUTHORIZED)
        raw_body, fields, err = self._read_urlencoded_body()
        if err:
            return json_response(self, {"error": err}, HTTPStatus.BAD_REQUEST)
        return self._finish_gps_ingest(device, fields, raw_body, ingest_route)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length > 0 else b"{}"
        return json.loads(body.decode("utf-8"))

    def _serve_file(self, path: Path):
        if not path.exists() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        suffix = path.suffix.lower()
        content_type = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".webmanifest": "application/manifest+json; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".ico": "image/x-icon",
            ".webp": "image/webp",
        }.get(suffix, "application/octet-stream")
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlparse.urlparse(self.path)
        route = parsed.path
        query = urlparse.parse_qs(parsed.query)

        if route in ("/api", "/api/"):
            return self._serve_file(STATIC_DIR / "api-docs.html")
        if route == "/api/openapi.json":
            return json_response(self, build_openapi_spec())
        if route == "/api/devices":
            return json_response(self, {"devices": state.list_devices()})
        if route == "/api/health":
            return json_response(self, {"ok": True, "service": "gpslogger"})
        if route == "/api/devices/status":
            return json_response(self, {"statuses": state.get_device_statuses()})
        if route == "/api/settings":
            return json_response(self, {"settings": state.get_settings()})
        if route == "/api/system/status":
            runtime = state.get_runtime_stats()
            runtime["forward_queue_size"] = forward_queue.qsize()
            runtime["uptime_seconds"] = int(time.time() - STARTED_AT)
            return json_response(self, {"status": runtime})
        if route == "/api/storage/status":
            nas_path_override = None
            if "nas_path" in query:
                nas_path_override = str((query.get("nas_path") or [""])[0] or "").strip()
            enabled_override: bool | None = None
            if "nas_storage_enabled" in query:
                raw_list = query.get("nas_storage_enabled") or [""]
                raw_v = str(raw_list[0] if raw_list else "").strip()
                if raw_v != "":
                    enabled_override = raw_v.lower() in ("1", "true", "yes", "on")
            overview = state.get_storage_overview(
                nas_path_override,
                nas_storage_enabled_override=enabled_override,
            )
            return json_response(self, {"overview": overview})
        if route == "/api/forwarding/errors":
            query_limit = (query.get("limit", ["50"])[0] or "50")
            try:
                limit = max(1, min(500, int(query_limit)))
            except ValueError:
                limit = 50
            return json_response(self, {"errors": state.get_forwarding_errors(limit=limit)})
        if route == "/api/gps/recent":
            query_limit = (query.get("limit", ["20"])[0] or "20")
            try:
                limit = max(1, min(200, int(query_limit)))
            except ValueError:
                limit = 20
            return json_response(self, {"requests": state.get_recent_gps_requests(limit=limit)})
        if route == "/api/stream/positions":
            return self._sse_positions_stream()
        if route == "/api/themes":
            return json_response(self, {"themes": discover_themes()})
        if route == "/api/positions":
            query_from = (query.get("from", [None])[0] or None)
            query_to = (query.get("to", [None])[0] or None)
            query_limit = (query.get("limit", ["500"])[0] or "500")
            query_offset = (query.get("offset", ["0"])[0] or "0")
            left = parse_query_time(query_from)
            right = parse_query_time(query_to)
            if not query_from or not query_to:
                return json_response(
                    self,
                    {"error": "from und to sind erforderlich (ISO-8601)"},
                    HTTPStatus.BAD_REQUEST,
                )
            if query_from and left is None:
                return json_response(self, {"error": "from muss ISO-Format haben"}, HTTPStatus.BAD_REQUEST)
            if query_to and right is None:
                return json_response(self, {"error": "to muss ISO-Format haben"}, HTTPStatus.BAD_REQUEST)
            if left and right and left > right:
                return json_response(self, {"error": "from darf nicht nach to liegen"}, HTTPStatus.BAD_REQUEST)
            try:
                limit = max(1, min(5000, int(query_limit)))
            except ValueError:
                return json_response(self, {"error": "limit muss eine ganze Zahl sein"}, HTTPStatus.BAD_REQUEST)
            try:
                offset = max(0, int(query_offset))
            except ValueError:
                return json_response(self, {"error": "offset muss eine ganze Zahl sein"}, HTTPStatus.BAD_REQUEST)
            device_names = parse_device_filters(query)
            rows, has_more = state.query_positions(
                device_names=device_names,
                ts_from=query_from,
                ts_to=query_to,
                limit=limit,
                offset=offset,
            )
            return json_response(
                self,
                {
                    "positions": rows,
                    "pagination": {
                        "limit": limit,
                        "offset": offset,
                        "returned": len(rows),
                        "has_more": has_more,
                    },
                    "filters": {
                        "from": query_from,
                        "to": query_to,
                        "device": device_names,
                    },
                },
            )
        if route.startswith("/themes/"):
            rel = route.removeprefix("/themes/")
            return self._serve_file(THEMES_DIR / rel)
        if route == "/sw.js":
            path = STATIC_DIR / "sw.js"
            if not path.exists() or not path.is_file():
                return self.send_error(HTTPStatus.NOT_FOUND)
            data = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache, max-age=0")
            self.end_headers()
            self.wfile.write(data)
            return
        if route in ("/favicon.ico", "/favicon.svg"):
            return self._serve_file(STATIC_DIR / "icons" / "icon.svg")
        if route in ("/", "/index.html"):
            return self._serve_file(STATIC_DIR / "index.html")
        if route.startswith("/static/"):
            rel = route.removeprefix("/static/")
            return self._serve_file(STATIC_DIR / rel)

        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self):
        parsed = urlparse.urlparse(self.path)
        route = parsed.path

        if route == "/api/devices/draft":
            draft = state.create_device_draft()
            return json_response(self, draft)

        if route == "/api/devices/commit":
            body = self._read_json_body()
            token = str(body.get("draft_token", "")).strip()
            name = str(body.get("name", "")).strip()
            if not token or not name:
                return json_response(self, {"error": "draft_token und name sind erforderlich"}, HTTPStatus.BAD_REQUEST)
            override_key = body.get("api_key")
            if override_key is not None and not isinstance(override_key, str):
                return json_response(self, {"error": "api_key muss ein Text sein"}, HTTPStatus.BAD_REQUEST)
            try:
                device = state.commit_device_draft(token, name, api_key_override=override_key)
            except ValueError as exc:
                return json_response(self, {"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return json_response(self, {"device": device}, HTTPStatus.CREATED)

        if route == "/api/devices":
            return json_response(
                self,
                {"error": "Geräte über /api/devices/draft und /api/devices/commit anlegen"},
                HTTPStatus.BAD_REQUEST,
            )

        if route == "/api/forwardings":
            body = self._read_json_body()
            name = str(body.get("name", "")).strip()
            url = str(body.get("url", "")).strip()
            headers_raw = body.get("headers")
            headers = headers_raw if isinstance(headers_raw, dict) else {}
            enabled = bool(body.get("enabled", True))
            iho_raw = body.get("incoming_headers_only")
            incoming_headers_only = True if iho_raw is None else bool(iho_raw)
            fbs_raw = body.get("forward_body_from_source")
            forward_body_from_source = True if fbs_raw is None else bool(fbs_raw)
            body_fields_raw = body.get("body_fields")
            body_fields = body_fields_raw if isinstance(body_fields_raw, list) else []
            try:
                forwarding = state.create_forwarding(
                    name,
                    url,
                    headers,
                    enabled,
                    incoming_headers_only=incoming_headers_only,
                    forward_body_from_source=forward_body_from_source,
                    body_fields=body_fields,
                )
            except ValueError as exc:
                return json_response(self, {"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return json_response(self, {"forwarding": forwarding}, HTTPStatus.CREATED)

        if route.startswith("/api/forwardings/") and route.endswith("/test"):
            forward_id = route.removeprefix("/api/forwardings/").removesuffix("/test")
            selected = None
            for fwd in state.list_forwardings():
                if str(fwd.get("id")) == str(forward_id):
                    selected = fwd
                    break
            if not selected:
                return json_response(self, {"error": "Weiterleitung nicht gefunden"}, HTTPStatus.NOT_FOUND)
            devices = state.list_devices()
            statuses = state.get_device_statuses()
            latest_requests = state.get_latest_gps_requests_by_device()
            if not devices:
                return json_response(
                    self,
                    {
                        "ok": True,
                        "result": {
                            "forwarding_id": selected.get("id"),
                            "forwarding_name": selected.get("name"),
                            "target_url": selected.get("url"),
                            "server_side_request": True,
                            "devices_total": 0,
                            "devices_with_position": 0,
                            "devices_without_position": [],
                            "device_runs": [],
                            "requests_attempted": 0,
                            "requests_delivered": 0,
                            "requests_failed": 0,
                        },
                    },
                )
            total_with_position = 0
            attempted = 0
            delivered = 0
            failed = 0
            devices_without_position: list[dict] = []
            device_runs: list[dict] = []
            for device in devices:
                device_id = str(device.get("id") or "")
                st = statuses.get(device_id) or {}
                lat = st.get("latitude")
                lon = st.get("longitude")
                if lat is None or lon is None:
                    devices_without_position.append({"device_id": device_id, "device_name": device.get("name")})
                    continue
                total_with_position += 1
                record = latest_requests.get(device_id)
                if record is None:
                    record = build_test_forwarding_record(device, st)
                    replay_mode = "normalized_fallback"
                    replay_reason = "no_stored_request_for_device"
                else:
                    record = dict(record)
                    replay_mode = "stored_replay"
                    replay_reason = ""
                    replay = record.get("replay_request") if isinstance(record.get("replay_request"), dict) else None
                    if replay is None:
                        replay_reason = "stored_request_has_no_replay_request"
                        replay = build_replay_request(
                            "POST",
                            dict(record.get("headers") or {}),
                            str(record.get("raw_body") or ""),
                            str(record.get("received_at") or utc_now_iso()),
                        )
                        replay_mode = "legacy_stored_request_fallback"
                    replay = dict(replay)
                    replay["headers"] = select_replay_headers(dict(replay.get("headers") or {}))
                    replay["body_unchanged"] = True
                    record["replay_request"] = replay
                row = forward_record_to_forwardings(record, [selected], allow_disabled=True)
                attempted += int(row.get("attempted", 0))
                delivered += int(row.get("delivered", 0))
                failed += int(row.get("failed", 0))
                device_runs.append(
                    {
                        "device_id": device_id,
                        "device_name": device.get("name"),
                        "used_source": replay_mode,
                        "replay_available": replay_mode != "normalized_fallback",
                        "replay_reason": replay_reason,
                        "attempts": row.get("attempts") or [],
                    }
                )
            return json_response(
                self,
                {
                    "ok": True,
                    "result": {
                        "forwarding_id": selected.get("id"),
                        "forwarding_name": selected.get("name"),
                        "target_url": selected.get("url"),
                        "server_side_request": True,
                        "devices_total": len(devices),
                        "devices_with_position": total_with_position,
                        "devices_without_position": devices_without_position,
                        "device_runs": device_runs,
                        "requests_attempted": attempted,
                        "requests_delivered": delivered,
                        "requests_failed": failed,
                    },
                },
            )

        if route == "/api/save-now":
            with save_lock:
                result = state.flush_pending_to_nas()
            if not result.get("ok", True):
                return json_response(
                    self,
                    {
                        "ok": False,
                        "error_key": result.get("error_key"),
                        "result": result,
                    },
                    HTTPStatus.BAD_REQUEST,
                )
            return json_response(self, {"ok": True, "result": result})

        if route == "/api/admin/restart":
            schedule_restart_via_webhook()
            return json_response(
                self,
                {"ok": True, "message": "Neustart angefordert"},
            )

        if route.startswith("/api/devices/") and route.endswith("/rotate-key"):
            device_id = route.removeprefix("/api/devices/").removesuffix("/rotate-key")
            rotated = state.rotate_device_key(device_id)
            if not rotated:
                return json_response(self, {"error": "Device nicht gefunden"}, HTTPStatus.NOT_FOUND)
            return json_response(self, {"device": rotated})

        if route == "/api/gps":
            return self._handle_gps_ingest("/api/gps")

        if route == "/api/current-location":
            return self._handle_gps_ingest("/api/current-location")

        if route == "/api/forwarding/errors/clear":
            state.clear_forwarding_errors()
            return json_response(self, {"ok": True})

        self.send_error(HTTPStatus.NOT_FOUND)

    def do_PUT(self):
        parsed = urlparse.urlparse(self.path)
        route = parsed.path
        if route.startswith("/api/forwardings/"):
            forward_id = route.removeprefix("/api/forwardings/")
            body = self._read_json_body()
            name = str(body.get("name", "")).strip()
            url = str(body.get("url", "")).strip()
            headers_raw = body.get("headers")
            headers = headers_raw if isinstance(headers_raw, dict) else {}
            enabled = bool(body.get("enabled", True))
            iho_raw = body.get("incoming_headers_only")
            incoming_headers_only = True if iho_raw is None else bool(iho_raw)
            fbs_raw = body.get("forward_body_from_source")
            forward_body_from_source = True if fbs_raw is None else bool(fbs_raw)
            body_fields_raw = body.get("body_fields")
            body_fields = body_fields_raw if isinstance(body_fields_raw, list) else []
            try:
                updated = state.update_forwarding(
                    forward_id,
                    name,
                    url,
                    headers,
                    enabled,
                    incoming_headers_only=incoming_headers_only,
                    forward_body_from_source=forward_body_from_source,
                    body_fields=body_fields,
                )
            except ValueError as exc:
                return json_response(self, {"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            if not updated:
                return json_response(self, {"error": "Weiterleitung nicht gefunden"}, HTTPStatus.NOT_FOUND)
            return json_response(self, {"forwarding": updated})

        if route.startswith("/api/devices/"):
            device_id = route.removeprefix("/api/devices/")
            body = self._read_json_body()
            name = str(body.get("name", "")).strip()
            if not name:
                return json_response(self, {"error": "Name ist erforderlich"}, HTTPStatus.BAD_REQUEST)
            api_key = body.get("api_key")
            if api_key is not None and not isinstance(api_key, str):
                return json_response(self, {"error": "api_key muss ein Text sein"}, HTTPStatus.BAD_REQUEST)
            map_color_index = None
            if "map_color_index" in body and body.get("map_color_index") is not None:
                try:
                    map_color_index = state.normalize_map_color_index(body.get("map_color_index"))
                except ValueError as exc:
                    return json_response(self, {"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            try:
                device = state.update_device(device_id, name, map_color_index=map_color_index, api_key=api_key)
            except ValueError as exc:
                return json_response(self, {"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            if not device:
                return json_response(self, {"error": "Device nicht gefunden"}, HTTPStatus.NOT_FOUND)
            return json_response(self, {"device": device})

        if route == "/api/settings":
            payload = self._read_json_body()
            try:
                settings = state.update_settings(payload)
            except ConfigFieldError as exc:
                return json_response(
                    self,
                    {"error": exc.error_key, "error_key": exc.error_key},
                    HTTPStatus.BAD_REQUEST,
                )
            return json_response(self, {"settings": settings})

        self.send_error(HTTPStatus.NOT_FOUND)

    def do_DELETE(self):
        parsed = urlparse.urlparse(self.path)
        route = parsed.path
        if route.startswith("/api/forwardings/"):
            forward_id = route.removeprefix("/api/forwardings/")
            ok = state.delete_forwarding(forward_id)
            if not ok:
                return json_response(self, {"error": "Weiterleitung nicht gefunden"}, HTTPStatus.NOT_FOUND)
            return json_response(self, {"ok": True})
        if route.startswith("/api/devices/"):
            device_id = route.removeprefix("/api/devices/")
            ok = state.delete_device(device_id)
            if not ok:
                return json_response(self, {"error": "Device nicht gefunden"}, HTTPStatus.NOT_FOUND)
            return json_response(self, {"ok": True})
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_PATCH(self):
        parsed = urlparse.urlparse(self.path)
        route = parsed.path
        if route.startswith("/api/forwardings/"):
            forward_id = route.removeprefix("/api/forwardings/")
            body = self._read_json_body()
            if "enabled" not in body:
                return json_response(self, {"error": "enabled ist erforderlich"}, HTTPStatus.BAD_REQUEST)
            updated = state.set_forwarding_enabled(forward_id, bool(body.get("enabled")))
            if not updated:
                return json_response(self, {"error": "Weiterleitung nicht gefunden"}, HTTPStatus.NOT_FOUND)
            return json_response(self, {"forwarding": updated})
        self.send_error(HTTPStatus.NOT_FOUND)


def run_server(host: str = "0.0.0.0", port: int = 8080):
    threading.Thread(target=forwarding_worker, daemon=True).start()
    threading.Thread(target=save_scheduler, daemon=True).start()
    print(f"GPSLogger laeuft auf http://{host}:{port}")
    server = ThreadingHTTPServer((host, port), Handler)
    server.serve_forever()

