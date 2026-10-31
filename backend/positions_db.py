"""SQLite Abfrageindex für GPS-Positionen (NDJSON bleibt Source of Truth)."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1

# Nur diese Schrittweiten sind für die Kartendarstellung erlaubt.
# 1 bedeutet volle Auflösung (bisheriges API-Verhalten).
MAP_POINT_STRIDES = frozenset({1, 2, 5, 10, 20, 50, 100})
DEFAULT_MAP_POINT_STRIDE = 10

META_SCHEMA_VERSION = "schema_version"
META_NDJSON_BYTE_OFFSET = "ndjson_byte_offset"
META_NDJSON_FILE_SIZE = "ndjson_file_size"
META_LAST_INGEST_SEQ = "last_ingest_seq"
META_SYNC_COMPLETE = "sync_complete"


def parse_time_utc(value: Any) -> datetime | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def timestamp_to_epoch(value: Any) -> float | None:
    dt = parse_time_utc(value)
    if dt is None:
        return None
    return dt.timestamp()


def format_cursor_epoch(value: float) -> str:
    """Dezimaldarstellung, die über Float-JSON und Query-Strings stabil bleibt."""
    return format(float(value), ".17g")


def connect(db_path: Path) -> sqlite3.Connection:
    """Kurzlebige Connection; WAL für bessere Concurrent Reads unter ThreadingHTTPServer."""
    conn = sqlite3.connect(str(db_path), timeout=30.0, check_same_thread=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS positions (
            ingest_seq INTEGER PRIMARY KEY,
            device_id TEXT,
            device_name TEXT,
            device_name_lower TEXT,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            accuracy REAL,
            timestamp TEXT,
            timestamp_epoch REAL,
            received_at TEXT,
            battery TEXT,
            speed REAL,
            direction REAL,
            altitude REAL,
            provider TEXT,
            activity TEXT,
            device TEXT,
            time TEXT,
            ingest_route TEXT,
            request_device TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_positions_timestamp_epoch
            ON positions(timestamp_epoch);

        CREATE INDEX IF NOT EXISTS idx_positions_device_lower_ts
            ON positions(device_name_lower, timestamp_epoch);

        CREATE INDEX IF NOT EXISTS idx_positions_ingest_seq
            ON positions(ingest_seq);

        CREATE TABLE IF NOT EXISTS sync_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )
    _set_meta(conn, META_SCHEMA_VERSION, str(SCHEMA_VERSION))
    conn.commit()


def _get_meta(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM sync_meta WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    return str(row["value"])


def _set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO sync_meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def get_sync_byte_offset(conn: sqlite3.Connection) -> int:
    raw = _get_meta(conn, META_NDJSON_BYTE_OFFSET, "0")
    try:
        return max(0, int(raw or "0"))
    except (TypeError, ValueError):
        return 0


def set_sync_progress(
    conn: sqlite3.Connection,
    *,
    byte_offset: int,
    file_size: int,
    last_ingest_seq: int | None = None,
    complete: bool = False,
) -> None:
    _set_meta(conn, META_NDJSON_BYTE_OFFSET, str(max(0, int(byte_offset))))
    _set_meta(conn, META_NDJSON_FILE_SIZE, str(max(0, int(file_size))))
    if last_ingest_seq is not None:
        _set_meta(conn, META_LAST_INGEST_SEQ, str(int(last_ingest_seq)))
    _set_meta(conn, META_SYNC_COMPLETE, "1" if complete else "0")


def is_sync_complete(conn: sqlite3.Connection) -> bool:
    return _get_meta(conn, META_SYNC_COMPLETE, "0") == "1"


def _optional_float(value: Any) -> float | None:
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _battery_as_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    return str(value)


def item_to_db_row(item: dict[str, Any]) -> dict[str, Any] | None:
    """Baut eine Index-Zeile; None wenn keine gültigen Koordinaten oder keine ingest_seq."""
    raw_seq = item.get("ingest_seq")
    try:
        ingest_seq = int(raw_seq)
    except (TypeError, ValueError):
        return None
    if ingest_seq < 1:
        return None
    try:
        lat = float(item.get("latitude"))
        lon = float(item.get("longitude"))
    except (TypeError, ValueError):
        return None

    ts_raw = item.get("timestamp") or item.get("received_at")
    epoch = timestamp_to_epoch(ts_raw)
    device_name = item.get("device_name")
    device_name_str = str(device_name).strip() if device_name is not None else ""
    return {
        "ingest_seq": ingest_seq,
        "device_id": item.get("device_id"),
        "device_name": device_name,
        "device_name_lower": device_name_str.lower() if device_name_str else "",
        "latitude": lat,
        "longitude": lon,
        "accuracy": _optional_float(item.get("accuracy")),
        "timestamp": ts_raw,
        "timestamp_epoch": epoch,
        "received_at": item.get("received_at"),
        "battery": _battery_as_text(item.get("battery")),
        "speed": _optional_float(item.get("speed")),
        "direction": _optional_float(item.get("direction")),
        "altitude": _optional_float(item.get("altitude")),
        "provider": item.get("provider"),
        "activity": item.get("activity"),
        "device": item.get("device"),
        "time": item.get("time"),
        "ingest_route": item.get("ingest_route"),
        "request_device": item.get("request_device"),
    }


def upsert_position(conn: sqlite3.Connection, item: dict[str, Any]) -> bool:
    row = item_to_db_row(item)
    if row is None:
        return False
    conn.execute(
        """
        INSERT INTO positions (
            ingest_seq, device_id, device_name, device_name_lower,
            latitude, longitude, accuracy, timestamp, timestamp_epoch, received_at,
            battery, speed, direction, altitude, provider, activity,
            device, time, ingest_route, request_device
        ) VALUES (
            :ingest_seq, :device_id, :device_name, :device_name_lower,
            :latitude, :longitude, :accuracy, :timestamp, :timestamp_epoch, :received_at,
            :battery, :speed, :direction, :altitude, :provider, :activity,
            :device, :time, :ingest_route, :request_device
        )
        ON CONFLICT(ingest_seq) DO UPDATE SET
            device_id=excluded.device_id,
            device_name=excluded.device_name,
            device_name_lower=excluded.device_name_lower,
            latitude=excluded.latitude,
            longitude=excluded.longitude,
            accuracy=excluded.accuracy,
            timestamp=excluded.timestamp,
            timestamp_epoch=excluded.timestamp_epoch,
            received_at=excluded.received_at,
            battery=excluded.battery,
            speed=excluded.speed,
            direction=excluded.direction,
            altitude=excluded.altitude,
            provider=excluded.provider,
            activity=excluded.activity,
            device=excluded.device,
            time=excluded.time,
            ingest_route=excluded.ingest_route,
            request_device=excluded.request_device
        """,
        row,
    )
    return True


def upsert_positions_many(conn: sqlite3.Connection, items: Iterable[dict[str, Any]]) -> int:
    n = 0
    for item in items:
        if upsert_position(conn, item):
            n += 1
    return n


def db_row_to_position(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    """API-Zeile kompatibel zu AppState._position_row_from_stored."""
    get = row.__getitem__ if hasattr(row, "__getitem__") else row.get  # type: ignore[attr-defined]
    base: dict[str, Any] = {
        "device_id": get("device_id"),
        "device_name": get("device_name"),
        "latitude": float(get("latitude")),
        "longitude": float(get("longitude")),
        "accuracy": get("accuracy"),
        "timestamp": get("timestamp") or get("received_at"),
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
        val = get(key)
        if val is not None:
            if key == "battery":
                # Als Zahl zurückgeben wenn möglich (wie Originalspeicher).
                try:
                    base[key] = float(val)
                except (TypeError, ValueError):
                    base[key] = val
            else:
                base[key] = val
    return base


def parse_position_stride(raw: str | None) -> int | None:
    """Optionales `stride` für die Karte. None = volle Auflösung. ValueError bei ungültigen Werten."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        value = int(text)
    except (TypeError, ValueError) as exc:
        raise ValueError("stride") from exc
    if value not in MAP_POINT_STRIDES:
        raise ValueError("stride")
    if value <= 1:
        return None
    return value


