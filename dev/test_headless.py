"""End-to-end test of the packaged extension in background Blender.

Use an isolated profile so your own Blender setup is untouched:

    set BLENDER_USER_RESOURCES=%TEMP%\b4d_test_profile
    blender -b --factory-startup --python dev/test_headless.py -- <extension.zip> <zip take> <folder take> <out dir>

Checks: install, import from .zip (cached or converted), import from a folder with
background conversion, playback, EEVEE + Cycles renders, save/reopen.
"""
import os
import sys
import time

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
ext_zip, zip_take, folder_take, out_dir = (os.path.abspath(a) for a in argv[:4])
os.makedirs(out_dir, exist_ok=True)
failures = []


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        failures.append(msg)


# 1. install + enable
bpy.ops.extensions.package_install_files(filepath=ext_zip, repo="user_default", enable_on_install=True)
pkg = next((k for k in bpy.context.preferences.addons.keys() if k.endswith("blender_4dgs_viewer_editor")), None)
check(pkg is not None, f"extension installed and enabled ({pkg})")
mod = sys.modules[pkg]
jobs, playback = mod.jobs, mod.playback


def wait_for_jobs(timeout=600):
    t0 = time.time()
    while jobs._jobs and time.time() - t0 < timeout:
        jobs._tick()        # timers don't run in background mode
        time.sleep(0.2)
    jobs._tick()


scene = bpy.context.scene
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)

# 2. import the take .zip
t0 = time.time()
bpy.ops.b4d.import_sequence(filepath=zip_take, fps=30, setup_scene=True)
wait_for_jobs()
a = bpy.context.active_object
check(a is not None and a.b4d.is_sequence and not a.b4d.last_error, f"zip import ({time.time() - t0:.1f}s): {a and a.name}")
check(playback.get_cache(a.b4d.cache_dir) is not None, f"zip cache valid at {a.b4d.cache_dir}")
check(scene.camera is not None and scene.frame_end - scene.frame_start + 1 == len(playback.get_cache(a.b4d.cache_dir).counts),
      f"viewing set up: frames {scene.frame_start}-{scene.frame_end}")

# 3. import a folder by picking one of its .ply files -> background conversion
ply = sorted(f for f in os.listdir(folder_take) if f.lower().endswith(".ply"))[0]
t0 = time.time()
bpy.ops.b4d.import_sequence(filepath=os.path.join(folder_take, ply), fps=30, start_frame=1, setup_scene=False)
b = bpy.context.active_object
check(bool(b.b4d.job_id), "folder import started a background conversion")
wait_for_jobs()
check(not b.b4d.job_id and not b.b4d.last_error, f"folder conversion finished ({time.time() - t0:.1f}s) {b.b4d.last_error}")
check(playback.get_cache(b.b4d.cache_dir) is not None, f"folder cache valid at {b.b4d.cache_dir}")

# 4. playback + renders
b.b4d.enabled = False
scene.frame_set(300)
gs = a.evaluated_get(bpy.context.evaluated_depsgraph_get()).evaluated_geometry()
n = len(gs.pointcloud.points) if gs.pointcloud else 0
check(n > 50000, f"frame 300 streamed: {n} splats | {playback.status(a)}")
check(len(b.data.vertices) == 0, "hidden take holds no splats")

prefs = bpy.context.preferences.addons["cycles"].preferences
for dev in ("OPTIX", "CUDA"):
    try:
        prefs.compute_device_type = dev
        prefs.get_devices()
        if any(d.type == dev for d in prefs.devices):
            for d in prefs.devices:
                d.use = d.type == dev
            scene.cycles.device = "GPU"
            break
    except TypeError:
        pass
scene.render.resolution_percentage = int(os.environ.get("B4D_RES", "50"))
for engine in ("BLENDER_EEVEE", "CYCLES"):
    scene.render.engine = engine
    scene.render.filepath = os.path.join(out_dir, f"{engine.lower()}_0300.png")
    t0 = time.time()
    bpy.ops.render.render(write_still=True)
    check(os.path.exists(scene.render.filepath), f"{engine} render ({time.time() - t0:.1f}s)")

# 5. save + reopen
blend = os.path.join(out_dir, "b4d_test.blend")
name_a = a.name
bpy.ops.wm.save_as_mainfile(filepath=blend)
check(len(a.data.vertices) > 0, "splats restored after save")
size_mb = os.path.getsize(blend) / 1e6
check(size_mb < 5, f"saved .blend is small ({size_mb:.2f} MB)")
bpy.ops.wm.open_mainfile(filepath=blend)
a = bpy.data.objects[name_a]
scene = bpy.context.scene
scene.frame_set(450)
gs = a.evaluated_get(bpy.context.evaluated_depsgraph_get()).evaluated_geometry()
check(gs.pointcloud is not None and len(gs.pointcloud.points) > 50000,
      f"reopened file streams frame 450 ({playback.status(a)})")

print("RESULT", "OK" if not failures else f"{len(failures)} FAILED: {failures}", flush=True)
sys.exit(1 if failures else 0)
