"""Generate the CogniDiff extension icons (16/48/128 px) with no dependencies.

The mark is a cyan neural node on the same deep-navy field the rest of the app
uses: a glowing core, an orbital ring, and four faint axon spokes.
"""

import math
import os
import struct
import zlib

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "extension", "icons")

BG_TOP = (7, 19, 49)
BG_BOT = (4, 9, 28)
CYAN = (127, 216, 255)
GLOW = (56, 189, 248)


def _mix(a, b, t):
    t = max(0.0, min(1.0, t))
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def render(size):
    """Return an RGBA pixel buffer, supersampled 3x for clean edges."""
    ss = 3
    n = size * ss
    c = (n - 1) / 2.0
    core_r = n * 0.17
    ring_r = n * 0.40
    ring_w = max(n * 0.035, 1.2)

    rows = []
    for y in range(n):
        row = []
        for x in range(n):
            dx, dy = x - c, y - c
            d = math.hypot(dx, dy)

            r, g, b = _mix(BG_TOP, BG_BOT, y / (n - 1))
            a = 255

            # outer glow falling off from the core
            halo = math.exp(-((d / (n * 0.30)) ** 2)) * 0.75
            if halo > 0.002:
                r, g, b = _mix((r, g, b), GLOW, halo * 0.55)

            # orbital ring
            ring = 1.0 - min(abs(d - ring_r) / ring_w, 1.0)
            if ring > 0:
                r, g, b = _mix((r, g, b), CYAN, ring * 0.70)

            # four axon spokes at the diagonals
            if d < ring_r * 1.02:
                ang = math.atan2(dy, dx)
                spoke = max(math.cos(4 * (ang - math.pi / 4)), 0.0) ** 24
                if spoke > 0.01 and d > core_r * 0.9:
                    r, g, b = _mix((r, g, b), CYAN, spoke * 0.45)

            # bright core
            if d < core_r + 1.5:
                edge = min(max((core_r + 0.75 - d) / 1.5, 0.0), 1.0)
                r, g, b = _mix((r, g, b), (235, 250, 255), edge)

            # circular mask so the icon reads as a disc, not a square
            outer = n * 0.485
            if d > outer:
                a = 0
            elif d > outer - 1.5:
                a = round(255 * (outer - d) / 1.5)

            row.append((r, g, b, a))
        rows.append(row)

    # downsample the supersampled buffer
    out = bytearray()
    for y in range(size):
        out.append(0)  # PNG filter type 0
        for x in range(size):
            acc = [0, 0, 0, 0]
            for sy in range(ss):
                for sx in range(ss):
                    px = rows[y * ss + sy][x * ss + sx]
                    for i in range(4):
                        acc[i] += px[i]
            out.extend(v // (ss * ss) for v in acc)
    return bytes(out)


def write_png(path, size, raw):
    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 9))
    png += chunk(b"IEND", b"")

    with open(path, "wb") as f:
        f.write(png)


def main():
    os.makedirs(OUT, exist_ok=True)
    for size in (16, 48, 128):
        path = os.path.join(OUT, f"icon{size}.png")
        write_png(path, size, render(size))
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