def position_partition_key(row: dict[str, Any]) -> str:
    device_id = str(row.get("device_id") or "").strip()
    if device_id:
        return device_id
    return str(row.get("device_name") or "").strip().lower()


def _position_time_sort_key(row: dict[str, Any], order_index: int) -> tuple[int, float, int]:
    epoch = row.get("timestamp_epoch")
    if epoch is None:
        epoch = timestamp_to_epoch(row.get("timestamp") or row.get("received_at"))
    if epoch is None:
        return (0, 0.0, order_index)
    try:
        return (1, float(epoch), order_index)
    except (TypeError, ValueError):
        return (0, 0.0, order_index)


def thin_positions_by_stride(rows: list[dict[str, Any]], stride: int) -> list[dict[str, Any]]:
    """Behält je Gerät jeden n-ten Punkt sowie immer den zeitlich ersten und letzten."""
    if stride <= 1 or len(rows) <= 1:
        return list(rows)
    groups: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for index, row in enumerate(rows):
        groups.setdefault(position_partition_key(row), []).append((index, row))
    keep: set[int] = set()
    for entries in groups.values():
        ordered = sorted(entries, key=lambda item: _position_time_sort_key(item[1], item[0]))
        count = len(ordered)
        chosen = set(range(0, count, stride))
        chosen.add(0)
        chosen.add(count - 1)
        for pos in chosen:
            keep.add(ordered[pos][0])
    return [row for index, row in enumerate(rows) if index in keep]


