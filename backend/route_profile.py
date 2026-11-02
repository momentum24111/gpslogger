"""Volle Streckendistanz und ein reduziertes Höhenprofil.

Die Karten-Punktdichte bleibt unberücksichtigt. Die Distanz ist die Summe der
direkten geografischen Abstände aufeinanderfolgender gültiger Messpunkte je
Gerät. Geräte werden nicht miteinander verbunden.
"""

from __future__ import annotations

import math
from typing import Any, Iterable

from .gpx_export import finite_coordinate, optional_altitude, track_key, track_name

EARTH_RADIUS_M = 6371000.0
DEFAULT_PROFILE_SAMPLES = 1500


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Gleiche Kugelformel wie die Kartenansicht, Radius 6371 km."""
    rad = math.pi / 180.0
    d_lat = (lat2 - lat1) * rad
    d_lon = (lon2 - lon1) * rad
    sin_d_lat = math.sin(d_lat / 2.0)
    sin_d_lon = math.sin(d_lon / 2.0)
    a = sin_d_lat * sin_d_lat + math.cos(lat1 * rad) * math.cos(lat2 * rad) * sin_d_lon * sin_d_lon
    return EARTH_RADIUS_M * (2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a))))


def build_route_profile(rows: Iterable[dict[str, Any]], sample_limit: int = DEFAULT_PROFILE_SAMPLES) -> dict[str, Any]:
    """Erwartet Punkte je Gerät zusammenhängend und chronologisch."""
    limit = max(8, int(sample_limit))
    devices: list[dict[str, Any]] = []
    current_key: str | None = None
    current_rows: list[dict[str, Any]] = []

    def flush() -> None:
        if not current_rows:
            return
        devices.append(_device_profile(current_rows, limit))

    for row in rows:
        if not isinstance(row, dict):
            continue
        key = track_key(row)
        if current_key is None:
            current_key = key
        elif key != current_key:
            flush()
            current_rows = []
            current_key = key
        current_rows.append(row)
    flush()
    return {
        "distance_m": sum(device["distance_m"] for device in devices),
        "point_count": sum(device["point_count"] for device in devices),
        "devices": devices,
    }


def _device_profile(rows: list[dict[str, Any]], sample_limit: int) -> dict[str, Any]:
    series: list[tuple[float, float, float, float | None]] = []
    previous: tuple[float, float] | None = None
    distance = 0.0
    for row in rows:
        lat = finite_coordinate(row.get("latitude"), -90.0, 90.0)
        lon = finite_coordinate(row.get("longitude"), -180.0, 180.0)
        if lat is None or lon is None:
            continue
        if previous is not None:
            distance += haversine_meters(previous[0], previous[1], lat, lon)
        series.append((distance, lat, lon, optional_altitude(row.get("altitude"))))
        previous = (lat, lon)
    samples = [_sample(point) for point in _downsample(series, sample_limit)]
    return {
        "device_id": str(rows[0].get("device_id") or "").strip(),
        "device_name": track_name(rows[0]),
        "distance_m": distance,
        "point_count": len(series),
        "samples": samples,
    }


def _sample(point: tuple[float, float, float, float | None]) -> dict[str, Any]:
    return {"d": point[0], "lat": point[1], "lon": point[2], "ele": point[3]}


def _downsample(
    points: list[tuple[float, float, float, float | None]],
    limit: int,
) -> list[tuple[float, float, float, float | None]]:
    """Behält Anfang, Ende und Höhenextrema. Fehlende Höhen bleiben Lücken."""
    count = len(points)
    if count <= limit:
        return list(points)
    chosen = {0, count - 1}
    span = points[-1][0] - points[0][0]
    if span <= 0:
        finite = [index for index, point in enumerate(points) if point[3] is not None]
        if finite:
            chosen.add(min(finite, key=lambda index: points[index][3]))
            chosen.add(max(finite, key=lambda index: points[index][3]))
        return [points[index] for index in sorted(chosen)]

    bucket_count = max(1, limit // 3)
    width = span / bucket_count
    buckets: list[list[int]] = [[] for _ in range(bucket_count)]
    for index in range(1, count - 1):
        bucket_index = min(bucket_count - 1, int((points[index][0] - points[0][0]) / width))
        buckets[bucket_index].append(index)
    for bucket in buckets:
        if not bucket:
            continue
        finite = [index for index in bucket if points[index][3] is not None]
        if finite:
            chosen.add(min(finite, key=lambda index: points[index][3]))
            chosen.add(max(finite, key=lambda index: points[index][3]))
        else:
            chosen.add(bucket[len(bucket) // 2])
        if finite and len(finite) != len(bucket):
            gaps = [index for index in bucket if points[index][3] is None]
            chosen.add(gaps[len(gaps) // 2])
    ordered = _cap_samples(sorted(chosen), points, limit)
    return [points[index] for index in ordered]


def _cap_samples(
    chosen: list[int],
    points: list[tuple[float, float, float, float | None]],
    limit: int,
) -> list[int]:
    if len(chosen) <= limit:
        return chosen
    must = {chosen[0], chosen[-1]}
    finite = [index for index in chosen if points[index][3] is not None]
    if finite:
        must.add(min(finite, key=lambda index: (points[index][3], index)))
        must.add(max(finite, key=lambda index: (points[index][3], index)))
    rest = [index for index in chosen if index not in must]
    room = limit - len(must)
    if room <= 0:
        return sorted(must)[:limit]
    if len(rest) <= room:
        return sorted(must.union(rest))
    step = (len(rest) - 1) / (room - 1) if room > 1 else 0
    picked = {rest[min(len(rest) - 1, round(offset * step))] for offset in range(room)}
    return sorted(must.union(picked))
