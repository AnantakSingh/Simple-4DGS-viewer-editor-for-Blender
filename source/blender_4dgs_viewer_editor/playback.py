"""Streams cached splat frames into sequence objects as the timeline changes.

With a full-quality cache, each splat's view-dependent colour is evaluated for the
current viewpoint (render camera, or the viewport's eye) every frame, and again
when the viewport view moves while paused.
"""
import os
import time
from collections import OrderedDict

import bpy
import numpy as np
from bpy.app.handlers import persistent
from mathutils import Vector

from . import convert, shading, sh, timing

_loaded = {}        # object name -> key of what is currently in its mesh
_status = {}        # object name -> short status line for the UI
_shown = {}         # object name -> (positions, sh arrays, degree) of the splats in the mesh, for re-colouring
_view_key = {}      # object name -> viewpoint key the current colours were computed for
_rendering = False


# --------------------------------------------------------------------------- cache access

class _Cache:
    def __init__(self, root, meta, keep=32):
        self.root, self.meta = root, meta
        self.frame_numbers, self.counts = meta["frame_numbers"], meta["counts"]
        self.sh_degree = meta.get("sh_degree", 0) if meta.get("sh_requested") else 0
        self._lru, self._keep = OrderedDict(), keep

    def _get(self, key, path):
        arr = self._lru.get(key)
        if arr is None:
            arr = np.load(path)
            self._lru[key] = arr
            while len(self._lru) > self._keep:
                self._lru.popitem(last=False)
        else:
            self._lru.move_to_end(key)
        return arr

    def frame(self, index):
        return self._get(index, convert.frame_path(self.root, self.frame_numbers[index]))

    def sh(self, index):
        """(n, 3 + 3k) float16: unclamped base colour + SH coefficients, or None."""
        if not self.sh_degree:
            return None
        return self._get(("sh", index), convert.sh_path(self.root, self.frame_numbers[index]))


_caches = {}


def get_cache(cache_dir):
    if not cache_dir:
        return None
    root = os.path.normpath(bpy.path.abspath(cache_dir))
    cache = _caches.get(root)
    if cache is None:
        meta = convert.read_meta(root)
        if meta is None:
            return None
        cache = _caches[root] = _Cache(root, meta)
    return cache


def drop_cache(cache_dir=None):
    if cache_dir is None:
        _caches.clear()
    else:
        _caches.pop(os.path.normpath(bpy.path.abspath(cache_dir)), None)
    _loaded.clear()
    _view_key.clear()


def status(obj):
    return _status.get(obj.name, "")


# --------------------------------------------------------------------------- viewpoint

def _camera_view(cam):
    m = cam.matrix_world
    if cam.data.type == "ORTHO":
        return "dir", (m.to_3x3() @ Vector((0.0, 0.0, -1.0))).normalized()
    return "eye", m.translation.copy()


def viewpoint(scene):
    """('eye', world point) or ('dir', world direction) that view-dependent colour is seen from.

    Renders and camera views use the scene camera; otherwise the largest 3D viewport
    showing Rendered / Material Preview shading (or else any 3D viewport)."""
    cam = scene.camera
    if _rendering or bpy.app.background:
        return _camera_view(cam) if cam else None
    best, best_score = None, -1
    wm = bpy.context.window_manager
    for window in (wm.windows if wm else ()):
        for area in window.screen.areas:
            if area.type != "VIEW_3D":
                continue
            space = area.spaces.active
            score = area.width * area.height + (10 ** 8 if space.shading.type in {"RENDERED", "MATERIAL"} else 0)
            if score > best_score:
                best, best_score = space, score
    if best is None:
        return _camera_view(cam) if cam else None
    r3d = best.region_3d
    if r3d.view_perspective == "CAMERA" and cam:
        return _camera_view(cam)
    inv = r3d.view_matrix.inverted()
    if r3d.is_perspective:
        return "eye", inv.translation.copy()
    return "dir", (inv.to_3x3() @ Vector((0.0, 0.0, -1.0))).normalized()


def _view_key_of(obj, view):
    if view is None:
        return None
    kind, v = view
    step = 0.005 if kind == "eye" else 0.002          # 5 mm, or about 0.1 degree
    return kind, tuple(round(c / step) for c in v), tuple(round(c, 5) for row in obj.matrix_world for c in row)


def _colors_for(obj, positions, sh_parts, degree, view):
    """Linear RGB for all shown splats seen from `view` (given in world space)."""
    kind, v = view
    inv = obj.matrix_world.inverted()
    if kind == "eye":
        eye, direction = np.array(inv @ v, dtype=np.float32), None
    else:
        eye, direction = None, np.array((inv.to_3x3() @ v).normalized(), dtype=np.float32)
    cols = [sh.view_colors(p, s_[:, :3], s_[:, 3:], degree, eye=eye, view_dir=direction)
            for p, s_ in zip(positions, sh_parts)]
    return cols[0] if len(cols) == 1 else np.concatenate(cols)


