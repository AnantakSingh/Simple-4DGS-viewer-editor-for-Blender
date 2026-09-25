"""Unit tests for sh.py against an independent, loop-based 3DGS SH evaluation (numpy only):
    python dev/test_sh.py
"""
import importlib.util
import math
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "sh", os.path.join(HERE, "..", "source", "blender_4dgs_viewer_editor", "sh.py"))
sh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sh)

C0 = 0.28209479177387814


def reference(dc, rest, d, degree):
    """Straight transcription of the 3DGS reference `computeColorFromSH` for one splat."""
    x, y, z = d
    res = C0 * dc
    if degree > 0:
        res = res - 0.4886025119029199 * y * rest[0] + 0.4886025119029199 * z * rest[1] - 0.4886025119029199 * x * rest[2]
        if degree > 1:
            xx, yy, zz, xy, yz, xz = x * x, y * y, z * z, x * y, y * z, x * z
            res = (res + 1.0925484305920792 * xy * rest[3] + -1.0925484305920792 * yz * rest[4]
                   + 0.31539156525252005 * (2 * zz - xx - yy) * rest[5] + -1.0925484305920792 * xz * rest[6]
                   + 0.5462742152960396 * (xx - yy) * rest[7])
            if degree > 2:
                res = (res + -0.5900435899266435 * y * (3 * xx - yy) * rest[8] + 2.890611442640554 * xy * z * rest[9]
                       + -0.4570457994644658 * y * (4 * zz - xx - yy) * rest[10]
                       + 0.3731763325901154 * z * (2 * zz - 3 * xx - 3 * yy) * rest[11]
                       + -0.4570457994644658 * x * (4 * zz - xx - yy) * rest[12]
                       + 1.445305721320277 * z * (xx - yy) * rest[13] + -0.5900435899266435 * x * (xx - 3 * yy) * rest[14])
    srgb = np.clip(res + 0.5, 0, 1)
    return np.where(srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4)


rng = np.random.default_rng(1)
n = 300
pos = rng.normal(size=(n, 3)).astype(np.float32)
dc = rng.normal(scale=1.2, size=(n, 3))
rest_full = rng.normal(scale=0.3, size=(n, 3, 15))           # channel-major like the PLY
eye = np.array([0.3, -2.0, 4.0], dtype=np.float32)
base = 0.5 + C0 * dc

for degree in (0, 1, 2, 3):
    k = sh.COEFFS[degree]
    rest = rest_full[:, :, :k].reshape(n, -1)
    got = sh.view_colors(pos, base, rest, degree, eye=eye)
    want = np.array([reference(dc[i], rest_full[i, :, :k].T, (pos[i] - eye) / np.linalg.norm(pos[i] - eye), degree)
                     for i in range(n)])
    err = np.abs(got - want).max()
    assert err < 1e-5, (degree, err)
    print(f"ok  degree {degree} perspective (max err {err:.1e})")

view_dir = np.array([0.0, 1.0, 0.0], dtype=np.float32)
got = sh.view_colors(pos, base, rest_full.reshape(n, -1), 3, view_dir=view_dir)
want = np.array([reference(dc[i], rest_full[i].T, view_dir, 3) for i in range(n)])
assert np.abs(got - want).max() < 1e-5
print("ok  degree 3 orthographic")
assert sh.degree_for(45) == 3 and sh.degree_for(24) == 2 and sh.degree_for(9) == 1 and sh.degree_for(0) == 0
print("ok  degree_for")
print("all SH tests passed")
