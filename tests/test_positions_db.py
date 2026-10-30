"""Tests für SQLite Positionsindex und /api/positions-kompatible Abfragen."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from datetime import datetime, timedelta, timezone

from backend.openapi_spec import build_openapi_spec
from backend.state import AppState, ConfigFieldError
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


def _expected_stride_count(count: int, stride: int) -> int:
    if count <= 0:
        return 0
    if stride <= 1:
        return count
    keep = set(range(0, count, stride))
    keep.add(count - 1)
    return len(keep)


def _iso_at(index: int) -> str:
    base = datetime(2024, 6, 1, tzinfo=timezone.utc) + timedelta(seconds=index)
    return base.strftime("%Y-%m-%dT%H:%M:%S+00:00")


class MapPointStrideTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="gpslogger_stride_"))
        self.data = self.tmp / "data"
        self.data.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _range(self) -> tuple[str, str]:
        return ("2024-06-01T00:00:00+00:00", "2024-06-03T00:00:00+00:00")

    def test_parse_position_stride_keeps_full_resolution_without_value(self) -> None:
        self.assertIsNone(positions_db.parse_position_stride(None))
        self.assertIsNone(positions_db.parse_position_stride(""))
        self.assertIsNone(positions_db.parse_position_stride("1"))
        self.assertEqual(positions_db.parse_position_stride("20"), 20)
        with self.assertRaises(ValueError):
            positions_db.parse_position_stride("3")
        with self.assertRaises(ValueError):
            positions_db.parse_position_stride("abc")

    def test_stride_omitted_returns_every_point(self) -> None:
        items = [_sample_item(i, timestamp=_iso_at(i)) for i in range(1, 12)]
        _write_ndjson(self.data / "gps.ndjson", items)
        state = AppState(self.tmp)
        left, right = self._range()
        full, more_full = state.query_positions(None, left, right, limit=500)
        explicit, more_explicit = state.query_positions(None, left, right, limit=500, stride=1)
        self.assertEqual(len(full), 11)
        self.assertFalse(more_full)
        self.assertEqual(full, explicit)
        self.assertEqual(more_full, more_explicit)
        conn = positions_db.connect(state.gps_db_path)
        try:
            self.assertEqual(positions_db.count_positions(conn), 11)
        finally:
            conn.close()

    def test_keeps_first_and_last_and_thins_per_device(self) -> None:
        items = []
        seq = 1
        for index in range(20):
            items.append(
                _sample_item(
                    seq,
                    device_name="Alpha",
                    device_id="dev-a",
                    timestamp=_iso_at(index * 2),
                    lat=50 + index / 1000,
                )
            )
            seq += 1
            items.append(
                _sample_item(
                    seq,
                    device_name="Beta",
                    device_id="dev-b",
                    timestamp=_iso_at(index * 2 + 1),
                    lat=40 + index / 1000,
                )
            )
            seq += 1
        path = self.data / "gps.ndjson"
        _write_ndjson(path, items)
        raw = path.read_bytes()
        state = AppState(self.tmp)
        left, right = self._range()
        conn = positions_db.connect(state.gps_db_path)
        try:
            rows, has_more = positions_db.query_positions(conn, None, left, right, limit=500, stride=10)
        finally:
            conn.close()
        self.assertFalse(has_more)
        self.assertEqual(len(rows), 6)
        by_device: dict[str, list[dict]] = {}
        for row in rows:
            by_device.setdefault(str(row["device_id"]), []).append(row)
        self.assertEqual(set(by_device), {"dev-a", "dev-b"})
        self.assertEqual(by_device["dev-a"][0]["timestamp"], _iso_at(0))
        self.assertEqual(by_device["dev-a"][-1]["timestamp"], _iso_at(38))
        self.assertEqual(by_device["dev-b"][0]["timestamp"], _iso_at(1))
        self.assertEqual(by_device["dev-b"][-1]["timestamp"], _iso_at(39))
        self.assertNotIn("_sample_rn", rows[0])
        ndjson_rows, ndjson_more = state._query_positions_from_ndjson(None, left, right, limit=500, stride=10)
        self.assertFalse(ndjson_more)
        self.assertEqual([row["timestamp"] for row in ndjson_rows], [row["timestamp"] for row in rows])
        self.assertEqual(path.read_bytes(), raw)
        conn = positions_db.connect(state.gps_db_path)
        try:
            self.assertEqual(positions_db.count_positions(conn), 40)
        finally:
            conn.close()

    def test_out_of_order_timestamps_keep_chronological_ends(self) -> None:
        times = [
            "2024-06-01T12:00:00+00:00",
            "2024-06-01T10:00:00+00:00",
            "2024-06-01T14:00:00+00:00",
            "2024-06-01T11:00:00+00:00",
            "2024-06-01T13:00:00+00:00",
        ]
        items = [_sample_item(index + 1, timestamp=stamp) for index, stamp in enumerate(times)]
        _write_ndjson(self.data / "gps.ndjson", items)
        state = AppState(self.tmp)
        rows, _ = state.query_positions(
            None,
            "2024-06-01T00:00:00+00:00",
            "2024-06-02T00:00:00+00:00",
            stride=100,
        )
        stamps = [row["timestamp"] for row in rows]
        self.assertEqual(stamps, ["2024-06-01T10:00:00+00:00", "2024-06-01T14:00:00+00:00"])

    def test_stride_pagination_applies_after_thinning(self) -> None:
        items = [_sample_item(i, timestamp=_iso_at(i)) for i in range(1, 26)]
        _write_ndjson(self.data / "gps.ndjson", items)
        state = AppState(self.tmp)
        left, right = self._range()
        page1, more1 = state.query_positions(None, left, right, limit=2, offset=0, stride=10)
        page2, more2 = state.query_positions(None, left, right, limit=2, offset=2, stride=10)
        self.assertTrue(more1)
        self.assertEqual(len(page1), 2)
        self.assertFalse(more2)
        self.assertEqual(len(page2), 2)
        self.assertEqual(_expected_stride_count(25, 10), 4)
        self.assertEqual(page1[0]["timestamp"], _iso_at(1))
        self.assertEqual(page2[-1]["timestamp"], _iso_at(25))

    def test_large_range_returns_about_one_twentieth_without_deleting(self) -> None:
        count = 10000
        items = [_sample_item(i, timestamp=_iso_at(i), lat=52 + (i / 100000), lon=13 + (i / 100000)) for i in range(1, count + 1)]
        state = AppState(self.tmp)
        conn = positions_db.connect(state.gps_db_path)
        try:
            positions_db.upsert_positions_many(conn, items)
            conn.commit()
            stored = positions_db.count_positions(conn)
            left, right = self._range()
            started = datetime.now(timezone.utc)
            thinned, has_more = positions_db.query_positions(conn, None, left, right, limit=5000, stride=20)
            elapsed = (datetime.now(timezone.utc) - started).total_seconds()
            full_page, full_more = positions_db.query_positions(conn, None, left, right, limit=5000, offset=0)
        finally:
            conn.close()
        self.assertEqual(stored, count)
        self.assertFalse(has_more)
        self.assertEqual(len(thinned), _expected_stride_count(count, 20))
        self.assertEqual(len(thinned), 501)
        self.assertEqual(thinned[0]["timestamp"], _iso_at(1))
        self.assertEqual(thinned[-1]["timestamp"], _iso_at(count))
        self.assertLess(elapsed, 5.0)
        self.assertEqual(len(full_page), 5000)
        self.assertTrue(full_more)
        conn = positions_db.connect(state.gps_db_path)
        try:
            self.assertEqual(positions_db.count_positions(conn), count)
        finally:
            conn.close()

    def test_map_point_stride_setting_persists_and_rejects_invalid(self) -> None:
        state = AppState(self.tmp)
        self.assertEqual(state.get_settings()["map_point_stride"], 10)
        updated = state.update_settings({"map_point_stride": 50})
        self.assertEqual(updated["map_point_stride"], 50)
        reloaded = AppState(self.tmp)
        self.assertEqual(reloaded.get_settings()["map_point_stride"], 50)
        with self.assertRaises(ConfigFieldError) as caught:
            reloaded.update_settings({"map_point_stride": 7})
        self.assertEqual(caught.exception.error_key, "settings.system.error.mapPointStrideInvalid")
        self.assertEqual(reloaded.get_settings()["map_point_stride"], 50)

    def test_invalid_stored_stride_falls_back_to_default(self) -> None:
        (self.data / "settings.json").write_text(json.dumps({"map_point_stride": 7}), encoding="utf-8")
        state = AppState(self.tmp)
        self.assertEqual(state.get_settings()["map_point_stride"], 10)
        stored = json.loads((self.data / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["map_point_stride"], 10)

    def test_openapi_stride_is_optional(self) -> None:
        spec = build_openapi_spec()
        parameters = spec["paths"]["/api/positions"]["get"]["parameters"]
        stride = next(item for item in parameters if item["name"] == "stride")
        self.assertFalse(stride.get("required", False))
        self.assertEqual(stride["schema"]["enum"], [1, 2, 5, 10, 20, 50, 100])
        required = {"from", "to", "limit", "offset"}
        names = {item["name"] for item in parameters}
        self.assertTrue(required.issubset(names))
        filters = spec["components"]["schemas"]["PositionsResponse"]["properties"]["filters"]
        self.assertEqual(filters["required"], ["from", "to", "device"])
        self.assertIn("stride", filters["properties"])


if __name__ == "__main__":
    unittest.main()
