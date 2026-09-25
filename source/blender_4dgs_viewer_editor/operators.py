import math
import os
import shutil
import zipfile

import bpy
from bpy_extras.io_utils import ImportHelper
from mathutils import Euler, Matrix, Vector

from . import convert, jobs, playback, props, shading, timing

UP_AXES = [
    ("NEG_Y", "-Y (Y-down)", "Source is Y-down and faces +Z (most 3DGS / 4DGS exports)"),
    ("POS_Y", "+Y", "Source is Y-up and faces +Z"),
    ("POS_Z", "+Z", "Source is Z-up and faces -Y"),
]
# Source -> Blender rotation: up becomes +Z and the performer faces -Y, i.e. towards
# Blender's Front view, so Left/Right/Front/Back match the numpad views.
UP_ROTATION = {"NEG_Y": (-math.pi / 2, 0, math.pi), "POS_Y": (math.pi / 2, 0, 0), "POS_Z": (0, 0, 0)}
CAMERA, RIG, WORLD = "Splat Camera", "Splat Camera Rig", "Splat Backdrop"


# --------------------------------------------------------------------------- helpers

def _find_job_object(job_id):
    return next((o for o in bpy.data.objects if o.type == "MESH" and o.b4d.job_id == job_id), None)


def start_conversion(obj, rebuild=False, setup_scene=False):
    s = obj.b4d
    if rebuild and os.path.isdir(s.cache_dir):
        # Remove only what the converter writes, in case Cache points somewhere unexpected.
        shutil.rmtree(os.path.join(s.cache_dir, "frames"), ignore_errors=True)
        for name in ("meta.json", "source.sig"):
            try:
                os.remove(os.path.join(s.cache_dir, name))
            except OSError:
                pass
    playback.drop_cache(s.cache_dir)
    p = props.prefs()
    scene_name = bpy.context.scene.name

    def on_done(job):
        o = _find_job_object(job.id)
        if o is None:
            return
        o.b4d.job_id = ""
        if job.cancelled:
            o.b4d.last_error = "Conversion stopped. Click Convert to resume where it left off."
        elif job.error:
            o.b4d.last_error = f"Conversion failed: {job.error}"
        else:
            o.b4d.last_error = ""
            playback.drop_cache(o.b4d.cache_dir)
            apply_up_axis(o)
            scene = bpy.data.scenes.get(scene_name) or bpy.context.scene
            if setup_scene:
                setup_view(scene, o)
            playback.refresh(o)

    job = jobs.start(s.source, s.cache_dir, p.workers if p else 0, on_done, with_sh=s.full_quality)
    s.job_id = job.id
    s.last_error = ""
    return job


