import json
import queue
import threading
import time
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import parse as urlparse
from urllib import request as urlrequest

from .openapi_spec import build_openapi_spec
from .state import AppState
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
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


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


def is_http_url(value: str) -> bool:
    try:
        parsed = urlparse.urlparse(value)
    except Exception:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def forwarding_worker():
    while True:
        item = forward_queue.get()
        try:
            settings = state.get_settings()
            forwardings = settings.get("forwardings") or []
            if not isinstance(forwardings, list):
                continue
            raw_in_headers = item.get("headers") or {}
            raw_body_text = item.get("raw_body", "") or ""
            for fwd in forwardings:
                if not isinstance(fwd, dict) or not fwd.get("enabled"):
                    continue
                url = str(fwd.get("url", "")).strip()
                if not url or not is_http_url(url):
                    continue
                nfwd = state._normalize_forwarding_entry(fwd)
                headers = build_outgoing_forward_headers(nfwd, raw_in_headers)
                if nfwd.get("forward_body_from_source", True):
                    payload_bytes = raw_body_text.encode("utf-8")
                else:
                    payload_bytes = b""
                try:
                    req = urlrequest.Request(url=url, data=payload_bytes, headers=headers, method="POST")
                    with urlrequest.urlopen(req, timeout=6):
                        pass
                except Exception as exc:
                    label = str(fwd.get("name", "")).strip() or fwd.get("id", "")
                    print(f"[forwarding] error ({label}): {exc}")
                    state.append_forwarding_error(f"{label}: {exc}")
        except Exception as exc:
            print(f"[forwarding] error: {exc}")
            state.append_forwarding_error(str(exc))
        finally:
            forward_queue.task_done()


def save_scheduler():
    while True:
        try:
            settings = state.get_settings()
            interval = max(5, int(settings.get("nas_interval_seconds", 60)))
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
        record = {
            "device_id": device["id"],
            "device_name": device["name"],
            "latitude": lat,
            "longitude": lon,
            "accuracy": normalized_accuracy,
            "timestamp": normalized_timestamp,
            "ingest_route": ingest_route,
            "extra_fields": fields,
            "raw_body": raw_body,
            "headers": headers_dict,
            "received_at": utc_now_iso(),
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
            left = parse_query_time(query_from)
            right = parse_query_time(query_to)
            if query_from and left is None:
                return json_response(self, {"error": "from muss ISO-Format haben"}, HTTPStatus.BAD_REQUEST)
            if query_to and right is None:
                return json_response(self, {"error": "to muss ISO-Format haben"}, HTTPStatus.BAD_REQUEST)
            if left and right and left > right:
                return json_response(self, {"error": "from darf nicht nach to liegen"}, HTTPStatus.BAD_REQUEST)
            rows = state.query_positions(
                device_id=(query.get("device_id", [None])[0] or None),
                ts_from=query_from,
                ts_to=query_to,
            )
            return json_response(self, {"positions": rows})
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
            return self._serve_file(STATIC_DIR / "favicon.svg")
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
            try:
                forwarding = state.create_forwarding(
                    name,
                    url,
                    headers,
                    enabled,
                    incoming_headers_only=incoming_headers_only,
                    forward_body_from_source=forward_body_from_source,
                )
            except ValueError as exc:
                return json_response(self, {"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return json_response(self, {"forwarding": forwarding}, HTTPStatus.CREATED)

        if route == "/api/save-now":
            try:
                with save_lock:
                    result = state.flush_pending_to_nas()
                return json_response(self, {"ok": True, "result": result})
            except Exception as exc:
                state.mark_nas_run(saved_count=0, error=str(exc))
                return json_response(self, {"ok": False, "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

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
            try:
                updated = state.update_forwarding(
                    forward_id,
                    name,
                    url,
                    headers,
                    enabled,
                    incoming_headers_only=incoming_headers_only,
                    forward_body_from_source=forward_body_from_source,
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
            map_color_index = None
            if "map_color_index" in body and body.get("map_color_index") is not None:
                try:
                    map_color_index = state.normalize_map_color_index(body.get("map_color_index"))
                except ValueError as exc:
                    return json_response(self, {"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            try:
                device = state.update_device(device_id, name, map_color_index=map_color_index)
            except ValueError as exc:
                return json_response(self, {"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            if not device:
                return json_response(self, {"error": "Device nicht gefunden"}, HTTPStatus.NOT_FOUND)
            return json_response(self, {"device": device})

        if route == "/api/settings":
            payload = self._read_json_body()
            settings = state.update_settings(payload)
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