@dataclass(frozen=True)
class PositionPage:
    rows: list[dict[str, Any]]
    has_more: bool
    total: int | None = None
    cursor_epoch: str | None = None
    cursor_seq: int | None = None


def _normalize_device_names(device_names: list[str] | None) -> set[str] | None:
    if not isinstance(device_names, list) or len(device_names) == 0:
        return None
    normalized = {str(name).strip().lower() for name in device_names if str(name).strip()}
    return normalized or None


def _normalize_device_ids(device_ids: list[str] | None) -> list[str] | None:
    if device_ids is None:
        return None
    return list(dict.fromkeys(str(device_id).strip() for device_id in device_ids if str(device_id).strip()))


def _position_where_sql(
    device_names: list[str] | None,
    device_ids: list[str] | None,
    ts_from: str | None,
    ts_to: str | None,
) -> tuple[str, list[Any]]:
    where: list[str] = []
    params: list[Any] = []
    normalized_device_names = _normalize_device_names(device_names)
    if normalized_device_names is not None:
        placeholders = ",".join("?" for _ in normalized_device_names)
        where.append(f"device_name_lower IN ({placeholders})")
        params.extend(sorted(normalized_device_names))
    normalized_device_ids = _normalize_device_ids(device_ids)
    if normalized_device_ids is not None:
        if not normalized_device_ids:
            where.append("0")
        else:
            placeholders = ",".join("?" for _ in normalized_device_ids)
            where.append(f"device_id IN ({placeholders})")
            params.extend(normalized_device_ids)
    left = timestamp_to_epoch(ts_from)
    right = timestamp_to_epoch(ts_to)
    if left is not None or right is not None:
        where.append("timestamp_epoch IS NOT NULL")
        if left is not None:
            where.append("timestamp_epoch >= ?")
            params.append(left)
        if right is not None:
            where.append("timestamp_epoch <= ?")
            params.append(right)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    return where_sql, params