def apply_up_axis(obj):
    """Orient the object for its Up Axis and give the crop its upright take bounds."""
    s = obj.b4d
    euler = UP_ROTATION[s.up_axis]
    obj.rotation_euler = euler
    mod = obj.modifiers.get(shading.MODIFIER)
    if mod is None:
        return
    shading.set_input(mod, "Upright", euler)
    cache = playback.get_cache(s.cache_dir)
    if cache is not None:
        m = Euler(euler).to_matrix()
        lo, hi = cache.meta["bounds_min"], cache.meta["bounds_max"]
        corners = [m @ Vector((x, y, z)) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
        shading.set_input(mod, "Bounds Min", [min(c[i] for c in corners) for i in range(3)])
        shading.set_input(mod, "Bounds Max", [max(c[i] for c in corners) for i in range(3)])
    obj.update_tag()


def world_bounds(obj, meta):
    lo, hi = Vector(meta["bounds_min"]), Vector(meta["bounds_max"])
    m = obj.matrix_basis if obj.parent is None else obj.matrix_world
    corners = [m @ Vector((x, y, z)) for x in (lo.x, hi.x) for y in (lo.y, hi.y) for z in (lo.z, hi.z)]
    return (Vector([min(c[i] for c in corners) for i in range(3)]),
            Vector([max(c[i] for c in corners) for i in range(3)]))


def fit_timeline(scene):
    """Set the scene frame range to cover every take in the scene."""
    spans = []
    for o in playback.sequence_objects(scene):
        cache = playback.get_cache(o.b4d.cache_dir)
        if cache is not None:
            spans.append(timing.timeline_span(o.b4d, len(cache.counts), timing.clock_for(o, scene)))
    if spans:
        scene.frame_start = max(0, min(a for a, _b in spans))
        scene.frame_end = max(b for _a, b in spans)


def setup_view(scene, obj):
    """Frame range, camera, backdrop, colour management and render settings for viewing."""
    cache = playback.get_cache(obj.b4d.cache_dir)
    if cache is None:
        return
    fit_timeline(scene)

    # Camera: in front of the performer (source +Z), framing the whole take.
    lo, hi = world_bounds(obj, cache.meta)
    size = hi - lo
    target = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z + size.z / 2))
    m3 = (obj.matrix_basis if obj.parent is None else obj.matrix_world).to_3x3()
    front = m3 @ Vector((0, 0, 1))
    front.z = 0
    front = front.normalized() if front.length > 1e-6 else Vector((0, -1, 0))

    rig = bpy.data.objects.get(RIG)
    if rig is None:
        rig = bpy.data.objects.new(RIG, None)
        rig.empty_display_type = "CIRCLE"
    cam = bpy.data.objects.get(CAMERA)
    if cam is None:
        cam = bpy.data.objects.new(CAMERA, bpy.data.cameras.new(CAMERA))
    for o in (rig, cam):
        if o.name not in scene.collection.objects and not any(o.name in c.objects for c in scene.collection.children_recursive):
            scene.collection.objects.link(o)
    rig.location = (target.x, target.y, lo.z)
    rig.rotation_euler = (0, 0, 0)
    rig.empty_display_size = max(size.x, size.y) * 0.75 + 0.1

    cam.data.lens = 35.0
    cam.data.clip_start = 0.02
    cam.data.sensor_fit = "AUTO"
    aspect = scene.render.resolution_x / max(1, scene.render.resolution_y)
    fov_h = 2 * math.atan(36.0 / (2 * cam.data.lens))
    fov_v = 2 * math.atan(math.tan(fov_h / 2) / aspect) if aspect >= 1 else fov_h
    half = max(size.z, max(size.x, size.y) / max(aspect, 1e-3)) * 0.55
    dist = half / math.tan(fov_v / 2) + max(size.x, size.y) / 2
    cam_world = target + front * dist
    cam.parent = rig
    cam.matrix_parent_inverse = Matrix.Identity(4)
    cam.location = cam_world - rig.location
    cam.rotation_euler = (target - cam_world).to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam

    world = scene.world
    if world is None or world.name in {"World", WORLD}:
        world = bpy.data.worlds.get(WORLD) or bpy.data.worlds.new(WORLD)
        if getattr(world, "node_tree", None) is None:
            world.use_nodes = True
        bg = next((n for n in world.node_tree.nodes if n.type == "BACKGROUND"), None)
        if bg:
            bg.inputs["Color"].default_value = (0.02, 0.02, 0.02, 1.0)
            bg.inputs["Strength"].default_value = 1.0
        scene.world = world

    # Splat colours are display sRGB; the Standard view transform shows them 1:1.
    try:
        scene.view_settings.view_transform = "Standard"
        scene.view_settings.look = "None"
    except TypeError:
        pass
    r = scene.render
    r.use_lock_interface = True         # frames are swapped in while rendering
    r.use_persistent_data = False
    if hasattr(scene, "eevee"):
        scene.eevee.taa_samples = max(scene.eevee.taa_samples, 16)
        scene.eevee.taa_render_samples = max(scene.eevee.taa_render_samples, 64)
    if hasattr(scene, "cycles"):
        c = scene.cycles
        c.transparent_max_bounces = max(c.transparent_max_bounces, 512)  # rays cross many splats
        c.samples = min(c.samples, 128)             # splats are emissive: few samples converge
        c.preview_samples = min(c.preview_samples, 32)

    wm = bpy.context.window_manager
    for window in (wm.windows if wm else ()):
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                space = area.spaces.active
                space.shading.type = "RENDERED"
                space.clip_start = min(space.clip_start, 0.01)
                space.region_3d.view_perspective = "CAMERA"


