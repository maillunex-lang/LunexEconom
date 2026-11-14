"""Real, tiny images for the studio tests (the studio now reads image headers, so fake bytes are rejected)."""
import struct
import zlib


def png(width=8, height=8, shade=0):
    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + bytes([shade]) * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def png_header_only(width, height):
    """What a decompression bomb looks like to a header reader: a valid IHDR that declares a huge canvas."""
    return (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
            + struct.pack(">I", 0) + b"\x00" * 16)


def webp_vp8x(width, height):
    payload = b"WEBP" + b"VP8X" + struct.pack("<I", 10) + b"\x00\x00\x00\x00" + (width - 1).to_bytes(3, "little") + (height - 1).to_bytes(3, "little")
    return b"RIFF" + struct.pack("<I", len(payload)) + payload


def webp_vp8l(width, height):
    bits = (width - 1) | ((height - 1) << 14)
    body = b"\x2f" + struct.pack("<I", bits) + b"\x00" * 8
    payload = b"WEBP" + b"VP8L" + struct.pack("<I", len(body)) + body
    return b"RIFF" + struct.pack("<I", len(payload)) + payload


def webp_vp8(width, height):
    body = b"\x00\x00\x00" + b"\x9d\x01\x2a" + struct.pack("<HH", width, height) + b"\x00" * 8
    payload = b"WEBP" + b"VP8 " + struct.pack("<I", len(body)) + body
    return b"RIFF" + struct.pack("<I", len(payload)) + payload
