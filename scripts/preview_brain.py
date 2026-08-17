"""Offline preview of the procedural brain point cloud.

Mirrors the geometry in frontend/assets/neural-brain.js so the silhouette can be
checked without a browser: same ellipsoid, same lobe sculpting, same fissure and
gyri, rendered with an additive splat to imitate the WebGL blending.

    python scripts/preview_brain.py

Writes PNGs into docs/preview/.
"""

from __future__ import annotations

import math
import os
import struct
import sys
import zlib

import numpy as np

OUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "preview"
)

W, H = 900, 620
COUNT = 90_000
SEED = 20260817


# ---------------------------------------------------------------------------
# value noise, matching the JS implementation
# ---------------------------------------------------------------------------

def make_noise(rng, size=64):
    table = rng.random((size, size, size))

    def noise(x, y, z):
        xi = np.floor(x).astype(int)
        yi = np.floor(y).astype(int)
        zi = np.floor(z).astype(int)
        xf, yf, zf = x - xi, y - yi, z - zi

        fade = lambda t: t * t * (3 - 2 * t)
        xf, yf, zf = fade(xf), fade(yf), fade(zf)

        m = size - 1
        at = lambda a, b, c: table[(a & m), (b & m), (c & m)]

        c000, c100 = at(xi, yi, zi),         at(xi + 1, yi, zi)
        c010, c110 = at(xi, yi + 1, zi),     at(xi + 1, yi + 1, zi)
        c001, c101 = at(xi, yi, zi + 1),     at(xi + 1, yi, zi + 1)
        c011, c111 = at(xi, yi + 1, zi + 1), at(xi + 1, yi + 1, zi + 1)

        lerp = lambda a, b, t: a + (b - a) * t
        return lerp(
            lerp(lerp(c000, c100, xf), lerp(c010, c110, xf), yf),
            lerp(lerp(c001, c101, xf), lerp(c011, c111, xf), yf),
            zf,
        )

    return noise


# ---------------------------------------------------------------------------
# geometry (port of cerebrumRadius)
# ---------------------------------------------------------------------------

def cerebrum_surface(x, y, z, noise):
    """Returns (radius, fold, groove) — mirrors cerebrumSurface() in the JS."""
    RX, RY, RZ = 0.94, 0.86, 1.16
    r = 1.0 / np.sqrt((x / RX) ** 2 + (y / RY) ** 2 + (z / RZ) ** 2)

    r = np.where(z > 0, r * (1 - 0.12 * z ** 2), r)
    r = np.where(z < -0.6, r * (1 - 0.09 * np.abs(-z - 0.6) ** 1.5), r)

    temporal = (np.maximum(0, -y - 0.02)
                * np.maximum(0, np.abs(x) - 0.22)
                * np.maximum(0, 0.88 - np.abs(z + 0.1)))
    r *= 1 + 1.25 * temporal

    r = np.where(y < -0.52, r * (1 - 0.30 * np.abs(-y - 0.52) ** 1.3), r)

    midline = np.exp(-(x * x) / 0.0026)
    r *= 1 - 0.20 * midline * np.maximum(0, y + 0.05)

    central = np.exp(-((z - 0.02) * 3.1 - y * 1.4) ** 2 * 5.0)
    r *= 1 - 0.040 * central
    lateral = (np.exp(-((y + 0.18) * 4.4 + (z + 0.1) * 0.8) ** 2 * 4.0)
               * np.minimum(1, np.abs(x) * 2.2))
    r *= 1 - 0.050 * lateral

    n1 = noise(x * 4.3 + 11, y * 4.3 + 23, z * 4.3 + 37)
    n2 = noise(x * 9.1 + 3, y * 9.1 + 61, z * 9.1 + 17)
    r *= 1 + 0.085 * (n1 - 0.5) + 0.038 * (n2 - 0.5)

    ridge = (1 - np.abs(n1 * 2 - 1)) * 0.68 + (1 - np.abs(n2 * 2 - 1)) * 0.32
    fold = np.clip(ridge, 0, 1) ** 2.1
    groove = np.maximum(np.maximum(central, lateral), midline)
    return r, fold, groove


def unit_dirs(rng, n):
    u = rng.random(n) * 2 - 1
    phi = rng.random(n) * 2 * math.pi
    s = np.sqrt(np.maximum(0, 1 - u * u))
    return s * np.cos(phi), u, s * np.sin(phi)


