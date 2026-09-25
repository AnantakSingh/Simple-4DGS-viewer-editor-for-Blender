"""Per-shoot view-dependent colour flag, on synthetic PLY sequences (numpy only):
    python dev/test_view_dependence.py
"""
import importlib.util
import os
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "convert", os.path.join(HERE, "..", "source", "blender_4dgs_viewer_editor", "convert.py"))
convert = importlib.util.module_from_spec(spec)
spec.loader.exec_module(convert)


def write_take(folder, frames, rest_count, rest_scale, n=4000, seed=0):
    """Binary little-endian 3DGS PLY frames with `rest_count` f_rest properties."""
    rng = np.random.default_rng(seed)
    names = (["x", "y", "z", "nx", "ny", "nz", "f_dc_0", "f_dc_1", "f_dc_2"]
             + [f"f_rest_{i}" for i in range(rest_count)]
             + ["opacity", "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"])
    dtype = np.dtype([(nm, "<f4") for nm in names])
    os.makedirs(folder, exist_ok=True)
    for f in range(1, frames + 1):
        data = np.zeros(n, dtype=dtype)
        for nm in ("x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2"):
            data[nm] = rng.normal(size=n)
        for i in range(rest_count):
            data[f"f_rest_{i}"] = rng.normal(scale=rest_scale, size=n)
        data["opacity"] = 1.0
        for i in range(3):
            data[f"scale_{i}"] = -4.0
        data["rot_0"] = 1.0
        header = "ply\nformat binary_little_endian 1.0\nelement vertex %d\n%send_header\n" % (
            n, "".join(f"property float {nm}\n" for nm in names))
        with open(os.path.join(folder, f"frame.{f:07d}.ply"), "wb") as fh:
            fh.write(header.encode("ascii"))
            fh.write(data.tobytes())


def check(label, rest_count, rest_scale, want_degree, want_rating, flag_start):
    with tempfile.TemporaryDirectory() as tmp:
        take = os.path.join(tmp, label)
        write_take(take, 6, rest_count, rest_scale)
        src = convert.find_source(take)
        vd = convert.analyse_view_dependence(src)
        assert vd["degree"] == want_degree and vd["rating"] == want_rating, (label, vd)
        meta = convert.convert(src, os.path.join(tmp, "cache"), workers=1)      # compact
        flag = convert.view_dependence_flag(meta)
        assert flag.startswith(flag_start), (label, flag)
        if want_degree:
            full = convert.convert(src, os.path.join(tmp, "cache"), workers=1, with_sh=True)   # upgrade
            assert convert.view_dependence_flag(full).startswith("Full quality"), full
        print(f"ok  {label:<22} degree {vd['degree']}  avg {vd['mean_levels']:5.2f} levels  -> {vd['rating']}")


check("no SH", 0, 0.0, 0, "none", "This shoot has no view-dependent colour")
check("faint SH (degree 1)", 9, 0.002, 1, "negligible", "Compact cache drops")
check("strong SH (degree 3)", 45, 0.3, 3, "visible", "Compact cache drops")
print("all view-dependence tests passed")