def _stride_value(stride: int | None) -> int:
    safe_stride = 1
    if stride is None:
        return safe_stride
    try:
        safe_stride = int(stride)
    except (TypeError, ValueError) as exc:
        raise ValueError("stride") from exc
    if safe_stride not in MAP_POINT_STRIDES:
        raise ValueError("stride")
    return safe_stride


def query_position_page(
    conn: sqlite3.Connection,
    device_names: list[str] | None,
    ts_from: str | None,
    ts_to: str | None,
    *,
    limit: int = 500,
    offset: int = 0,
    stride: int | None = None,
    device_ids: list[str] | None = None,
    order: str = "ingest",
    after_epoch: float | None = None,
    after_seq: int | None = None,
    include_total: bool = False,
) -> PositionPage:
    """Seiten der Karten- oder API-Abfrage.

    `order=ingest` bleibt die bisherige Reihenfolge. `order=time` sortiert stabil
    nach Zeit und ingest_seq. Ein Cursor gilt nur für diese Zeitordnung und zählt
    die Ausdünnung über den gesamten Zeitraum, nicht je Seite neu.
    """
    if order not in ("ingest", "time"):
        raise ValueError("order")
    if (after_epoch is None) != (after_seq is None):
        raise ValueError("cursor")
    if after_epoch is not None and order != "time":
        raise ValueError("cursor")
    safe_limit = max(1, min(5000, int(limit)))
    safe_offset = 0 if after_epoch is not None else max(0, int(offset))
    safe_stride = _stride_value(stride)
    where_sql, params = _position_where_sql(device_names, device_ids, ts_from, ts_to)
    order_sql = "timestamp_epoch ASC, ingest_seq ASC" if order == "time" else "ingest_seq ASC"
    cursor_sql = ""
    cursor_params: list[Any] = []
    if after_epoch is not None:
        cursor_sql = " AND (timestamp_epoch > ? OR (timestamp_epoch = ? AND ingest_seq > ?))"
        cursor_params = [float(after_epoch), float(after_epoch), int(after_seq or 0)]

    total: int | None = None
    if include_total:
        total = _count_matching_positions(conn, where_sql, params, safe_stride)

    if safe_stride > 1:
        partition = "COALESCE(NULLIF(TRIM(device_id), ''), IFNULL(device_name_lower, ''))"
        sql = (
            "WITH filtered AS ("
            " SELECT *,"
            " ROW_NUMBER() OVER ("
            f" PARTITION BY {partition}"
            " ORDER BY timestamp_epoch ASC, ingest_seq ASC"
            " ) AS _sample_rn,"
            " COUNT(*) OVER ("
            f" PARTITION BY {partition}"
            " ) AS _sample_count"
            " FROM positions"
            f"{where_sql}"
            ") "
            "SELECT * FROM filtered"
            " WHERE (((_sample_rn - 1) % ? = 0) OR _sample_rn = _sample_count)"
            f"{cursor_sql}"
            f" ORDER BY {order_sql}"
            " LIMIT ? OFFSET ?"
        )
        query_params = [*params, safe_stride, *cursor_params, safe_limit + 1, safe_offset]
    else:
        cursor_clause = ""
        if cursor_sql:
            cursor_clause = cursor_sql if where_sql else " WHERE " + cursor_sql.removeprefix(" AND ")
        sql = (
            "SELECT * FROM positions"
            f"{where_sql}{cursor_clause}"
            f" ORDER BY {order_sql}"
            " LIMIT ? OFFSET ?"
        )
        query_params = [*params, *cursor_params, safe_limit + 1, safe_offset]

    raw_rows = conn.execute(sql, query_params).fetchall()
    has_more = len(raw_rows) > safe_limit
    if has_more:
        raw_rows = raw_rows[:safe_limit]
    cursor_epoch: str | None = None
    cursor_seq: int | None = None
    if order == "time" and raw_rows:
        last = raw_rows[-1]
        epoch = last["timestamp_epoch"]
        seq = last["ingest_seq"]
        if epoch is not None and seq is not None:
            cursor_epoch = format_cursor_epoch(float(epoch))
            cursor_seq = int(seq)
    return PositionPage(
        rows=[db_row_to_position(row) for row in raw_rows],
        has_more=has_more,
        total=total,
        cursor_epoch=cursor_epoch,
        cursor_seq=cursor_seq,
    )