def _uses_view_colour(obj, cache):
    return obj.b4d.view_colour and cache is not None and cache.sh_degree > 0


# --------------------------------------------------------------------------- mesh upload

_FIELDS = (
    (shading.ATTR_ROT, "QUATERNION", "value", "rot"),
    (shading.ATTR_SCALE, "FLOAT_VECTOR", "vector", "scale"),
    (shading.ATTR_COLOR, "FLOAT_VECTOR", "vector", "color"),
    (shading.ATTR_OPACITY, "FLOAT", "value", "opacity"),
)


def _attr(me, name, data_type):
    attr = me.attributes.get(name)
    if attr is None or attr.data_type != data_type or attr.domain != "POINT":
        if attr is not None:
            me.attributes.remove(attr)
        attr = me.attributes.new(name, data_type, "POINT")
    return attr


def _write_mesh(me, splats, colors=None):
    me.clear_geometry()
    n = 0 if splats is None else len(splats)
    if n:
        me.vertices.add(n)
        me.attributes["position"].data.foreach_set(
            "vector", np.ascontiguousarray(splats["pos"], dtype=np.float32).ravel())
        for name, data_type, key, field in _FIELDS:
            values = colors if (field == "color" and colors is not None) else splats[field]
            _attr(me, name, data_type).data.foreach_set(key, np.ascontiguousarray(values, dtype=np.float32).ravel())
    me.update()


def _is_playing():
    screen = getattr(bpy.context, "screen", None)
    return bool(screen and screen.is_animation_playing)


def sequence_objects(scene):
    return [o for o in scene.objects if o.type == "MESH" and o.b4d.is_sequence]


def _frames_to_show(obj, scene, frame, n):
    """[(take index, opacity factor)] for the current frame plus its echoes."""
    s = obj.b4d
    remap = timing.remap_value(obj, frame) if s.use_time_remap else None
    clock = timing.clock_for(obj, scene)
    main = timing.take_index(s, frame, n, remap, clock)
    if main is None:
        return []
    shown = [(main, 1.0)]
    if s.echoes and not s.freeze and not s.use_time_remap:
        for k in range(1, s.echoes + 1):
            idx = timing.take_index(s, frame - k * s.echo_spacing, n, clock=clock)
            if idx is not None and idx != main:
                shown.append((idx, s.echo_fade ** k))
    return shown


def update_object(obj, frame, force=False, scene=None):
    s = obj.b4d
    scene = scene or bpy.context.scene
    if not s.is_sequence or s.job_id:
        return          # still converting
    if not s.enabled:
        if _loaded.get(obj.name) != "off":
            _write_mesh(obj.data, None)
            _loaded[obj.name] = "off"
            _shown.pop(obj.name, None)
            _status[obj.name] = "Hidden"
        return
    cache = get_cache(s.cache_dir)
    if cache is None:
        _status[obj.name] = "Cache not found - set Cache or re-import"
        return

    n = len(cache.frame_numbers)
    shown = _frames_to_show(obj, scene, frame, n)
    fraction = s.density * (s.playback_detail if (_is_playing() and not _rendering) else 1.0)
    plan = []
    for k, (index, fade) in enumerate(shown):
        share = fraction if k == 0 else fraction * s.echo_density
        plan.append((index, max(1, round(cache.counts[index] * share)), fade))

    view_colour = _uses_view_colour(obj, cache)
    view = viewpoint(scene) if view_colour else None
    vkey = _view_key_of(obj, view) if view_colour else None
    key = (cache.root, tuple(plan), view_colour)
    if not force and _loaded.get(obj.name) == key and _view_key.get(obj.name) == vkey:
        return
    t0 = time.perf_counter()
    parts, sh_parts = [], []
    for index, count, fade in plan:
        part = cache.frame(index)[:count]
        if fade != 1.0:
            part = part.copy()
            part["opacity"] *= fade
        parts.append(part)
        if view_colour:
            sh_parts.append(cache.sh(index)[:count])
    splats = (parts[0] if len(parts) == 1 else np.concatenate(parts)) if parts else None
    colors = None
    if view_colour and parts and view is not None:
        positions = [p["pos"] for p in parts]
        colors = _colors_for(obj, positions, sh_parts, cache.sh_degree, view)
        _shown[obj.name] = (positions, sh_parts, cache.sh_degree)
    else:
        _shown.pop(obj.name, None)
    _write_mesh(obj.data, splats, colors)
    _loaded[obj.name] = key
    _view_key[obj.name] = vkey
    ms = 1000 * (time.perf_counter() - t0)
    if plan:
        total = sum(c for _i, c, _f in plan)
        echo = f" +{len(plan) - 1} echoes" if len(plan) > 1 else ""
        vd = " · full colour" if colors is not None else ""
        _status[obj.name] = f"Frame {plan[0][0] + 1}/{n}{echo} · {total / 1000:.0f}k splats{vd} · {ms:.0f} ms"
    else:
        _status[obj.name] = "Outside take (hidden)"


