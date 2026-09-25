"""Feature test for the editing / look tools (background Blender, isolated profile).

    set BLENDER_USER_RESOURCES=%TEMP%\\b4d_test_profile
    blender -b --factory-startup --python dev/test_features.py -- <extension.zip> <take .zip or folder> <image dir>

Verifies crop sides (in world space), feather, crop box (+ invert), clean-up, colour,
opacity, density, echoes, split, cut, trims, speed and time remap, and renders the
demo images used in the documentation.
"""
import os
import sys

import bpy
import numpy as np
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
ext_zip, take, img_dir = (os.path.abspath(a) for a in argv[:3])
os.makedirs(img_dir, exist_ok=True)
failures = []


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        failures.append(msg)


bpy.ops.extensions.package_install_files(filepath=ext_zip, repo="user_default", enable_on_install=True)
pkg = next(k for k in bpy.context.preferences.addons.keys() if k.endswith("blender_4dgs_viewer_editor"))
b4d = sys.modules[pkg]
shading, timing, playback = b4d.shading, b4d.timing, b4d.playback

for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
scene = bpy.context.scene
bpy.ops.b4d.import_sequence(filepath=take, fps=30, setup_scene=True)
while b4d.jobs._jobs:
    b4d.jobs._tick()
b4d.jobs._tick()
obj = bpy.context.active_object
mod = obj.modifiers[shading.MODIFIER]
n = len(playback.get_cache(obj.b4d.cache_dir).counts)


def evaluated(o=None):
    o = o or obj
    dg = bpy.context.evaluated_depsgraph_get()
    gs = o.evaluated_get(dg).evaluated_geometry()      # keep alive while reading
    pc = gs.pointcloud
    if pc is None or len(pc.points) == 0:
        return 0, np.zeros((0, 3)), {}
    cnt = len(pc.points)
    pos = np.empty(cnt * 3, np.float32)
    pc.attributes["position"].data.foreach_get("vector", pos)
    pos = pos.reshape(-1, 3)
    m = np.array(o.matrix_world)
    world = pos @ m[:3, :3].T + m[:3, 3]
    op = np.empty(cnt, np.float32); pc.attributes["splat_opacity"].data.foreach_get("value", op)
    col = np.empty(cnt * 3, np.float32); pc.attributes["splat_color"].data.foreach_get("vector", col)
    return cnt, world, {"opacity": op, "color": col.reshape(-1, 3)}


def reset():
    bpy.ops.b4d.reset_look(group="ALL")
    bpy.ops.b4d.reset_timing()
    obj.b4d.echoes = 0
    obj.b4d.density = 1.0


def render(name, pct=50):
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_percentage = pct
    scene.render.filepath = os.path.join(img_dir, name)
    bpy.ops.render.render(write_still=True)


check(not list(mod.node_warnings), f"node group has no warnings {[w.message for w in mod.node_warnings]}")
scene.frame_set(300)
base, world, attrs = evaluated()
lo, hi = world.min(0), world.max(0)
size = hi - lo
check(base > 50000, f"baseline frame 300: {base} splats, world size {np.round(size, 2)}")
render("hero.png", 100)

# ---- crop sides (world axes: -X left, +X right, -Y front, +Y back, Z up) ------------------
for side, axis, low in (("Top", 2, False), ("Bottom", 2, True), ("Left", 0, True), ("Right", 0, False),
                        ("Front", 1, True), ("Back", 1, False)):
    reset(); scene.frame_set(300)
    shading.set_input(mod, f"Crop {side}", 0.4); obj.update_tag()
    cnt, w, _ = evaluated()
    bmin = np.array(shading.get_input(mod, "Bounds Min")); bmax = np.array(shading.get_input(mod, "Bounds Max"))
    # the crop works on whole-take bounds; express the cut plane in world space
    ok = cnt < base and (w[:, axis].min() >= lo[axis] + 0.0 if low else True)
    if low:
        ok = ok and w[:, axis].min() > lo[axis] + 0.05 * size[axis]
    else:
        ok = ok and w[:, axis].max() < hi[axis] - 0.05 * size[axis]
    check(ok, f"Crop {side} 0.4 removes the {side.lower()} ({base} -> {cnt})")

