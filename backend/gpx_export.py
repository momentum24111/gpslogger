"""GPX-1.1-Export als Stream, ohne Exportdatei auf der Platte."""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any, Iterable, Iterator
from urllib.parse import quote
from xml.sax.saxutils import escape

GPX_NAMESPACE = "http://www.topografix.com/GPX/1/1"
GPX_SCHEMA = "http://www.topografix.com/GPX/1/1/gpx.xsd"
_FILENAME_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class GpxExportEmpty(Exception):
    """Keine gültigen Punkte für den angeforderten Export."""


def format_gpx_time(value: Any) -> str | None:
    """ISO-8601 in UTC mit Z-Suffix. Naive Zeitstempel gelten als UTC."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    if parsed.microsecond:
        fraction = f"{parsed.microsecond:06d}".rstrip("0")
        return parsed.strftime("%Y-%m-%dT%H:%M:%S") + f".{fraction}Z"
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


def format_gpx_number(value: float) -> str:
    text = f"{float(value):.8f}".rstrip("0").rstrip(".")
    if text in {"", "-0", "-"}:
        return "0"
    return text


def optional_altitude(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def finite_coordinate(value: Any, low: float, high: float) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < low or number > high:
        return None
    return number


def gpx_point_coordinates(row: dict[str, Any]) -> tuple[float, float] | None:
    lat = finite_coordinate(row.get("latitude"), -90.0, 90.0)
    lon = finite_coordinate(row.get("longitude"), -180.0, 180.0)
    if lat is None or lon is None:
        return None
    return lat, lon


def track_key(row: dict[str, Any]) -> str:
    device_id = str(row.get("device_id") or "").strip()
    if device_id:
        return device_id
    return str(row.get("device_name") or "").strip().lower() or "unknown"


def track_name(row: dict[str, Any]) -> str:
    name = str(row.get("device_name") or "").strip()
    if name:
        return name
    device_id = str(row.get("device_id") or "").strip()
    return device_id or "GPS"


def format_trkpt(row: dict[str, Any], lat: float, lon: float) -> str:
    parts = [f'<trkpt lat="{format_gpx_number(lat)}" lon="{format_gpx_number(lon)}">']
    altitude = optional_altitude(row.get("altitude"))
    if altitude is not None:
        parts.append(f"<ele>{format_gpx_number(altitude)}</ele>")
    timestamp = format_gpx_time(row.get("timestamp"))
    if timestamp:
        parts.append(f"<time>{timestamp}</time>")
    parts.append("</trkpt>\n")
    return "".join(parts)


def gpx_header(metadata_name: str) -> str:
    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    safe_name = escape(metadata_name)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<gpx version="1.1" creator="GPSLogger"\n'
        f' xmlns="{GPX_NAMESPACE}"\n'
        ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"\n'
        f' xsi:schemaLocation="{GPX_NAMESPACE} {GPX_SCHEMA}">\n'
        "<metadata>\n"
        f"<name>{safe_name}</name>\n"
        f"<time>{created}</time>\n"
        "</metadata>\n"
    )


def iter_gpx_chunks(rows: Iterable[dict[str, Any]], metadata_name: str) -> Iterator[str]:
    """Liefert GPX-Textstücke. Wirft GpxExportEmpty, bevor das erste Stück entsteht."""
    iterator = iter(rows)
    first: dict[str, Any] | None = None
    first_coords: tuple[float, float] | None = None
    for row in iterator:
        coords = gpx_point_coordinates(row)
        if coords is None:
            continue
        first = row
        first_coords = coords
        break
    if first is None or first_coords is None:
        raise GpxExportEmpty()

    yield gpx_header(metadata_name)
    current_key: str | None = None
    open_track = False

    def emit(row: dict[str, Any], coords: tuple[float, float]) -> str:
        nonlocal current_key, open_track
        key = track_key(row)
        pieces: list[str] = []
        if key != current_key:
            if open_track:
                pieces.append("</trkseg></trk>\n")
            current_key = key
            open_track = True
            pieces.append(f"<trk><name>{escape(track_name(row))}</name><trkseg>\n")
        pieces.append(format_trkpt(row, coords[0], coords[1]))
        return "".join(pieces)

    yield emit(first, first_coords)
    for row in iterator:
        coords = gpx_point_coordinates(row)
        if coords is None:
            continue
        yield emit(row, coords)
    if open_track:
        yield "</trkseg></trk>\n"
    yield "</gpx>\n"


def _iso_day(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    if _FILENAME_DATE.match(text):
        return text
    parsed = format_gpx_time(text)
    if not parsed:
        return None
    return parsed[:10]


def sanitize_filename_part(value: str) -> str:
    text = re.sub(r"\s+", "_", str(value or "").strip())
    text = re.sub(r"[^\w\-]+", "", text, flags=re.UNICODE)
    return text[:40].strip("_")


def gpx_filename(
    *,
    filename_from: str | None = None,
    filename_to: str | None = None,
    from_iso: str | None = None,
    to_iso: str | None = None,
    device_label: str | None = None,
    current: bool = False,
) -> str:
    if current:
        span = "aktuell"
    else:
        start = _iso_day(filename_from) or _iso_day(from_iso) or "export"
        end = _iso_day(filename_to) or _iso_day(to_iso) or start
        span = f"{start}_{end}"
    label = sanitize_filename_part(device_label or "")
    if label:
        return f"GPSLogger_{label}_{span}.gpx"
    return f"GPSLogger_{span}.gpx"


def content_disposition(filename: str) -> str:
    ascii_name = filename.encode("ascii", "ignore").decode("ascii")
    ascii_name = ascii_name.replace('"', "").replace("\\", "").replace("\r", "").replace("\n", "")
    if not ascii_name.lower().endswith(".gpx"):
        ascii_name = "GPSLogger.gpx"
    encoded = quote(filename, safe="")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded}"