def _count_matching_positions(
    conn: sqlite3.Connection,
    where_sql: str,
    params: list[Any],
    stride: int,
) -> int:
    if stride > 1:
        partition = "COALESCE(NULLIF(TRIM(device_id), ''), IFNULL(device_name_lower, ''))"
        sql = (
            "WITH filtered AS ("
            " SELECT"
            " ROW_NUMBER() OVER ("
            f" PARTITION BY {partition}"
            " ORDER BY timestamp_epoch ASC, ingest_seq ASC"
            " ) AS _sample_rn,"
            " COUNT(*) OVER ("
            f" PARTITION BY {partition}"
            " ) AS _sample_count"
            " FROM positions"
            f"{where_sql}"
            ") "
            "SELECT COUNT(*) AS c FROM filtered"
            " WHERE (((_sample_rn - 1) % ? = 0) OR _sample_rn = _sample_count)"
        )
        row = conn.execute(sql, [*params, stride]).fetchone()
    else:
        sql = f"SELECT COUNT(*) AS c FROM positions{where_sql}"
        row = conn.execute(sql, params).fetchone()
    return int(row["c"] if row else 0)


def query_positions(
    conn: sqlite3.Connection,
    device_names: list[str] | None,
    ts_from: str | None,
    ts_to: str | None,
    *,
    limit: int = 500,
    offset: int = 0,
    stride: int | None = None,
    device_ids: list[str] | None = None,
    order: str = "ingest",
    after_epoch: float | None = None,
    after_seq: int | None = None,
    include_total: bool = False,
) -> tuple[list[dict[str, Any]], bool]:
    page = query_position_page(
        conn,
        device_names,
        ts_from,
        ts_to,
        limit=limit,
        offset=offset,
        stride=stride,
        device_ids=device_ids,
        order=order,
        after_epoch=after_epoch,
        after_seq=after_seq,
        include_total=include_total,
    )
    return page.rows, page.has_more


def iter_full_positions(
    conn: sqlite3.Connection,
    device_ids: list[str] | None,
    ts_from: str | None,
    ts_to: str | None,
) -> Iterable[dict[str, Any]]:
    """Alle gespeicherten Punkte ohne Punktdichte, je Gerät chronologisch.

    Der Cursor wird zeilenweise gelesen, damit große Zeiträume nicht komplett
    im Speicher liegen müssen.
    """
    where = [
        "latitude >= -90 AND latitude <= 90",
        "longitude >= -180 AND longitude <= 180",
    ]
    params: list[Any] = []
    ids = [str(device_id).strip() for device_id in (device_ids or []) if str(device_id).strip()]
    if not ids:
        return
    placeholders = ",".join("?" for _ in ids)
    where.append(f"device_id IN ({placeholders})")
    params.extend(ids)

    left = timestamp_to_epoch(ts_from)
    right = timestamp_to_epoch(ts_to)
    if left is not None or right is not None:
        where.append("timestamp_epoch IS NOT NULL")
        if left is not None:
            where.append("timestamp_epoch >= ?")
            params.append(left)
        if right is not None:
            where.append("timestamp_epoch <= ?")
            params.append(right)

    sql = (
        "SELECT device_id, device_name, latitude, longitude, altitude, timestamp, received_at "
        "FROM positions WHERE "
        + " AND ".join(where)
        + " ORDER BY COALESCE(NULLIF(TRIM(device_id), ''), IFNULL(device_name_lower, '')), "
        "timestamp_epoch ASC, ingest_seq ASC"
    )
    cursor = conn.execute(sql, params)
    for row in cursor:
        yield {
            "device_id": row["device_id"],
            "device_name": row["device_name"],
            "latitude": row["latitude"],
            "longitude": row["longitude"],
            "altitude": row["altitude"],
            "timestamp": row["timestamp"] or row["received_at"],
        }


