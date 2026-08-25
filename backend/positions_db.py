"""SQLite Abfrageindex für GPS-Positionen (NDJSON bleibt Source of Truth)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1

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


def query_positions(
    conn: sqlite3.Connection,
    device_names: list[str] | None,
    ts_from: str | None,
    ts_to: str | None,
    *,
    limit: int = 500,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], bool]:
    left = timestamp_to_epoch(ts_from)
    right = timestamp_to_epoch(ts_to)
    safe_limit = max(1, min(5000, int(limit)))
    safe_offset = max(0, int(offset))

    where: list[str] = []
    params: list[Any] = []

    normalized_device_names: set[str] | None = None
    if isinstance(device_names, list) and len(device_names) > 0:
        normalized_device_names = {str(name).strip().lower() for name in device_names if str(name).strip()}
        if not normalized_device_names:
            normalized_device_names = None

    if normalized_device_names is not None:
        placeholders = ",".join("?" for _ in normalized_device_names)
        where.append(f"device_name_lower IN ({placeholders})")
        params.extend(sorted(normalized_device_names))

    if left is not None or right is not None:
        where.append("timestamp_epoch IS NOT NULL")
        if left is not None:
            where.append("timestamp_epoch >= ?")
            params.append(left)
        if right is not None:
            where.append("timestamp_epoch <= ?")
            params.append(right)

    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    # limit+1 für effizientes has_more; Dateireihenfolge = ingest_seq
    sql = (
        "SELECT * FROM positions"
        f"{where_sql}"
        " ORDER BY ingest_seq ASC"
        " LIMIT ? OFFSET ?"
    )
    params.extend([safe_limit + 1, safe_offset])
    rows = conn.execute(sql, params).fetchall()
    has_more = len(rows) > safe_limit
    if has_more:
        rows = rows[:safe_limit]
    return [db_row_to_position(r) for r in rows], has_more


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
