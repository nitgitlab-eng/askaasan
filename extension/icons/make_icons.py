"""Draws the Aasan Companion icons (orange rounded square with a white tick) using only the standard library.
Run: python3 make_icons.py  (writes icon16/32/48/128.png next to this file)."""
import os
import struct
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ORANGE, WHITE = (249, 115, 22), (255, 255, 255)


def pixel(x, y, n):
    u, v = (x + 0.5) / n, (y + 0.5) / n
    r = 0.22  # corner radius (fraction of size)
    dx, dy = max(r - u, 0, u - (1 - r)), max(r - v, 0, v - (1 - r))
    if dx * dx + dy * dy > r * r:
        return (0, 0, 0, 0)
    # Tick: two thick segments (0.27,0.52)->(0.43,0.68)->(0.74,0.34).
    def seg(ax, ay, bx, by):
        px, py, vx, vy = u - ax, v - ay, bx - ax, by - ay
        t = max(0.0, min(1.0, (px * vx + py * vy) / (vx * vx + vy * vy)))
        ex, ey = px - t * vx, py - t * vy
        return (ex * ex + ey * ey) ** 0.5
    d = min(seg(0.27, 0.52, 0.43, 0.68), seg(0.43, 0.68, 0.74, 0.34))
    return (*WHITE, 255) if d < 0.075 else (*ORANGE, 255)


def png(n):
    rows = b"".join(b"\x00" + b"".join(bytes(pixel(x, y, n)) for x in range(n)) for y in range(n))
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", n, n, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b"")


if __name__ == "__main__":
    for size in (16, 32, 48, 128):
        with open(os.path.join(HERE, f"icon{size}.png"), "wb") as f:
            f.write(png(size))
    print("ok")