def count_positions(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS c FROM positions").fetchone()
    return int(row["c"] if row else 0)


def mark_synced_to_file(conn: sqlite3.Connection, ndjson_path: Path, last_ingest_seq: int | None = None) -> None:
    """Nach erfolgreichem Live-Insert: Sync-Offset auf EOF setzen, damit Neustarts nicht nachziehen müssen."""
    size = ndjson_path.stat().st_size if ndjson_path.exists() else 0
    set_sync_progress(
        conn,
        byte_offset=size,
        file_size=size,
        last_ingest_seq=last_ingest_seq,
        complete=True,
    )


def sync_from_ndjson(
    conn: sqlite3.Connection,
    ndjson_path: Path,
    *,
    batch_size: int = 2000,
    progress_every_batches: int = 5,
) -> dict[str, Any]:
    """
    Inkrementeller Import aus gps.ndjson.
    Fortschritt über Byte-Offset; INSERT OR REPLACE via ingest_seq (idempotent).
    Beschädigte Zeilen werden übersprungen.
    """
    if not ndjson_path.exists():
        set_sync_progress(conn, byte_offset=0, file_size=0, last_ingest_seq=0, complete=True)
        conn.commit()
        return {"imported": 0, "skipped": 0, "byte_offset": 0, "complete": True}

    file_size = ndjson_path.stat().st_size
    start_offset = get_sync_byte_offset(conn)
    if start_offset > file_size:
        # Datei wurde ersetzt/verkürzt → Neuaufbau
        conn.execute("DELETE FROM positions")
        start_offset = 0
        set_sync_progress(conn, byte_offset=0, file_size=file_size, last_ingest_seq=0, complete=False)
        conn.commit()

    if start_offset == file_size and is_sync_complete(conn):
        return {"imported": 0, "skipped": 0, "byte_offset": start_offset, "complete": True}

    imported = 0
    skipped = 0
    last_seq = 0
    offset = start_offset
    batch: list[dict[str, Any]] = []
    batches_since_commit = 0

    with ndjson_path.open("rb") as handle:
        # Offset wird nur an Zeilengrenzen gespeichert → Seek ohne Zeile zu verwerfen.
        if offset > 0:
            handle.seek(offset)

        while True:
            raw = handle.readline()
            if not raw:
                offset = handle.tell()
                break
            offset = handle.tell()
            text = raw.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            try:
                item = json.loads(text)
            except json.JSONDecodeError:
                skipped += 1
                continue
            if not isinstance(item, dict):
                skipped += 1
                continue
            row = item_to_db_row(item)
            if row is None:
                skipped += 1
                continue
            batch.append(item)
            last_seq = max(last_seq, int(row["ingest_seq"]))
            if len(batch) >= batch_size:
                imported += upsert_positions_many(conn, batch)
                batch.clear()
                batches_since_commit += 1
                if batches_since_commit >= progress_every_batches:
                    set_sync_progress(
                        conn,
                        byte_offset=offset,
                        file_size=file_size,
                        last_ingest_seq=last_seq,
                        complete=False,
                    )
                    conn.commit()
                    batches_since_commit = 0

        if batch:
            imported += upsert_positions_many(conn, batch)
            batch.clear()

    set_sync_progress(
        conn,
        byte_offset=offset,
        file_size=file_size,
        last_ingest_seq=last_seq if last_seq else None,
        complete=True,
    )
    conn.commit()
    return {
        "imported": imported,
        "skipped": skipped,
        "byte_offset": offset,
        "complete": True,
    }