reset(); scene.frame_set(300)
shading.set_input(mod, "Crop Bottom", 0.45); shading.set_input(mod, "Crop Feather", 0.15); obj.update_tag()
cnt_f, _w, a_f = evaluated()
shading.set_input(mod, "Crop Feather", 0.0); obj.update_tag()
cnt_h, _w, a_h = evaluated()
check(a_f["opacity"].mean() < a_h["opacity"].mean(), f"feather fades edge splats (mean opacity {a_h['opacity'].mean():.3f} -> {a_f['opacity'].mean():.3f})")
shading.set_input(mod, "Crop Feather", 0.12); obj.update_tag()
render("feature_crop.png")

# ---- crop box ------------------------------------------------------------------------------
reset(); scene.frame_set(300)
bpy.ops.b4d.add_crop_box()
box = bpy.context.active_object
box_name = box.name
cnt_full, _w, _a = evaluated()
check(cnt_full >= base * 0.99, f"crop box around the take keeps everything ({cnt_full}/{base})")
box.scale = (box.scale.x, box.scale.y, box.scale.z * 0.3)
box.location.z = lo[2] + size[2] * 0.8
bpy.context.view_layer.update(); obj.update_tag()
cnt_box, w_box, _a = evaluated()
check(0 < cnt_box < base * 0.6 and w_box[:, 2].min() > lo[2] + size[2] * 0.45, f"shrunken crop box keeps the upper body only ({cnt_box})")
render("feature_crop_box.png")
shading.set_input(mod, "Invert Crop Box", True); obj.update_tag()
cnt_inv, _w, _a = evaluated()
check(abs(cnt_inv + cnt_box - base) < base * 0.02, f"inverted box keeps the rest ({cnt_inv} + {cnt_box} ~ {base})")
bpy.context.view_layer.objects.active = obj
bpy.ops.b4d.remove_crop_box()
check(bpy.data.objects.get(box_name) is None and not shading.get_input(mod, "Use Crop Box"), "crop box removed")

# ---- clean-up, opacity, colour, density ------------------------------------------------------
reset(); scene.frame_set(300)
_c, _w, a0 = evaluated()
shading.set_input(mod, "Max Splat Radius", 0.02); obj.update_tag()
c, _w, _a = evaluated()
check(c < base, f"Max Splat Radius 2 cm removes large splats ({base} -> {c})")
reset(); shading.set_input(mod, "Min Opacity", 0.2); obj.update_tag()   # the sample take's opacities sit around 0.2
c, _w, a = evaluated()
check(0 < c < base and a["opacity"].min() >= 0.2 - 1e-3, f"Min Opacity 0.2 ({base} -> {c})")
reset(); shading.set_input(mod, "Opacity", 0.5); obj.update_tag()
_c, _w, a = evaluated()
check(abs(a["opacity"].mean() / a0["opacity"].mean() - 0.5) < 0.02, "Opacity 0.5 halves opacity")
reset(); shading.set_input(mod, "Exposure", 1.0); obj.update_tag()
_c, _w, a = evaluated()
check(abs(a["color"].mean() / a0["color"].mean() - 2.0) < 0.05, "Exposure +1 doubles colour")
reset(); shading.set_input(mod, "Saturation", 0.0); obj.update_tag()
_c, _w, a = evaluated()
check(np.abs(a["color"] - a["color"].mean(1, keepdims=True)).max() < 1e-3, "Saturation 0 gives grey")
reset(); shading.set_input(mod, "Hue Shift", 0.45); shading.set_input(mod, "Saturation", 1.8)
shading.set_input(mod, "Exposure", 0.4); obj.update_tag()
render("feature_color.png")
reset(); obj.b4d.density = 0.25; scene.frame_set(300)
c, _w, _a = evaluated()
check(abs(c / base - 0.25) < 0.02, f"Density 25% ({c}/{base})")

# ---- echoes ------------------------------------------------------------------------------------
reset(); obj.b4d.echoes, obj.b4d.echo_spacing, obj.b4d.echo_fade, obj.b4d.echo_density = 3, 12, 0.8, 0.8
scene.frame_set(420)
c, _w, _a = evaluated()
check(len(obj.data.vertices) > playback.get_cache(obj.b4d.cache_dir).counts[419] * 2, f"3 echoes add splats ({playback.status(obj)})")
render("feature_echoes.png")