def build_brain(count=COUNT, seed=SEED):
    rng = np.random.default_rng(seed)
    noise = make_noise(np.random.default_rng(seed ^ 0x9E3779B9))

    n_surf = int(count * 0.74)
    n_int = int(count * 0.09)
    n_cb = int(count * 0.12)
    n_stem = count - n_surf - n_int - n_cb

    parts = []

    # cerebral surface — rejection-sampled toward the gyral crowns
    cand = n_surf * 6
    dx, dy, dz = unit_dirs(rng, cand)
    r, fold, groove = cerebrum_surface(dx, dy, dz, noise)
    keep = rng.random(cand) <= (0.16 + 0.84 * fold)
    idx = np.flatnonzero(keep)[:n_surf]
    dx, dy, dz = dx[idx], dy[idx], dz[idx]
    r, fold, groove = r[idx], fold[idx], groove[idx]
    n_kept = len(idx)

    r = r * (1 - rng.random(n_kept) * 0.030)
    brightness = (0.28 + 0.90 * fold) * (1 - 0.50 * groove)
    parts.append((np.stack([dx * r, dy * r + 0.06, dz * r], 1),
                  0.42 + rng.random(n_kept) * 0.62 + fold * 0.45,
                  np.minimum(1, 0.10 + rng.random(n_kept) * 0.22 + brightness * 0.80)))

    # interior volume
    dx, dy, dz = unit_dirs(rng, n_int)
    r, _, _ = cerebrum_surface(dx, dy, dz, noise)
    r = r * (0.30 + rng.random(n_int) * 0.58)
    parts.append((np.stack([dx * r, dy * r + 0.06, dz * r], 1),
                  0.32 + rng.random(n_int) * 0.34,
                  0.05 + rng.random(n_int) * 0.13))

    # cerebellum
    dx, dy, dz = unit_dirs(rng, n_cb)
    r = 1.0 / np.sqrt((dx / 0.60) ** 2 + (dy / 0.30) ** 2 + (dz / 0.40) ** 2)
    r *= 1 + 0.05 * (noise(dx * 9 + 5, dy * 34 + 9, dz * 9 + 2) - 0.5)
    r *= 1 - 0.13 * np.exp(-(dx * dx) / 0.004)
    shell = 1 - rng.random(n_cb) * 0.30
    parts.append((np.stack([dx * r * shell,
                            -0.60 + dy * r * shell,
                            -0.74 + dz * r * shell], 1),
                  0.50 + rng.random(n_cb) * 0.70,
                  0.34 + rng.random(n_cb) * 0.50))

    # brainstem
    t = rng.random(n_stem)
    rad = (0.20 - 0.075 * t) * (0.65 + rng.random(n_stem) * 0.35)
    ang = rng.random(n_stem) * 2 * math.pi
    parts.append((np.stack([np.cos(ang) * rad,
                            -0.42 - t * 0.78,
                            -0.22 + np.sin(ang) * rad * 0.85], 1),
                  0.45 + rng.random(n_stem) * 0.55,
                  0.30 + rng.random(n_stem) * 0.46))

    pos = np.concatenate([p[0] for p in parts])
    size = np.concatenate([p[1] for p in parts])
    alpha = np.concatenate([p[2] for p in parts])
    return pos, size, alpha


# ---------------------------------------------------------------------------
# rendering — additive splat, mimicking the WebGL point sprites
# ---------------------------------------------------------------------------

def look_at(eye, target, up=(0, 1, 0)):
    f = np.array(target, float) - np.array(eye, float)
    f /= np.linalg.norm(f)
    u = np.array(up, float)
    s = np.cross(f, u); s /= np.linalg.norm(s)
    u = np.cross(s, f)
    return np.stack([s, u, -f])          # rows = camera basis


