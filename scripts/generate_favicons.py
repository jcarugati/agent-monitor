#!/usr/bin/env python3
"""Generate deterministic raster favicons for Agent Monitor."""

from __future__ import annotations

import binascii
import struct
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
BACKGROUND = (0x17, 0x18, 0x13, 0xFF)
BORDER = (0x48, 0x4C, 0x3E, 0xFF)
LIME = (0xB8, 0xEF, 0x4A, 0xFF)


def brand_pixels(size: int) -> list[list[tuple[int, int, int, int]]]:
    """Return the crisp 16px brand mark, optionally integer-scaled."""
    if size not in {16, 32}:
        raise ValueError("favicon size must be 16 or 32")
    scale = size // 16
    base = [[BACKGROUND for _ in range(16)] for _ in range(16)]
    for position in range(16):
        base[0][position] = BORDER
        base[15][position] = BORDER
        base[position][0] = BORDER
        base[position][15] = BORDER
    for x in range(7, 12):
        base[4][x] = LIME
    for y in range(6, 11):
        base[y][4] = LIME
    for y in range(10, 13):
        for x in range(10, 13):
            base[y][x] = LIME
    return [
        [base[y // scale][x // scale] for x in range(size)]
        for y in range(size)
    ]


def png_chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", binascii.crc32(kind + payload))


def encode_png(pixels: list[list[tuple[int, int, int, int]]]) -> bytes:
    height = len(pixels)
    width = len(pixels[0])
    scanlines = b"".join(b"\x00" + b"".join(bytes(pixel) for pixel in row) for row in pixels)
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", header)
        + png_chunk(b"IDAT", zlib.compress(scanlines, level=9))
        + png_chunk(b"IEND", b"")
    )


def encode_dib(pixels: list[list[tuple[int, int, int, int]]]) -> bytes:
    height = len(pixels)
    width = len(pixels[0])
    xor_bitmap = b"".join(
        bytes((blue, green, red, alpha))
        for row in reversed(pixels)
        for red, green, blue, alpha in row
    )
    mask_stride = ((width + 31) // 32) * 4
    and_mask = bytes(mask_stride * height)
    bitmap_size = len(xor_bitmap) + len(and_mask)
    header = struct.pack(
        "<IiiHHIIiiII",
        40,
        width,
        height * 2,
        1,
        32,
        0,
        bitmap_size,
        0,
        0,
        0,
        0,
    )
    return header + xor_bitmap + and_mask


def encode_ico(sizes: tuple[int, ...] = (16, 32)) -> bytes:
    images = [encode_dib(brand_pixels(size)) for size in sizes]
    offset = 6 + 16 * len(images)
    entries = []
    for size, image in zip(sizes, images, strict=True):
        entries.append(struct.pack("<BBBBHHII", size, size, 0, 0, 1, 32, len(image), offset))
        offset += len(image)
    return struct.pack("<HHH", 0, 1, len(images)) + b"".join(entries) + b"".join(images)


def main() -> None:
    (FRONTEND / "favicon-32x32.png").write_bytes(encode_png(brand_pixels(32)))
    (FRONTEND / "favicon.ico").write_bytes(encode_ico())


if __name__ == "__main__":
    main()
