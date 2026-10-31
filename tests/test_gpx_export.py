"""GPX-Export: vollständige Punkte, getrennte Tracks, kein Datei-Rest."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.gpx_export import (
    GPX_NAMESPACE,
    GpxExportEmpty,
    content_disposition,
    gpx_filename,
    iter_gpx_chunks,
)
from backend.openapi_spec import build_openapi_spec
from backend.state import AppState


NS = {"gpx": GPX_NAMESPACE}


def _write_ndjson(path: Path, items: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")


def _item(
    seq: int,
    *,
    device_id: str = "dev1",
    device_name: str = "Phone",
    lat: float = 52.5,
    lon: float = 13.4,
    timestamp: str = "2026-10-01T12:00:00+00:00",
    altitude: float | None = None,
) -> dict:
    row = {
        "ingest_seq": seq,
        "device_id": device_id,
        "device_name": device_name,
        "latitude": lat,
        "longitude": lon,
        "accuracy": 8.0,
        "timestamp": timestamp,
        "received_at": timestamp,
        "battery": 80.0,
        "speed": 3.5,
        "headers": {"Authorization": "Bearer secret"},
    }
    if altitude is not None:
        row["altitude"] = altitude
    return row


def _gpx_text(rows: list[dict], name: str = "Export") -> str:
    return "".join(iter_gpx_chunks(rows, name))


def _points(xml_text: str) -> list[ET.Element]:
    root = ET.fromstring(xml_text)
    return root.findall(".//gpx:trkpt", NS)


class GpxDocumentTests(unittest.TestCase):
    def test_empty_raises_before_any_chunk(self) -> None:
        chunks = iter_gpx_chunks([], "leer")
        with self.assertRaises(GpxExportEmpty):
            next(chunks)

    def test_single_point_is_valid_gpx(self) -> None:
        xml_text = _gpx_text(
            [
                {
                    "device_id": "dev1",
                    "device_name": "Phone",
                    "latitude": 52.5,
                    "longitude": 13.4,
                    "timestamp": "2026-10-01T12:00:00+02:00",
                    "altitude": 0,
                    "speed": 9,
                    "battery": "50%",
                }
            ]
        )
        root = ET.fromstring(xml_text)
        self.assertEqual(root.tag, f"{{{GPX_NAMESPACE}}}gpx")
        self.assertEqual(root.attrib.get("version"), "1.1")
        points = _points(xml_text)
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0].attrib["lat"], "52.5")
        self.assertEqual(points[0].attrib["lon"], "13.4")
        ele = points[0].find("gpx:ele", NS)
        self.assertIsNotNone(ele)
        self.assertEqual(ele.text, "0")
        stamp = points[0].find("gpx:time", NS)
        self.assertIsNotNone(stamp)
        self.assertEqual(stamp.text, "2026-10-01T10:00:00Z")
        self.assertNotIn("speed", xml_text)
        self.assertNotIn("battery", xml_text)

    def test_missing_altitude_and_invalid_coordinates(self) -> None:
        xml_text = _gpx_text(
            [
                {
                    "device_id": "dev1",
                    "device_name": "A & <B>",
                    "latitude": 999,
                    "longitude": 13.4,
                    "timestamp": "2026-10-01T12:00:00Z",
                },
                {
                    "device_id": "dev1",
                    "device_name": "A & <B>",
                    "latitude": 48.1,
                    "longitude": 11.5,
                    "timestamp": "not-a-time",
                },
            ]
        )
        points = _points(xml_text)
        self.assertEqual(len(points), 1)
        self.assertIsNone(points[0].find("gpx:ele", NS))
        self.assertIsNone(points[0].find("gpx:time", NS))
        self.assertIn("A &amp; &lt;B&gt;", xml_text)

    def test_devices_stay_in_separate_tracks(self) -> None:
        xml_text = _gpx_text(
            [
                {
                    "device_id": "a",
                    "device_name": "Alpha",
                    "latitude": 48.1,
                    "longitude": 11.5,
                    "timestamp": "2026-10-01T11:00:00Z",
                },
                {
                    "device_id": "a",
                    "device_name": "Alpha",
                    "latitude": 48.4,
                    "longitude": 11.8,
                    "timestamp": "2026-10-01T13:00:00Z",
                },
                {
                    "device_id": "b",
                    "device_name": "Bravo",
                    "latitude": 48.2,
                    "longitude": 11.6,
                    "timestamp": "2026-10-01T10:00:00Z",
                },
                {
                    "device_id": "b",
                    "device_name": "Bravo",
                    "latitude": 48.3,
                    "longitude": 11.7,
                    "timestamp": "2026-10-01T12:00:00Z",
                },
            ]
        )
        root = ET.fromstring(xml_text)
        tracks = root.findall("gpx:trk", NS)
        self.assertEqual(len(tracks), 2)
        names = [track.findtext("gpx:name", default="", namespaces=NS) for track in tracks]
        self.assertEqual(names, ["Alpha", "Bravo"])
        counts = [len(track.findall(".//gpx:trkpt", NS)) for track in tracks]
        self.assertEqual(counts, [2, 2])

    def test_filename_and_header(self) -> None:
        self.assertEqual(
            gpx_filename(filename_from="2026-10-01", filename_to="2026-10-31"),
            "GPSLogger_2026-10-01_2026-10-31.gpx",
        )
        self.assertEqual(
            gpx_filename(device_label="Phone", filename_from="2026-10-01", filename_to="2026-10-31"),
            "GPSLogger_Phone_2026-10-01_2026-10-31.gpx",
        )
        self.assertEqual(gpx_filename(device_label="Phone", current=True), "GPSLogger_Phone_aktuell.gpx")
        hostile = gpx_filename(
            device_label="../../etc/passwd",
            filename_from="2026-10-01",
            filename_to="2026-10-01",
        )
        self.assertTrue(hostile.endswith(".gpx"))
        self.assertNotIn("/", hostile)
        self.assertNotIn("\\", hostile)
        self.assertNotIn("..", hostile)
        header = content_disposition("GPSLogger_2026-10-01_2026-10-31.gpx")
        self.assertIn("attachment;", header)
        self.assertIn('filename="GPSLogger_2026-10-01_2026-10-31.gpx"', header)
        self.assertIn("filename*=UTF-8''", header)

    def test_large_stream_counts_every_point(self) -> None:
        total = 4000

        def rows():
            for index in range(total):
                yield {
                    "device_id": "dev1",
                    "device_name": "Phone",
                    "latitude": 50 + (index % 100) / 1000,
                    "longitude": 8 + (index % 50) / 1000,
                    "timestamp": "2026-10-01T12:00:00Z",
                    "speed": 1,
                }

        count = 0
        pieces = 0
        for chunk in iter_gpx_chunks(rows(), "viel"):
            pieces += 1
            count += chunk.count("<trkpt ")
        self.assertEqual(count, total)
        self.assertGreater(pieces, 1)


class GpxStateExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="gpslogger_gpx_"))
        self.data = self.tmp / "data"
        self.data.mkdir(parents=True)
        devices = [
            {
                "id": "dev1",
                "name": "Wander & Tour",
                "api_key": "secret-key",
                "created_at": "2026-10-01T00:00:00+00:00",
                "map_color_index": 0,
            },
            {
                "id": "dev2",
                "name": "Zweitgerät",
                "api_key": "other-secret",
                "created_at": "2026-10-01T00:00:00+00:00",
                "map_color_index": 1,
            },
        ]
        (self.data / "devices.json").write_text(json.dumps(devices), encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _load(self, items: list[dict]) -> AppState:
        _write_ndjson(self.data / "gps.ndjson", items)
        return AppState(self.tmp)

    def test_export_ignores_map_stride_and_keeps_devices_apart(self) -> None:
        start = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)
        items = []
        seq = 1
        for index in range(30):
            stamp = (start + timedelta(minutes=index)).isoformat()
            device_id = "dev1" if index % 2 == 0 else "dev2"
            device_name = "Wander & Tour" if device_id == "dev1" else "Zweitgerät"
            altitude = 120.0 if index % 3 == 0 else None
            items.append(
                _item(
                    seq,
                    device_id=device_id,
                    device_name=device_name,
                    lat=52.0 + index / 1000,
                    lon=13.0 + index / 1000,
                    timestamp=stamp,
                    altitude=altitude,
                )
            )
            seq += 1
        items.append(
            _item(seq, device_id="dev1", device_name="Wander & Tour", lat=999, lon=13.4, timestamp=start.isoformat())
        )
        state = self._load(items)
        left = "2026-10-01T00:00:00+00:00"
        right = "2026-10-02T00:00:00+00:00"
        thinned, _has_more = state.query_positions(
            ["Wander & Tour", "Zweitgerät"],
            left,
            right,
            limit=5000,
            stride=10,
        )
        exported = list(state.iter_gpx_positions(["dev1", "dev2"], left, right))
        self.assertLess(len(thinned), 30)
        self.assertEqual(len(exported), 30)
        self.assertTrue(all(-90 <= row["latitude"] <= 90 for row in exported))
        xml_text = "".join(iter_gpx_chunks(exported, "GPSLogger_2026-10-01_2026-10-01"))
        root = ET.fromstring(xml_text)
        tracks = root.findall("gpx:trk", NS)
        self.assertEqual(len(tracks), 2)
        self.assertEqual(
            [track.findtext("gpx:name", default="", namespaces=NS) for track in tracks],
            ["Wander & Tour", "Zweitgerät"],
        )
        self.assertIn("Wander &amp; Tour", xml_text)
        self.assertNotIn("secret-key", xml_text)
        self.assertNotIn("battery", xml_text)
        self.assertNotIn("speed", xml_text)
        self.assertEqual(list(self.tmp.rglob("*.gpx")), [])
        self.assertEqual(state.gpx_device_label(["dev1"]), "Wander & Tour")
        self.assertIsNone(state.gpx_device_label(["dev1", "dev2"]))

    def test_current_scope_exports_one_point_per_device(self) -> None:
        items = [
            _item(1, timestamp="2026-10-01T10:00:00+00:00", lat=52.1),
            _item(2, device_id="dev2", device_name="Zweitgerät", timestamp="2026-10-01T11:00:00+00:00", lat=48.1),
            _item(3, timestamp="2026-10-01T12:00:00+00:00", lat=52.9, altitude=42),
        ]
        state = self._load(items)
        rows = list(state.iter_current_gpx_positions(["dev2", "dev1"]))
        self.assertEqual([row["device_id"] for row in rows], ["dev2", "dev1"])
        self.assertEqual(rows[1]["latitude"], 52.9)
        self.assertEqual(rows[1]["altitude"], 42)
        xml_text = "".join(iter_gpx_chunks(rows, "aktuell"))
        self.assertEqual(len(_points(xml_text)), 2)

    def test_ndjson_fallback_when_index_is_missing(self) -> None:
        items = [
            _item(1, timestamp="2026-10-01T10:00:00+00:00"),
            _item(2, timestamp="2026-10-01T11:00:00+00:00", lat=52.6),
        ]
        state = self._load(items)
        state.gps_db_path.unlink()
        state._positions_db_ready = False
        rows = list(
            state.iter_gpx_positions(
                ["dev1"],
                "2026-10-01T00:00:00+00:00",
                "2026-10-02T00:00:00+00:00",
            )
        )
        self.assertEqual(len(rows), 2)

    def test_openapi_adds_gpx_without_changing_positions(self) -> None:
        spec = build_openapi_spec()
        position_params = spec["paths"]["/api/positions"]["get"]["parameters"]
        stride = next(item for item in position_params if item["name"] == "stride")
        self.assertFalse(stride.get("required", False))
        gpx = spec["paths"]["/api/positions/gpx"]["get"]
        self.assertEqual(gpx["responses"]["200"]["content"]["application/gpx+xml"]["schema"]["format"], "binary")
        self.assertFalse(any(item["name"] == "stride" for item in gpx["parameters"]))


if __name__ == "__main__":
    unittest.main()