def recolor(obj, scene):
    """Re-evaluate view-dependent colour for the splats already in the mesh (view moved)."""
    data = _shown.get(obj.name)
    view = viewpoint(scene)
    if data is None or view is None:
        return False
    positions, sh_parts, degree = data
    colors = _colors_for(obj, positions, sh_parts, degree, view)
    me = obj.data
    if len(me.vertices) != len(colors):
        return False
    _attr(me, shading.ATTR_COLOR, "FLOAT_VECTOR").data.foreach_set("vector", colors.ravel())
    me.update()
    _view_key[obj.name] = _view_key_of(obj, view)
    return True


def _watch_view():
    """Timer: when the viewport eye moves while paused, re-colour full-quality takes."""
    try:
        scene = bpy.context.scene
        if scene is None or _rendering or _is_playing():
            return 0.25
        for obj in sequence_objects(scene):
            if obj.name in _shown and _view_key.get(obj.name) != _view_key_of(obj, viewpoint(scene)):
                recolor(obj, scene)
    except (ReferenceError, AttributeError, RuntimeError):
        pass
    return 0.25


def update_scene(scene, force=False):
    for obj in sequence_objects(scene):
        update_object(obj, scene.frame_current, force, scene)


def refresh_scene(scene):
    for obj in sequence_objects(scene):
        _loaded.pop(obj.name, None)
    update_scene(scene, force=True)


def refresh(obj):
    _loaded.pop(obj.name, None)
    scene = bpy.context.scene
    if scene is not None:
        update_object(obj, scene.frame_current, force=True, scene=scene)


# --------------------------------------------------------------------------- handlers

@persistent
def _on_frame_change(scene, _depsgraph=None):
    update_scene(scene)


@persistent
def _on_playback_end(scene, _depsgraph=None):
    update_scene(scene)     # back to full detail when playback stops


@persistent
def _on_render_init(scene, _depsgraph=None):
    global _rendering
    _rendering = True
    update_scene(scene, force=True)     # full detail, colours seen from the render camera


@persistent
def _on_render_end(_scene, _depsgraph=None):
    global _rendering
    _rendering = False
    _view_key.clear()                   # lets the viewport watcher restore viewport colours


@persistent
def _on_reload(*_args):
    """After file load / undo / redo the meshes may hold stale data: reload everything."""
    _loaded.clear()
    for scene in bpy.data.scenes:
        update_scene(scene, force=True)


@persistent
def _on_load(*_args):
    from . import jobs
    drop_cache()
    for obj in bpy.data.objects:
        if obj.type == "MESH" and obj.b4d.job_id and jobs.get(obj.b4d.job_id) is None:
            obj.b4d.job_id = ""
            obj.b4d.last_error = "Conversion was interrupted. Click Convert to resume."
    shading_needed = any(o.b4d.is_sequence for o in bpy.data.objects if o.type == "MESH")
    if shading_needed:
        shading.ensure()        # upgrade node group/material saved by an older version
    _on_reload()


@persistent
def _on_save_pre(*_args):
    # Keep .blend files small: the splats are reloaded from the cache on open.
    for obj in bpy.data.objects:
        if obj.type == "MESH" and obj.b4d.is_sequence and len(obj.data.vertices):
            obj.data.clear_geometry()
    _loaded.clear()


@persistent
def _on_save_post(*_args):
    _on_reload()


_HANDLERS = (
    ("frame_change_pre", _on_frame_change),
    ("animation_playback_post", _on_playback_end),
    ("render_init", _on_render_init),
    ("render_complete", _on_render_end),
    ("render_cancel", _on_render_end),
    ("load_post", _on_load),
    ("undo_post", _on_reload),
    ("redo_post", _on_reload),
    ("save_pre", _on_save_pre),
    ("save_post", _on_save_post),
)


def register():
    for name, fn in _HANDLERS:
        lst = getattr(bpy.app.handlers, name, None)
        if lst is not None and fn not in lst:
            lst.append(fn)
    # Enabling the add-on in an already-open file: load what's there.
    bpy.app.timers.register(lambda: (_on_reload(), None)[1], first_interval=0.1)
    if not bpy.app.background and not bpy.app.timers.is_registered(_watch_view):
        bpy.app.timers.register(_watch_view, first_interval=1.0, persistent=True)


def unregister():
    if bpy.app.timers.is_registered(_watch_view):
        bpy.app.timers.unregister(_watch_view)
    sh.shutdown()
    for name, fn in _HANDLERS:
        lst = getattr(bpy.app.handlers, name, None)
        if lst is not None and fn in lst:
            lst.remove(fn)
    drop_cache()
