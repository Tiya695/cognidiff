"""Offline preview of the procedural brain point cloud with VISIBLE MATTE BLUE matching Image 2."""

from __future__ import annotations

import math
import os
import struct
import zlib

import numpy as np

OUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "preview"
)

W, H = 900, 900
COUNT = 115_000
SEED = 20260817


def generate_brain(count=COUNT, seed=SEED):
    rng = np.random.default_rng(seed)

    n_cortex = int(count * 0.77)
    n_cerebellum = int(count * 0.17)
    n_stem = count - n_cortex - n_cerebellum

    # Anatomical gyral centers per hemisphere (x > 0)
    hemi_seeds = [
        # Superior sagittal row (along midline)
        [0.16, 0.80, 0.20],
        [0.17, 0.78, -0.15],
        [0.15, 0.68, 0.48],
        [0.16, 0.65, -0.45],
        [0.14, 0.50, 0.68],
        [0.14, 0.46, -0.68],
        [0.12, 0.25, 0.78],
        [0.12, 0.20, -0.78],

        # Mid-dorsal / Frontal & Parietal face
        [0.36, 0.72, 0.22],
        [0.38, 0.70, -0.16],
        [0.34, 0.58, 0.50],
        [0.36, 0.54, -0.50],
        [0.32, 0.38, 0.68],
        [0.32, 0.32, -0.68],
        [0.30, 0.16, 0.75],
        [0.30, 0.10, -0.75],

        # Lateral crown / Precentral & Postcentral bulges
        [0.58, 0.55, 0.18],
        [0.60, 0.52, -0.20],
        [0.54, 0.42, 0.48],
        [0.56, 0.38, -0.50],
        [0.50, 0.22, 0.62],
        [0.50, 0.16, -0.62],

        # Temporal & lateral under-curving lobes
        [0.70, 0.25, 0.15],
        [0.70, 0.20, -0.18],
        [0.66, 0.04, 0.34],
        [0.66, -0.02, -0.34],
        [0.58, -0.14, 0.42],
        [0.56, -0.18, -0.40],
        [0.44, -0.16, 0.15],
        [0.44, -0.18, -0.15],
    ]
    hemi_seeds = np.array(hemi_seeds, dtype=np.float32)
    all_seeds = np.concatenate([
        hemi_seeds,
        hemi_seeds * np.array([-1.0, 1.0, 1.0], dtype=np.float32)
    ], axis=0)

    # 1. CEREBRUM SURFACE
    u = rng.uniform(-0.62, 0.98, n_cortex)
    phi = rng.uniform(0, 2 * np.pi, n_cortex)
    s = np.sqrt(np.maximum(0, 1.0 - u * u))

    dx = s * np.sin(phi)
    dy = u
    dz = s * np.cos(phi)

    RX, RY, RZ = 0.85, 0.84, 0.92
    bx = dx * RX
    by = dy * RY + 0.14
    bz = dz * RZ

    # Longitudinal fissure
    fissure = 0.20 * np.exp(-((bx / 0.080) ** 2)) * np.clip((by + 0.18) / 0.78, 0.2, 1.25)
    bx_sign = np.sign(bx)
    bx_sign[bx_sign == 0] = 1.0
    bx = bx - bx_sign * fissure * 0.28

    under_cb = np.maximum(0.0, -0.06 - by)
    by += under_cb * 0.30

    P = np.stack([bx, by, bz], axis=1)

    gyri_puff = np.zeros(n_cortex, dtype=np.float32)
    chunk_size = 20000
    for start in range(0, n_cortex, chunk_size):
        end = min(start + chunk_size, n_cortex)
        p_chk = P[start:end]
        diff = p_chk[:, None, :] - all_seeds[None, :, :]
        d2 = np.sum(diff * diff, axis=2)
        part = np.partition(d2, 1, axis=1)
        d1 = np.sqrt(part[:, 0])
        d2 = np.sqrt(part[:, 1])

        cell_r = 0.24
        crest = np.cos(np.clip(d1 / cell_r, 0.0, 1.0) * (math.pi / 2.0)) ** 2
        sulcus = np.tanh((d2 - d1) / 0.045)
        gyri_puff[start:end] = crest * (0.35 + 0.65 * sulcus)

    hemi_cx = np.where(bx >= 0, 0.18, -0.18)
    dir_x = bx - hemi_cx
    dir_y = by - 0.10
    dir_z = bz
    dir_len = np.sqrt(dir_x ** 2 + dir_y ** 2 + dir_z ** 2 + 1e-6)
    dir_x /= dir_len; dir_y /= dir_len; dir_z /= dir_len

    mound_disp = (gyri_puff - 0.30) * 0.18
    micro = np.sin(bx * 26.0) * np.sin(by * 26.0) * np.sin(bz * 26.0) * 0.012

    px = bx + dir_x * (mound_disp + micro)
    py = by + dir_y * (mound_disp + micro)
    pz = bz + dir_z * (mound_disp + micro)

    depth = (rng.uniform(0, 1, n_cortex) ** 2.2) * 0.075
    px -= dir_x * depth
    py -= dir_y * depth
    pz -= dir_z * depth

    nx = dir_x + dir_x * mound_disp * 1.8
    ny = dir_y + dir_y * mound_disp * 1.8
    nz = dir_z
    n_len = np.sqrt(nx ** 2 + ny ** 2 + nz ** 2 + 1e-6)
    nx /= n_len; ny /= n_len; nz /= n_len

    alpha = np.clip(0.38 + 0.58 * gyri_puff - depth * 3.5, 0.22, 0.95)
    size = 0.40 + 0.24 * gyri_puff + rng.uniform(0, 0.2, n_cortex)

    pts_cortex = (np.stack([px, py, pz], 1), size, alpha, np.stack([nx, ny, nz], 1), gyri_puff)

    # 2. CEREBELLUM
    pts_cb = []
    n_cb_half = n_cerebellum // 2
    for sign in (-1.0, 1.0):
        cx = sign * 0.32
        cy = -0.32
        cz = -0.15
        rx, ry, rz = 0.31, 0.19, 0.27

        u = rng.uniform(-0.95, 0.95, n_cb_half)
        phi = rng.uniform(0, 2 * np.pi, n_cb_half)
        theta = np.arccos(u)

        dx = np.sin(theta) * np.cos(phi)
        dy = np.cos(theta)
        dz = np.sin(theta) * np.sin(phi)

        folia = np.sin((cy + dy * ry) * 78.0)
        rad = 1.0 + folia * 0.045

        cpx = cx + dx * rx * rad
        cpy = cy + dy * ry * rad
        cpz = cz + dz * rz * rad

        depth_cb = (rng.uniform(0, 1, n_cb_half) ** 2.0) * 0.05
        cpx -= dx * depth_cb
        cpy -= dy * depth_cb
        cpz -= dz * depth_cb

        norm_folia = np.clip((folia + 1.0) * 0.5, 0.0, 1.0)
        al_cb = np.clip(0.35 + 0.50 * norm_folia, 0.22, 0.90)
        sz_cb = 0.36 + rng.uniform(0, 0.2, n_cb_half)

        pts_cb.append((np.stack([cpx, cpy, cpz], 1), sz_cb, al_cb, np.stack([dx, dy, dz], 1), norm_folia))

    # 3. BRAINSTEM
    t = rng.uniform(0, 1, n_stem)
    pons = 0.046 * np.exp(-((t - 0.22) ** 2) / 0.018)
    rad_stem = (0.11 - 0.038 * t + pons) * np.sqrt(rng.uniform(0.18, 1.0, n_stem))
    ang = rng.uniform(0, 2 * np.pi, n_stem)

    sx = np.cos(ang) * rad_stem
    sy = -0.28 - t * 0.56
    sz = -0.08 + np.sin(ang) * rad_stem * 0.75

    stem_alpha = 0.35 + rng.uniform(0, 0.35, n_stem)
    stem_size = 0.36 + rng.uniform(0, 0.2, n_stem)
    snx = np.cos(ang)
    sny = np.zeros_like(ang)
    snz = np.sin(ang)
    stem_elev = np.full(n_stem, 0.55, dtype=np.float32)

    all_pos = np.concatenate([pts_cortex[0]] + [p[0] for p in pts_cb] + [np.stack([sx, sy, sz], 1)])
    all_sz  = np.concatenate([pts_cortex[1]] + [p[1] for p in pts_cb] + [stem_size])
    all_al  = np.concatenate([pts_cortex[2]] + [p[2] for p in pts_cb] + [stem_alpha])
    all_norm= np.concatenate([pts_cortex[3]] + [p[3] for p in pts_cb] + [np.stack([snx, sny, snz], 1)])
    all_elev= np.concatenate([pts_cortex[4]] + [p[4] for p in pts_cb] + [stem_elev])

    return all_pos, all_sz, all_al, all_norm, all_elev


