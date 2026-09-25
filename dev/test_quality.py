"""Full-quality colour check (background Blender, isolated profile).

    set BLENDER_USER_RESOURCES=%TEMP%\\b4d_test_profile
    blender -b --factory-startup --python dev/test_quality.py -- <extension.zip> <take .zip or folder> <out dir> [frame]

Imports the take with Full-Quality Colour (converting or upgrading the cache), then renders:
  A  the plugin with view-dependent colour
  B  the same frame with View-Dependent Colour off (compact look)
  C  a reference whose splat colours are computed independently from the original PLY
     (3DGS SH evaluated toward the camera), bypassing the plugin's colour code
A must match C (only float16 rounding differs); B shows what the compact cache loses.
"""
import os
import sys
import time

import bpy
import numpy as np

argv = sys.argv[sys.argv.index("--") + 1:]
ext_zip, take, out_dir = (os.path.abspath(a) for a in argv[:3])
FRAME = int(argv[3]) if len(argv) > 3 else 300
os.makedirs(out_dir, exist_ok=True)
failures = []


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        failures.append(msg)


bpy.ops.extensions.package_install_files(filepath=ext_zip, repo="user_default", enable_on_install=True)
pkg = next(k for k in bpy.context.preferences.addons.keys() if k.endswith("blender_4dgs_viewer_editor"))
m = sys.modules[pkg]
convert, playback, shading = m.convert, m.playback, m.shading

for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
scene = bpy.context.scene
t0 = time.time()
bpy.ops.b4d.import_sequence(filepath=take, fps=30, setup_scene=True, full_quality=True)
while m.jobs._jobs:
    m.jobs._tick()
    time.sleep(0.2)
m.jobs._tick()
obj = bpy.context.active_object
cache = playback.get_cache(obj.b4d.cache_dir)
check(cache is not None and cache.sh_degree == 3, f"full-quality cache ready in {time.time() - t0:.0f}s (SH degree {cache and cache.sh_degree})")

scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_percentage = 100
scene.eevee.taa_render_samples = 128
scene.frame_set(FRAME)
print("status:", playback.status(obj))


def render(name):
    scene.render.filepath = os.path.join(out_dir, name)
    bpy.ops.render.render(write_still=True)
    im = bpy.data.images.load(scene.render.filepath)
    w, h = im.size
    return np.array(im.pixels[:], np.float32).reshape(h, w, 4)[..., :3] * 255


def mesh_colors():
    me = obj.data
    c = np.empty(len(me.vertices) * 3, np.float32)
    me.attributes[shading.ATTR_COLOR].data.foreach_get("vector", c)
    return c.reshape(-1, 3)


# ---- A: plugin, full-quality colour --------------------------------------------------------
img_a = render(f"A_full_{FRAME}.png")
col_a = mesh_colors()

# ---- C: independent reference from the original PLY ----------------------------------------
raw = convert.find_source(take).open_reader().read(FRAME - 1)
n = len(raw)
dc = np.stack([raw[f"f_dc_{i}"] for i in range(3)], 1).astype(np.float64)
op = 1 / (1 + np.exp(-raw["opacity"].astype(np.float64)))
sc = np.sort(np.exp(np.stack([raw[f"scale_{i}"] for i in range(3)], 1).astype(np.float64)), axis=1)
order = np.argsort(-(op * sc[:, 2] * sc[:, 1]), kind="stable")
pos = np.stack([raw["x"], raw["y"], raw["z"]], 1).astype(np.float64)
rest = np.stack([raw[f"f_rest_{i}"] for i in range(45)], 1).astype(np.float64).reshape(n, 3, 15)
cam = np.array(obj.matrix_world.inverted() @ scene.camera.matrix_world.translation)
d = pos - cam
d /= np.linalg.norm(d, axis=1, keepdims=True)
x, y, z = d.T
xx, yy, zz = x * x, y * y, z * z
B = np.stack([-0.4886025119029199 * y, 0.4886025119029199 * z, -0.4886025119029199 * x,
              1.0925484305920792 * x * y, -1.0925484305920792 * y * z, 0.31539156525252005 * (2 * zz - xx - yy),
              -1.0925484305920792 * x * z, 0.5462742152960396 * (xx - yy),
              -0.5900435899266435 * y * (3 * xx - yy), 2.890611442640554 * x * y * z,
              -0.4570457994644658 * y * (4 * zz - xx - yy), 0.3731763325901154 * z * (2 * zz - 3 * xx - 3 * yy),
              -0.4570457994644658 * x * (4 * zz - xx - yy), 1.445305721320277 * z * (xx - yy),
              -0.5900435899266435 * x * (xx - 3 * yy)], 1)
srgb = np.clip(0.5 + 0.28209479177387814 * dc + np.einsum("nck,nk->nc", rest, B), 0, 1)
ref = np.where(srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4)[order].astype(np.float32)
err = np.abs(col_a - ref)
check(err.max() < 0.01 and err.mean() < 5e-4, f"plugin colours match the reference (max {err.max():.4f}, mean {err.mean():.6f} linear)")

render_init = bpy.app.handlers.render_init
held = [h for h in render_init if getattr(h, "__module__", "").startswith(pkg)]
for h in held:
    render_init.remove(h)          # keep the handler from overwriting the reference colours
obj.data.attributes[shading.ATTR_COLOR].data.foreach_set("vector", ref.ravel())
obj.data.update()
img_c = render(f"C_reference_{FRAME}.png")
for h in held:
    render_init.append(h)

# ---- B: compact look ------------------------------------------------------------------------
obj.b4d.view_colour = False
img_b = render(f"B_compact_{FRAME}.png")
obj.b4d.view_colour = True


def compare(a, b):
    mask = (np.abs(a - a[0, 0]).max(2) > 3) | (np.abs(b - b[0, 0]).max(2) > 3)
    diff = np.abs(a - b).max(2)[mask]
    mse = (np.abs(a - b)[mask] ** 2).mean()
    return diff.mean(), np.percentile(diff, 99), 10 * np.log10(255 ** 2 / max(mse, 1e-9))


ma, pa, psnr_a = compare(img_a, img_c)
mb, pb, psnr_b = compare(img_b, img_c)
check(psnr_a > 45, f"full quality vs reference: mean {ma:.2f} levels, p99 {pa:.1f}, PSNR {psnr_a:.1f} dB")
check(psnr_b < psnr_a - 10, f"compact vs reference:      mean {mb:.2f} levels, p99 {pb:.1f}, PSNR {psnr_b:.1f} dB")

# ---- per-frame cost -------------------------------------------------------------------------
times = []
for f in range(FRAME + 1, FRAME + 11):
    t = time.perf_counter()
    scene.frame_set(f)
    times.append((time.perf_counter() - t) * 1000)
print(f"frame change with full colour: median {np.median(times):.1f} ms | {playback.status(obj)}")

print("RESULT", "OK" if not failures else f"{len(failures)} FAILED: {failures}", flush=True)
sys.exit(1 if failures else 0)
