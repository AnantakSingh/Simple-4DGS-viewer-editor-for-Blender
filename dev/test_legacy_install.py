"""Classic add-on install of the release zip (background Blender, isolated profile).

    set BLENDER_USER_RESOURCES=%TEMP%\\b4d_test_profile
    blender -b --factory-startup --python dev/test_legacy_install.py -- <release zip> <small take folder>

Installs through Preferences > Add-ons > Install legacy Add-on (bpy.ops.preferences.addon_install),
enables it, converts and streams a take, and checks the cache-location fallback that
doesn't depend on extension-only APIs.
"""
import os
import sys
import time

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
zip_path, take = (os.path.abspath(a) for a in argv[:2])
failures = []


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        failures.append(msg)


bpy.ops.preferences.addon_install(filepath=zip_path, overwrite=True)
bpy.ops.preferences.addon_enable(module="blender_4dgs_viewer_editor")
m = sys.modules.get("blender_4dgs_viewer_editor")
check(m is not None and "blender_4dgs_viewer_editor" in bpy.context.preferences.addons,
      f"installed and enabled as a classic add-on ({m and m.__file__})")
check(hasattr(bpy.ops.b4d, "import_sequence"), "operators registered")

for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
bpy.ops.b4d.import_sequence(filepath=take, fps=30, setup_scene=True)
while m.jobs._jobs:
    m.jobs._tick()
    time.sleep(0.2)
m.jobs._tick()
obj = bpy.context.active_object
check(obj is not None and m.playback.get_cache(obj.b4d.cache_dir) is not None and not obj.b4d.last_error,
      f"take converted: {obj and obj.b4d.cache_dir} {obj and obj.b4d.last_error}")
bpy.context.scene.frame_set(5)
gs = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).evaluated_geometry()
check(gs.pointcloud is not None and len(gs.pointcloud.points) > 1000, f"streams splats: {m.playback.status(obj)}")
print("flag:", m.convert.view_dependence_flag(m.convert.read_meta(obj.b4d.cache_dir)))

# Read-only take location: the cache must fall back to a user folder without extension APIs.
src = m.convert.find_source(take)
real_access = os.access
os.access = lambda path, mode: False
try:
    fallback = m.props.cache_dir_for(src)
finally:
    os.access = real_access
check(os.path.isdir(os.path.dirname(fallback)) and "blender_4dgs_viewer_editor" in fallback,
      f"read-only fallback cache location: {fallback}")

print("RESULT", "OK" if not failures else f"{len(failures)} FAILED: {failures}", flush=True)
sys.exit(1 if failures else 0)
