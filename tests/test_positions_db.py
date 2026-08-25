"""Tests für SQLite Positionsindex und /api/positions-kompatible Abfragen."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from backend.state import AppState
from backend import positions_db


def _write_ndjson(path: Path, items: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")


def _sample_item(
    seq: int,
    *,
    device_name: str = "Phone",
    device_id: str = "dev1",
    lat: float = 52.5,
    lon: float = 13.4,
    timestamp: str = "2024-06-01T12:00:00+00:00",
    **extra,
) -> dict:
    row = {
        "ingest_seq": seq,
        "device_id": device_id,
        "device_name": device_name,
        "latitude": lat,
        "longitude": lon,
        "accuracy": 10.0,
        "timestamp": timestamp,
        "received_at": timestamp,
        "ingest_route": "/api/current-location",
        "battery": 80.0,
        "speed": 1.5,
        "headers": {"Authorization": "Bearer secret"},
        "replay_request": {"method": "POST", "body": "huge"},
    }
    row.update(extra)
    return row


class PositionsDbMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="gpslogger_test_"))
        self.data = self.tmp / "data"
        self.data.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_migration_imports_ndjson_positions(self) -> None:
        items = [
            _sample_item(1, timestamp="2024-06-01T10:00:00+00:00"),
            _sample_item(2, timestamp="2024-06-01T11:00:00+00:00", device_name="Tablet", device_id="dev2"),
            _sample_item(3, timestamp="2024-06-01T12:00:00+00:00"),
        ]
        _write_ndjson(self.data / "gps.ndjson", items)
        state = AppState(self.tmp)
        self.assertTrue(state._positions_db_ready)
        self.assertTrue(state.gps_db_path.exists())
        conn = positions_db.connect(state.gps_db_path)
        try:
            self.assertEqual(positions_db.count_positions(conn), 3)
            self.assertTrue(positions_db.is_sync_complete(conn))
        finally:
            conn.close()

    def test_restart_does_not_duplicate(self) -> None:
        items = [_sample_item(i, timestamp=f"2024-06-01T{10+i:02d}:00:00+00:00") for i in range(1, 6)]
        _write_ndjson(self.data / "gps.ndjson", items)
        AppState(self.tmp)
        state2 = AppState(self.tmp)
        conn = positions_db.connect(state2.gps_db_path)
        try:
            self.assertEqual(positions_db.count_positions(conn), 5)
        finally:
            conn.close()
        rows, has_more = state2.query_positions(None, "2024-06-01T00:00:00+00:00", "2024-06-02T00:00:00+00:00")
        self.assertEqual(len(rows), 5)
        self.assertFalse(has_more)

    def test_invalid_ndjson_lines_skipped(self) -> None:
        path = self.data / "gps.ndjson"
        with path.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(_sample_item(1)) + "\n")
            handle.write("{not-json\n")
            handle.write("null\n")
            handle.write(json.dumps({"ingest_seq": 2, "latitude": "x", "longitude": 1}) + "\n")
            handle.write(json.dumps(_sample_item(3, timestamp="2024-06-01T13:00:00+00:00")) + "\n")
        state = AppState(self.tmp)
        rows, _ = state.query_positions(None, "2024-01-01T00:00:00+00:00", "2025-01-01T00:00:00+00:00")
        self.assertEqual(len(rows), 2)
        self.assertEqual([r["device_name"] for r in rows], ["Phone", "Phone"])

    def test_time_filter(self) -> None:
        items = [
            _sample_item(1, timestamp="2024-06-01T10:00:00+00:00"),
            _sample_item(2, timestamp="2024-06-01T12:00:00+00:00"),
            _sample_item(3, timestamp="2024-06-01T14:00:00+00:00"),
        ]
        _write_ndjson(self.data / "gps.ndjson", items)
        state = AppState(self.tmp)
        rows, has_more = state.query_positions(
            None,
            "2024-06-01T11:00:00+00:00",
            "2024-06-01T13:00:00+00:00",
        )
        self.assertFalse(has_more)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["timestamp"], "2024-06-01T12:00:00+00:00")

    def test_device_filter_case_insensitive(self) -> None:
        items = [
            _sample_item(1, device_name="Alpha", device_id="a"),
            _sample_item(2, device_name="Beta", device_id="b"),
            _sample_item(3, device_name="alpha", device_id="a2"),
        ]
        _write_ndjson(self.data / "gps.ndjson", items)
        state = AppState(self.tmp)
        rows, _ = state.query_positions(
            ["ALPHA"],
            "2024-01-01T00:00:00+00:00",
            "2025-01-01T00:00:00+00:00",
        )
        self.assertEqual(len(rows), 2)
        names = {r["device_name"] for r in rows}
        self.assertEqual(names, {"Alpha", "alpha"})

    def test_pagination_and_has_more(self) -> None:
        items = [
            _sample_item(i, timestamp=f"2024-06-01T{i:02d}:00:00+00:00")
            for i in range(1, 8)
        ]
        _write_ndjson(self.data / "gps.ndjson", items)
        state = AppState(self.tmp)
        page1, more1 = state.query_positions(
            None,
            "2024-06-01T00:00:00+00:00",
            "2024-06-02T00:00:00+00:00",
            limit=3,
            offset=0,
        )
        page2, more2 = state.query_positions(
            None,
            "2024-06-01T00:00:00+00:00",
            "2024-06-02T00:00:00+00:00",
            limit=3,
            offset=3,
        )
        page3, more3 = state.query_positions(
            None,
            "2024-06-01T00:00:00+00:00",
            "2024-06-02T00:00:00+00:00",
            limit=3,
            offset=6,
        )
        self.assertTrue(more1)
        self.assertEqual(len(page1), 3)
        self.assertTrue(more2)
        self.assertEqual(len(page2), 3)
        self.assertFalse(more3)
        self.assertEqual(len(page3), 1)
        # Reihenfolge = ingest_seq / Dateireihenfolge
        self.assertEqual(
            [r["timestamp"] for r in page1 + page2 + page3],
            [f"2024-06-01T{i:02d}:00:00+00:00" for i in range(1, 8)],
        )

    def test_store_after_migration_keeps_sync(self) -> None:
        items = [_sample_item(1, timestamp="2024-06-01T10:00:00+00:00")]
        _write_ndjson(self.data / "gps.ndjson", items)
        (self.data / "ingest_seq_next.json").write_text(
            json.dumps({"next": 2}), encoding="utf-8"
        )
        state = AppState(self.tmp)
        state.store_gps_request(
            {
                "device_id": "dev1",
                "device_name": "Phone",
                "latitude": 52.6,
                "longitude": 13.5,
                "accuracy": 5,
                "timestamp": "2024-06-01T15:00:00+00:00",
                "received_at": "2024-06-01T15:00:00+00:00",
            }
        )
        rows, _ = state.query_positions(
            None,
            "2024-06-01T00:00:00+00:00",
            "2024-06-02T00:00:00+00:00",
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[-1]["latitude"], 52.6)
        # NDJSON unverändert als Source of Truth weitergeschrieben
        lines = [ln for ln in (self.data / "gps.ndjson").read_text(encoding="utf-8").splitlines() if ln.strip()]
        self.assertEqual(len(lines), 2)
        # Neustart ohne Duplikate
        state2 = AppState(self.tmp)
        rows2, _ = state2.query_positions(
            None,
            "2024-06-01T00:00:00+00:00",
            "2024-06-02T00:00:00+00:00",
        )
        self.assertEqual(len(rows2), 2)

    def test_api_row_shape_matches_position_row(self) -> None:
        item = _sample_item(
            1,
            device="PhoneRaw",
            altitude=42.0,
            provider="gps",
            activity="walking",
            time="2024-06-01T12:00:00+00:00",
        )
        _write_ndjson(self.data / "gps.ndjson", [item])
        state = AppState(self.tmp)
        rows, _ = state.query_positions(
            None,
            "2024-06-01T00:00:00+00:00",
            "2024-06-02T00:00:00+00:00",
        )
        expected = state._position_row_from_stored(item)
        self.assertIsNotNone(expected)
        self.assertEqual(set(rows[0].keys()), set(expected.keys()))
        for key in expected:
            self.assertEqual(rows[0][key], expected[key], msg=key)
        # Keine Rohdaten in der API-Antwort
        self.assertNotIn("headers", rows[0])
        self.assertNotIn("replay_request", rows[0])

    def test_interrupted_sync_resumable(self) -> None:
        items = [_sample_item(i, timestamp=f"2024-06-01T{i:02d}:00:00+00:00") for i in range(1, 6)]
        path = self.data / "gps.ndjson"
        _write_ndjson(path, items)
        db_path = self.data / "gps_positions.sqlite3"
        conn = positions_db.connect(db_path)
        try:
            positions_db.init_schema(conn)
            # Nur ersten Teil importieren und Offset mittendrin speichern
            with path.open("rb") as handle:
                handle.readline()
                handle.readline()
                mid = handle.tell()
            positions_db.upsert_position(conn, items[0])
            positions_db.upsert_position(conn, items[1])
            positions_db.set_sync_progress(
                conn, byte_offset=mid, file_size=path.stat().st_size, last_ingest_seq=2, complete=False
            )
            conn.commit()
        finally:
            conn.close()
        state = AppState(self.tmp)
        rows, _ = state.query_positions(
            None,
            "2024-06-01T00:00:00+00:00",
            "2024-06-02T00:00:00+00:00",
        )
        self.assertEqual(len(rows), 5)


class PositionsApiStructureTests(unittest.TestCase):
    """Prüft die vom Server erwartete Response-Struktur (ohne HTTP)."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="gpslogger_api_"))
        self.data = self.tmp / "data"
        self.data.mkdir(parents=True)
        items = [_sample_item(1), _sample_item(2, timestamp="2024-06-01T13:00:00+00:00")]
        _write_ndjson(self.data / "gps.ndjson", items)
        self.state = AppState(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_positions_response_shape(self) -> None:
        device_names = ["Phone"]
        query_from = "2024-06-01T00:00:00+00:00"
        query_to = "2024-06-02T00:00:00+00:00"
        limit = 500
        offset = 0
        rows, has_more = self.state.query_positions(
            device_names=device_names,
            ts_from=query_from,
            ts_to=query_to,
            limit=limit,
            offset=offset,
        )
        payload = {
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
        }
        self.assertIn("positions", payload)
        self.assertIn("pagination", payload)
        self.assertIn("filters", payload)
        self.assertEqual(
            set(payload["pagination"].keys()),
            {"limit", "offset", "returned", "has_more"},
        )
        self.assertEqual(payload["pagination"]["returned"], 2)
        self.assertFalse(payload["pagination"]["has_more"])
        self.assertEqual(payload["filters"]["device"], ["Phone"])


if __name__ == "__main__":
    unittest.main()
