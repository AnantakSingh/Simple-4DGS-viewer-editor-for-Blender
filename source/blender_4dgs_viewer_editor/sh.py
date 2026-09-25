"""View-dependent colour: evaluate 3DGS spherical harmonics (degrees 0-3) with numpy.

Same basis, constants and conventions as the reference 3DGS rasteriser: the colour
of a splat is evaluated once, for the direction from the viewpoint to the splat
centre, in the capture's own (source) coordinates:

    srgb = clamp(0.5 + C0 * f_dc + sum_k basis_k(dir) * f_rest[k], 0, 1)

The cache stores `base` = 0.5 + C0 * f_dc (unclamped) and `rest` = f_rest laid
out channel-major (3 x coefficients), both as float16. No Blender dependency.
"""
import os
from concurrent.futures import ThreadPoolExecutor

import numpy as np

C1 = 0.4886025119029199
C2 = (1.0925484305920792, -1.0925484305920792, 0.31539156525252005, -1.0925484305920792, 0.5462742152960396)
C3 = (-0.5900435899266435, 2.890611442640554, -0.4570457994644658, 0.3731763325901154,
      -0.4570457994644658, 1.445305721320277, -0.5900435899266435)
COEFFS = {0: 0, 1: 3, 2: 8, 3: 15}          # higher-order coefficients per channel for each degree


def degree_for(rest_count):
    """SH degree from the number of f_rest properties (0, 9, 24 or 45)."""
    per_channel = rest_count // 3
    for degree, count in COEFFS.items():
        if count == per_channel:
            return degree
    raise ValueError(f"unsupported number of f_rest properties: {rest_count}")


def basis(dirs, degree):
    """(n, COEFFS[degree]) basis values for unit direction vectors `dirs` (n, 3)."""
    x, y, z = dirs[:, 0], dirs[:, 1], dirs[:, 2]
    cols = []
    if degree >= 1:
        cols += [-C1 * y, C1 * z, -C1 * x]
    if degree >= 2:
        xx, yy, zz = x * x, y * y, z * z
        cols += [C2[0] * x * y, C2[1] * y * z, C2[2] * (2 * zz - xx - yy), C2[3] * x * z, C2[4] * (xx - yy)]
    if degree >= 3:
        cols += [C3[0] * y * (3 * xx - yy), C3[1] * x * y * z, C3[2] * y * (4 * zz - xx - yy),
                 C3[3] * z * (2 * zz - 3 * xx - 3 * yy), C3[4] * x * (4 * zz - xx - yy),
                 C3[5] * z * (xx - yy), C3[6] * x * (xx - 3 * yy)]
    return np.stack(cols, axis=1) if cols else np.zeros((len(dirs), 0), dtype=dirs.dtype)


def srgb_to_linear(c):
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


_CHUNK = 16384
_pool = None


def _executor():
    global _pool
    if _pool is None:
        _pool = ThreadPoolExecutor(max_workers=max(1, min(8, (os.cpu_count() or 2) - 1)))
    return _pool


def _eval(pos, base, rest, degree, eye, view_dir, out):
    pos = np.asarray(pos, dtype=np.float32)
    if eye is not None:
        dirs = pos - eye
    else:
        dirs = np.broadcast_to(view_dir, pos.shape)
    dirs = dirs / np.maximum(np.linalg.norm(dirs, axis=1, keepdims=True), 1e-12)
    srgb = np.asarray(base, dtype=np.float32).copy()
    k = COEFFS[degree]
    if k:
        b = basis(dirs, degree)                                             # (n, k)
        r = np.asarray(rest, dtype=np.float32).reshape(len(pos), 3, -1)[:, :, :k]
        srgb += np.einsum("nck,nk->nc", r, b)
    out[:] = srgb_to_linear(np.clip(srgb, 0.0, 1.0))


def view_colors(positions, base, rest, degree, eye=None, view_dir=None):
    """Linear RGB (n, 3) float32 for each splat as seen from `eye` (perspective) or along
    `view_dir` (orthographic). positions/eye/view_dir are in source coordinates.

    Large inputs are split into chunks evaluated on worker threads (numpy releases the GIL)."""
    n = len(positions)
    out = np.empty((n, 3), dtype=np.float32)
    eye = None if eye is None else np.asarray(eye, dtype=np.float32)
    view_dir = None if view_dir is None else np.asarray(view_dir, dtype=np.float32)
    if n <= _CHUNK:
        _eval(positions, base, rest, degree, eye, view_dir, out)
        return out
    jobs = [_executor().submit(_eval, positions[a:a + _CHUNK], base[a:a + _CHUNK], rest[a:a + _CHUNK],
                               degree, eye, view_dir, out[a:a + _CHUNK])
            for a in range(0, n, _CHUNK)]
    for job in jobs:
        job.result()
    return out


def shutdown():
    global _pool
    if _pool is not None:
        _pool.shutdown(wait=False)
        _pool = None
