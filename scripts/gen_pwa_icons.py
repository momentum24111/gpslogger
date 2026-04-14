"""Einmalig ausführen: erzeugt PNG-Icons unter static/icons/ (stdlib, kein Pillow)."""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "static" / "icons"

# Primärfarbe Light-Theme (--color-primary #2456f5)
BRAND_RGB = (36, 86, 245)


def _chunk(tag: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(tag + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)


def write_png(path: Path, width: int, height: int, rgb: tuple[int, int, int]) -> None:
    r, g, b = rgb
    raw = bytearray()
    row = b"\x00" + bytes([r, g, b] * width)
    for _ in range(height):
        raw.extend(row)
    compressed = zlib.compress(bytes(raw), 9)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", compressed) + _chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)


def main() -> None:
    write_png(OUT / "icon-192.png", 192, 192, BRAND_RGB)
    write_png(OUT / "icon-512.png", 512, 512, BRAND_RGB)
    write_png(OUT / "icon-maskable-512.png", 512, 512, BRAND_RGB)
    write_png(OUT / "apple-touch-icon.png", 180, 180, BRAND_RGB)
    print("OK:", OUT)


if __name__ == "__main__":
    main()