def render(pos, size, alpha, eye, target, rot_y=0.0, fov=42.0,
           focus=None, pulse=None):
    c, s = math.cos(rot_y), math.sin(rot_y)
    R = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    p = pos @ R.T

    M = look_at(eye, target)
    cam = (p - np.array(eye, float)) @ M.T
    zc = -cam[:, 2]

    keep = zc > 0.05
    cam, zc = cam[keep], zc[keep]
    sz, al = size[keep], alpha[keep]
    src = pos[keep]

    heat = np.zeros(len(cam))
    if focus is not None:
        fx, fy, fz, fr = focus
        d = np.linalg.norm(src - np.array([fx, fy, fz]), axis=1)
        heat = np.maximum(heat, np.clip(1 - (d - fr * 0.25) / (fr * 0.75), 0, 1))
    if pulse is not None:
        axis = (src[:, 2] + 1.35) / 2.7
        heat = np.maximum(heat, np.clip(1 - np.abs(axis - pulse) / 0.13, 0, 1))

    fpx = (H / 2) / math.tan(math.radians(fov) / 2)
    x = cam[:, 0] / zc * fpx + W / 2
    y = -cam[:, 1] / zc * fpx + H / 2
    r = np.clip(sz * (34.0 / zc) * 0.45, 0.5, 6.0)

    img = np.zeros((H, W, 3), np.float32)
    base = np.array([0.369, 0.784, 0.961])       # #5ec8f5
    hot = np.array([0.914, 0.984, 1.0])          # #e9fbff

    order = np.argsort(-zc)
    x, y, r, al, heat = x[order], y[order], r[order], al[order], heat[order]

    xi = np.round(x).astype(int)
    yi = np.round(y).astype(int)
    ok = (xi >= 2) & (xi < W - 2) & (yi >= 2) & (yi < H - 2)
    xi, yi, r, al, heat = xi[ok], yi[ok], r[ok], al[ok], heat[ok]

    col = base[None, :] * (1 - heat[:, None]) + hot[None, :] * heat[:, None]
    weight = al * (1 + heat * 1.6)

    # 3x3 splat with a soft falloff
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            d2 = dx * dx + dy * dy
            fall = math.exp(-d2 / 1.5)
            contrib = (col * (weight * fall * 0.17)[:, None]).astype(np.float32)
            np.add.at(img, (yi + dy, xi + dx), contrib)

    return img


def compose(img):
    """Lay the additive point cloud over the CSS background field."""
    yy, xx = np.mgrid[0:H, 0:W]
    u, v = xx / W, yy / H

    bg = np.zeros((H, W, 3), np.float32)
    top = np.array([0.024, 0.063, 0.161])
    bot = np.array([0.012, 0.027, 0.075])
    bg += top * (1 - v[..., None]) + bot * v[..., None]

    def radial(cx, cy, rad, colour, amp):
        d = np.sqrt(((u - cx) * (W / H)) ** 2 + (v - cy) ** 2)
        g = np.clip(1 - d / rad, 0, 1) ** 2
        return (np.array(colour) * amp)[None, None, :] * g[..., None]

    bg += radial(0.82, 1.04, 1.05, (0.102, 0.310, 0.816), 0.55)
    bg += radial(0.06, -0.06, 0.85, (0.220, 0.741, 0.973), 0.20)

    rng = np.random.default_rng(7)
    n = 260
    sx = (rng.random(n) * W).astype(int)
    sy = (rng.random(n) * H).astype(int)
    sa = rng.random(n) * 0.55 + 0.12
    bg[sy, sx] += np.array([0.84, 0.93, 1.0])[None, :] * sa[:, None]

    out = bg + img
    out = out / (1 + out * 0.55)            # soft filmic rolloff
    return np.clip(out * 255, 0, 255).astype(np.uint8)


def write_png(path, rgb):
    h, w, _ = rgb.shape
    raw = b"".join(b"\x00" + rgb[y].tobytes() for y in range(h))

    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 6))
           + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)


STATES = {
    "01_arrival":  dict(eye=(0, 0.02, 4.25), target=(0, 0.04, 0), rot_y=0.0),
    "02_baseline": dict(eye=(0.35, 1.15, 2.30), target=(0, 0.34, 0), rot_y=0.55),
    "03_signals":  dict(eye=(0, 0.02, 3.05), target=(0, 0.02, 0), rot_y=1.2, pulse=0.55),
    "05_insight":  dict(eye=(0.55, 0.18, 3.55), target=(0, 0.02, 0), rot_y=math.pi,
                        focus=(0, -0.02, -1.02, 0.78)),
    "06_balance":  dict(eye=(0.15, -0.72, 2.95), target=(0, -0.52, -0.35),
                        rot_y=math.pi * 0.82, focus=(0, -0.60, -0.74, 0.62)),
    "07_summary":  dict(eye=(0, 0.02, 4.75), target=(0, 0.02, 0), rot_y=2.4),
}


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print("building point cloud …")
    pos, size, alpha = build_brain()

    only = sys.argv[1] if len(sys.argv) > 1 else None
    for name, cfg in STATES.items():
        if only and only not in name:
            continue
        img = render(pos, size, alpha, **cfg)
        path = os.path.join(OUT_DIR, f"brain_{name}.png")
        write_png(path, compose(img))
        print("wrote", path)


if __name__ == "__main__":
    main()