def render_normal_blend(pos, size, alpha, normals, elev, tilt_x=0.14):
    p = pos.copy()
    norm = normals.copy()

    cx, sx = math.cos(tilt_x), math.sin(tilt_x)
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    p = p @ Rx.T
    norm = norm @ Rx.T

    zc = 3.25 - p[:, 2]
    fov = 34.0
    fpx = (H / 2) / math.tan(math.radians(fov) / 2)

    x = p[:, 0] / zc * fpx + W / 2
    y = -p[:, 1] / zc * fpx + H / 2

    # Lighting matching Image 2
    light_dir = np.array([0.22, 0.85, 0.52])
    light_dir /= np.linalg.norm(light_dir)
    diffuse = np.maximum(0.0, norm @ light_dir)
    cam_fill = np.maximum(0.0, norm[:, 2])
    rim = np.clip(1.0 - np.abs(norm[:, 2]), 0.0, 1.0) ** 1.8

    illum = 0.20 + 0.35 * diffuse + 0.25 * cam_fill + 0.38 * rim + 0.35 * elev

    # Palette matching Image 2
    base_blue = np.array([0.05, 0.20, 0.55], np.float32)
    mid_blue  = np.array([0.16, 0.50, 0.94], np.float32)
    crest_blue= np.array([0.42, 0.80, 1.00], np.float32)

    t = np.clip(illum, 0.0, 1.0)
    col = np.zeros((len(t), 3), np.float32)
    m1 = t < 0.50
    col[m1] = base_blue[None, :] * (1.0 - t[m1, None] * 2.0) + mid_blue[None, :] * (t[m1, None] * 2.0)
    m2 = ~m1
    col[m2] = mid_blue[None, :] * (1.0 - (t[m2, None] - 0.5) * 2.0) + crest_blue[None, :] * ((t[m2, None] - 0.5) * 2.0)

    img = np.zeros((H, W, 3), np.float32)
    yy, xx = np.mgrid[0:H, 0:W]
    u, v = xx / W, yy / H
    d_center = np.sqrt(((u - 0.5) * 1.0) ** 2 + ((v - 0.48) * 1.0) ** 2)
    bg_glow = np.clip(1.0 - d_center / 0.58, 0.0, 1.0) ** 2.2
    img += np.array([0.012, 0.030, 0.070])[None, None, :] * bg_glow[..., None]
    img += np.array([0.004, 0.007, 0.016])[None, None, :]

    order = np.argsort(zc)
    x, y, col, alpha = x[order], y[order], col[order], alpha[order]

    xi = np.round(x).astype(int)
    yi = np.round(y).astype(int)
    valid = (xi >= 1) & (xi < W - 1) & (yi >= 1) & (yi < H - 1)

    xi, yi, col, alpha = xi[valid], yi[valid], col[valid], alpha[valid]

    weights = [
        (0, 0, 1.0),
        (-1, 0, 0.55), (1, 0, 0.55), (0, -1, 0.55), (0, 1, 0.55),
        (-1, -1, 0.28), (1, -1, 0.28), (-1, 1, 0.28), (1, 1, 0.28)
    ]
    accum_col = np.zeros((H, W, 3), np.float32)
    accum_w = np.zeros((H, W), np.float32)

    for dx, dy, w_factor in weights:
        cur_x = xi + dx
        cur_y = yi + dy
        v = (cur_x >= 0) & (cur_x < W) & (cur_y >= 0) & (cur_y < H)
        w = alpha[v] * w_factor * 0.38
        np.add.at(accum_col, (cur_y[v], cur_x[v], 0), col[v, 0] * w)
        np.add.at(accum_col, (cur_y[v], cur_x[v], 1), col[v, 1] * w)
        np.add.at(accum_col, (cur_y[v], cur_x[v], 2), col[v, 2] * w)
        np.add.at(accum_w, (cur_y[v], cur_x[v]), w)

    img_rgb = img.copy()
    for c in range(3):
        blended = img_rgb[:, :, c] + accum_col[:, :, c]
        img_rgb[:, :, c] = np.clip(blended / (1.0 + blended * 0.38), 0.0, 1.0)

    return np.clip(img_rgb * 255, 0, 255).astype(np.uint8)


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


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    pos, sz, al, norm, elev = generate_brain()
    img = render_normal_blend(pos, sz, al, norm, elev, tilt_x=0.14)
    path = os.path.join(OUT_DIR, "brain_01_arrival.png")
    write_png(path, img)
    print("wrote", path)


if __name__ == "__main__":
    main()