def create_sequence_object(context, source, cache_dir, up_axis, start_frame, full_quality=True):
    me = bpy.data.meshes.new(source.take)
    obj = bpy.data.objects.new(source.take, me)
    (context.collection or context.scene.collection).objects.link(obj)
    s = obj.b4d
    s.is_sequence = True
    s.take = source.take
    s.source = source.root
    s.start_frame = start_frame
    s.full_quality = full_quality
    s.cache_dir = cache_dir
    shading.ensure_modifier(obj)
    s.up_axis = up_axis
    apply_up_axis(obj)
    select_only(context, obj)
    return obj


def select_only(context, obj):
    for o in context.selected_objects:
        o.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj


def active_sequence(context):
    obj = context.active_object
    return obj if obj is not None and obj.type == "MESH" and obj.b4d.is_sequence else None


# --------------------------------------------------------------------------- operators

class B4D_OT_import(bpy.types.Operator, ImportHelper):
    """Import a 4DGS take (folder of 3DGS .ply frames, one of its .ply files, or a .zip of them)"""
    bl_idname = "b4d.import_sequence"
    bl_label = "Import Splat Sequence"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ""
    filter_glob: bpy.props.StringProperty(default="*.ply;*.zip", options={"HIDDEN"})
    directory: bpy.props.StringProperty(subtype="DIR_PATH", options={"HIDDEN", "SKIP_SAVE"})

    fps: bpy.props.IntProperty(name="Frame Rate", default=30, min=1, max=240,
                               description="Playback rate of the capture (sets the scene frame rate)")
    start_frame: bpy.props.IntProperty(name="Start Frame", default=1,
                                       description="Timeline frame for the first frame of the take")
    up_axis: bpy.props.EnumProperty(name="Up Axis", items=UP_AXES, default="NEG_Y")
    full_quality: bpy.props.BoolProperty(
        name="Full-Quality Colour", default=False,
        description="Also keep view-dependent colour (spherical harmonics) so splats look exactly like the "
                    "original capture. Off = compact cache: most stable, fastest, about 4x smaller. "
                    "A compact cache can be upgraded later from the Look panel")
    setup_scene: bpy.props.BoolProperty(
        name="Set Up Viewing", default=True,
        description="Frame range, camera, dark backdrop, Standard colour and rendered viewport")

    def invoke(self, context, event):
        if self.filepath:       # dropped onto the viewport
            return context.window_manager.invoke_props_dialog(self)
        return ImportHelper.invoke(self, context, event)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, "fps")
        layout.prop(self, "start_frame")
        layout.prop(self, "up_axis")
        layout.prop(self, "full_quality")
        layout.prop(self, "setup_scene")

    def execute(self, context):
        path = self.filepath
        if not path or not os.path.exists(path):
            path = self.directory or path
        try:
            source = convert.find_source(bpy.path.abspath(path))
        except (OSError, ValueError, zipfile.BadZipFile) as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        cache_dir = props.cache_dir_for(source, context)
        obj = create_sequence_object(context, source, cache_dir, self.up_axis, self.start_frame,
                                     self.full_quality)
        if self.setup_scene:
            context.scene.render.fps = self.fps
            context.scene.render.fps_base = 1.0

        if convert.cache_is_valid(cache_dir, source, need_sh=self.full_quality):
            if self.setup_scene:
                setup_view(context.scene, obj)
            playback.refresh(obj)
            self.report({"INFO"}, f"{source.take}: {len(source.frames)} frames (cached)")
        else:
            start_conversion(obj, setup_scene=self.setup_scene)
            self.report({"INFO"}, f"{source.take}: converting {len(source.frames)} frames in the background")
        return {"FINISHED"}


