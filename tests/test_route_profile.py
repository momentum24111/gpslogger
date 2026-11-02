"""Distanz und Höhenprofil unabhängig von der Karten-Punktdichte."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from backend.gpx_export import GPX_NAMESPACE, iter_gpx_chunks
from backend.route_profile import build_route_profile, haversine_meters
from backend.state import AppState


def _point(device_id, lat, lon, altitude=None, minute=0, name=None):
    stamp = f"2026-10-01T10:{minute:02d}:00+00:00"
    row = {
        "ingest_seq": minute + 1,
        "device_id": device_id,
        "device_name": name or device_id,
        "latitude": lat,
        "longitude": lon,
        "timestamp": stamp,
        "received_at": stamp,
        "speed": 12,
        "battery": 70,
    }
    if altitude is not None:
        row["altitude"] = altitude
    return row


def _sum_path(rows):
    total = 0.0
    previous = None
    for row in rows:
        current = (row["latitude"], row["longitude"])
        if previous is not None:
            total += haversine_meters(previous[0], previous[1], current[0], current[1])
        previous = current
    return total


def _gpx_distance(rows):
    xml_text = "".join(iter_gpx_chunks(rows, "vergleich"))
    root = ET.fromstring(xml_text)
    total = 0.0
    for track in root.findall(f".//{{{GPX_NAMESPACE}}}trk"):
        points = []
        for point in track.findall(f".//{{{GPX_NAMESPACE}}}trkpt"):
            points.append((float(point.attrib["lat"]), float(point.attrib["lon"])))
        previous = None
        for current in points:
            if previous is not None:
                total += haversine_meters(previous[0], previous[1], current[0], current[1])
            previous = current
    return total


class RouteProfileTests(unittest.TestCase):
    def test_curved_route_is_longer_than_every_tenth_point(self) -> None:
        rows = []
        for index in range(61):
            lat = 52.0 + (0.04 if index % 2 else 0.0)
            lon = 13.0 + index * 0.01
            rows.append(_point("dev1", lat, lon, altitude=100 + index, minute=index, name="Phone"))
        profile = build_route_profile(rows)
        thinned = [rows[index] for index in range(0, len(rows), 10)]
        if thinned[-1] is not rows[-1]:
            thinned.append(rows[-1])
        self.assertEqual(profile["point_count"], 61)
        self.assertAlmostEqual(profile["distance_m"], _sum_path(rows), delta=0.01)
        self.assertAlmostEqual(profile["distance_m"], _gpx_distance(rows), delta=0.01)
        self.assertGreater(profile["distance_m"], _sum_path(thinned) * 1.2)
        self.assertNotIn("speed", json.dumps(profile))

    def test_devices_are_not_joined(self) -> None:
        rows = [
            _point("a", 0.0, 0.0, altitude=10, minute=0, name="A"),
            _point("a", 0.0, 0.01, altitude=12, minute=1, name="A"),
            _point("b", 10.0, 0.0, altitude=20, minute=2, name="B"),
            _point("b", 10.0, 0.01, altitude=22, minute=3, name="B"),
        ]
        profile = build_route_profile(rows)
        own = haversine_meters(0.0, 0.0, 0.0, 0.01) + haversine_meters(10.0, 0.0, 10.0, 0.01)
        self.assertEqual(len(profile["devices"]), 2)
        self.assertAlmostEqual(profile["distance_m"], own, delta=0.01)
        self.assertLess(profile["distance_m"], 5_000)

    def test_missing_altitude_stays_a_gap_and_extreme_is_kept(self) -> None:
        rows = []
        for index in range(3000):
            altitude = None if index == 400 else (9000 if index == 1500 else 10)
            rows.append(_point("dev1", 52.0, 13.0 + index * 0.0001, altitude=altitude, minute=index % 60))
            rows[-1]["timestamp"] = f"2026-10-01T10:00:{index:05d}+00:00"
            rows[-1]["ingest_seq"] = index + 1
        profile = build_route_profile(rows, sample_limit=48)
        samples = profile["devices"][0]["samples"]
        self.assertLessEqual(len(samples), 48)
        self.assertTrue(any(sample["ele"] == 9000 for sample in samples))
        self.assertTrue(any(sample["ele"] is None for sample in samples))
        self.assertEqual(profile["point_count"], 3000)
        self.assertEqual(samples[0]["d"], 0)
        self.assertAlmostEqual(samples[-1]["d"], profile["distance_m"], delta=0.01)

    def test_invalid_coordinate_is_skipped_like_gpx(self) -> None:
        rows = [
            _point("dev1", 0.0, 0.0, altitude=5, minute=0),
            _point("dev1", 999, 0.0, altitude=5, minute=1),
            _point("dev1", 0.0, 0.02, altitude=0, minute=2),
        ]
        profile = build_route_profile(rows)
        self.assertEqual(profile["point_count"], 2)
        self.assertAlmostEqual(profile["distance_m"], haversine_meters(0.0, 0.0, 0.0, 0.02), delta=0.01)
        self.assertEqual(profile["devices"][0]["samples"][-1]["ele"], 0)


class RouteProfileStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="gpslogger_profile_"))
        self.data = self.tmp / "data"
        self.data.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_database_profile_ignores_map_stride(self) -> None:
        items = []
        for index in range(40):
            items.append(
                {
                    "ingest_seq": index + 1,
                    "device_id": "dev1",
                    "device_name": "Phone",
                    "latitude": 48.0 + (0.03 if index % 2 else 0.0),
                    "longitude": 11.0 + index * 0.01,
                    "altitude": 200 + index,
                    "timestamp": f"2026-10-02T08:{index:02d}:00+00:00",
                    "received_at": f"2026-10-02T08:{index:02d}:00+00:00",
                }
            )
        with (self.data / "gps.ndjson").open("w", encoding="utf-8") as handle:
            for item in items:
                handle.write(json.dumps(item) + "\n")
        state = AppState(self.tmp)
        left = "2026-10-02T00:00:00+00:00"
        right = "2026-10-03T00:00:00+00:00"
        thinned, _has_more = state.query_positions(["Phone"], left, right, limit=5000, stride=10)
        profile = build_route_profile(state.iter_gpx_positions(["dev1"], left, right))
        thinned_distance = 0.0
        previous = None
        for row in thinned:
            current = (row["latitude"], row["longitude"])
            if previous is not None:
                thinned_distance += haversine_meters(previous[0], previous[1], current[0], current[1])
            previous = current
        self.assertEqual(profile["point_count"], 40)
        self.assertLess(len(thinned), 40)
        self.assertGreater(profile["distance_m"], thinned_distance)
        self.assertAlmostEqual(profile["distance_m"], _sum_path(items), delta=0.01)
        self.assertEqual(list(self.tmp.rglob("*.gpx")), [])


if __name__ == "__main__":
    unittest.main()