# ---- timing: speed, trims, time remap --------------------------------------------------------
reset(); scene.frame_set(1)
obj.b4d.speed = 0.5
scene.frame_set(101)
check(playback.status(obj).startswith("Frame 51/"), f"speed 0.5 at frame 101 -> {playback.status(obj)}")
reset(); scene.frame_set(200)
bpy.ops.b4d.trim_to_playhead(side="START")
check(obj.b4d.trim_in == 200 and obj.b4d.start_frame == 200, f"trim start at 200 (in {obj.b4d.trim_in}, start {obj.b4d.start_frame})")
scene.frame_set(250); check(playback.status(obj).startswith("Frame 250/"), "trimmed take keeps its timing")
reset(); scene.frame_set(1)
bpy.ops.b4d.remap_key()
scene.frame_set(101); obj.b4d.remap_frame = 26; bpy.ops.b4d.remap_key()
scene.frame_set(51)
check(obj.b4d.use_time_remap and 12 <= int(playback.status(obj).split()[1].split("/")[0]) <= 15,
      f"time remap keys interpolate (frame 51 -> {playback.status(obj)})")
obj.animation_data_clear()
reset()

# ---- playback speed (scene-wide and keyframed) --------------------------------------------------
def frame_no(o=None):
    return int(playback.status(o or obj).split()[1].split("/")[0])


def constant_keys(id_data, path, keys):
    for frame, value in keys:
        setattr(id_data.b4d if path.startswith("b4d.") else id_data, path.split(".")[-1], value)
        id_data.keyframe_insert(data_path=path, frame=frame)
    coll, fc = timing.find_fcurve(id_data, path)
    for kp in fc.keyframe_points:
        kp.interpolation = "CONSTANT"


reset(); scene.frame_set(1)
fps_before = scene.render.fps
scene.b4d_speed = 0.5
scene.frame_set(101)
check(frame_no() == 51 and scene.render.fps == fps_before, f"scene Playback Speed 0.5: frame 101 -> take frame {frame_no()}, fps still {scene.render.fps}")
obj.b4d.speed = 2.0
scene.frame_set(101)
check(frame_no() == 101, f"take Speed 2 x scene 0.5 = normal speed ({frame_no()})")
obj.b4d.speed = 1.0
scene.b4d_speed = 1.0
constant_keys(scene, "b4d_speed", [(1, 1.0), (51, 0.5)])
scene.frame_set(101)
check(frame_no() == 76, f"keyframed scene speed ramp: frame 101 -> take frame {frame_no()} (expected 76)")
bpy.ops.b4d.fit_timeline()
check(scene.frame_end == 50 + 2 * (n - 50), f"fit timeline follows the ramp (end {scene.frame_end})")
scene.animation_data_clear(); scene.b4d_speed = 1.0
constant_keys(obj, "b4d.speed", [(1, 2.0), (51, 1.0)])
scene.frame_set(101)
check(frame_no() == 151, f"keyframed take speed ramp: frame 101 -> take frame {frame_no()} (expected 151)")
bpy.ops.b4d.reset_timing()
check(timing.find_fcurve(obj, "b4d.speed")[1] is None and obj.b4d.start_frame == 1, "Reset Timing removes speed keys")
obj.animation_data_clear()
reset(); bpy.ops.b4d.fit_timeline()

# ---- split & cut -------------------------------------------------------------------------------
scene.frame_set(400)
bpy.ops.b4d.split()
b = bpy.context.active_object
check(b is not obj and b.b4d.trim_in == 400 and obj.b4d.trim_out == 399, f"split at 400 -> A 1-{obj.b4d.trim_out}, B {b.b4d.trim_in}-end")
scene.frame_set(399)
check(len(obj.data.vertices) > 0 and len(b.data.vertices) == 0, "frame 399: only part A visible")
scene.frame_set(400)
check(len(obj.data.vertices) == 0 and len(b.data.vertices) > 0, "frame 400: only part B visible")
bpy.data.objects.remove(b)
bpy.context.view_layer.objects.active = obj
reset()
bpy.ops.b4d.cut(first=100, last=199, close_gap=True)
c2 = bpy.context.active_object
check(c2 is not obj and obj.b4d.trim_out == 99 and c2.b4d.trim_in == 200 and c2.b4d.start_frame == 100,
      f"cut 100-199 with close gap (A ..{obj.b4d.trim_out}, B {c2.b4d.trim_in}.. from frame {c2.b4d.start_frame})")
scene.frame_set(100)
check(playback.status(c2).startswith("Frame 200/") and len(obj.data.vertices) == 0, "gap closed: frame 100 shows take frame 200")
bpy.ops.b4d.fit_timeline()
check(scene.frame_end == n - 100, f"fit timeline after cut: 1-{scene.frame_end}")

print("RESULT", "OK" if not failures else f"{len(failures)} FAILED: {failures}", flush=True)
sys.exit(1 if failures else 0)