class B4D_OT_convert(bpy.types.Operator):
    """Convert (or resume converting) the active take's splat cache"""
    bl_idname = "b4d.convert"
    bl_label = "Convert"
    bl_options = {"REGISTER"}

    rebuild: bpy.props.BoolProperty(name="Rebuild", default=False, options={"SKIP_SAVE"},
                                    description="Delete the existing cache and convert from scratch")
    full_quality: bpy.props.BoolProperty(
        name="Full Quality", default=False, options={"SKIP_SAVE"},
        description="Add view-dependent colour to the cache (keeps the existing frames, adds the rest)")

    @classmethod
    def poll(cls, context):
        obj = active_sequence(context)
        return obj is not None and jobs.get(obj.b4d.job_id) is None and bool(obj.b4d.source)

    def invoke(self, context, event):
        if self.rebuild:
            return context.window_manager.invoke_confirm(
                self, event, title="Rebuild splat cache?",
                message="The converted cache for this take will be deleted and rebuilt from the source.")
        return self.execute(context)

    def execute(self, context):
        obj = active_sequence(context)
        if not os.path.exists(obj.b4d.source):
            self.report({"ERROR"}, f"Source not found: {obj.b4d.source}")
            return {"CANCELLED"}
        if self.full_quality:
            obj.b4d.full_quality = True
            obj.b4d.view_colour = True
        start_conversion(obj, rebuild=self.rebuild)
        return {"FINISHED"}


class B4D_OT_cancel(bpy.types.Operator):
    """Stop converting this take (it can be resumed later)"""
    bl_idname = "b4d.cancel"
    bl_label = "Stop Conversion"

    def execute(self, context):
        obj = active_sequence(context)
        if obj and obj.b4d.job_id:
            jobs.cancel(obj.b4d.job_id)
        return {"FINISHED"}


class B4D_OT_setup_view(bpy.types.Operator):
    """Frame the camera on the active take and apply viewing settings (frame range, backdrop, colour, rendered viewport)"""
    bl_idname = "b4d.setup_view"
    bl_label = "Set Up Viewing"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = active_sequence(context)
        return obj is not None and playback.get_cache(obj.b4d.cache_dir) is not None

    def execute(self, context):
        setup_view(context.scene, active_sequence(context))
        return {"FINISHED"}


class B4D_OT_reload(bpy.types.Operator):
    """Re-read the active take's cache from disk"""
    bl_idname = "b4d.reload"
    bl_label = "Reload"

    def execute(self, context):
        obj = active_sequence(context)
        if obj:
            playback.drop_cache(obj.b4d.cache_dir)
            playback.refresh(obj)
        return {"FINISHED"}


class B4D_OT_select(bpy.types.Operator):
    """Make this take the active object"""
    bl_idname = "b4d.select"
    bl_label = "Select Take"
    bl_options = {"REGISTER", "UNDO"}

    name: bpy.props.StringProperty()

    def execute(self, context):
        obj = bpy.data.objects.get(self.name)
        if obj is None:
            return {"CANCELLED"}
        select_only(context, obj)
        return {"FINISHED"}


class B4D_FH_import(bpy.types.FileHandler):
    bl_idname = "B4D_FH_splat_sequence"
    bl_label = "4DGS Splat Sequence"
    bl_import_operator = B4D_OT_import.bl_idname
    bl_file_extensions = ".zip;.ply"

    @classmethod
    def poll_drop(cls, context):
        return context.area is not None and context.area.type == "VIEW_3D"


def _menu_import(self, context):
    self.layout.operator(B4D_OT_import.bl_idname, text="4DGS Splat Sequence (.ply folder / .zip)")


classes = (B4D_OT_import, B4D_OT_convert, B4D_OT_cancel, B4D_OT_setup_view, B4D_OT_reload, B4D_OT_select,
           B4D_FH_import)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.TOPBAR_MT_file_import.append(_menu_import)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(_menu_import)
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
