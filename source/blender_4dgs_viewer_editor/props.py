import os

import bpy


def _refresh(self, context):
    from . import playback
    playback.refresh(self.id_data)


def _cache_changed(self, context):
    from . import playback
    playback.drop_cache(self.cache_dir)
    _refresh(self, context)


def _scene_speed_changed(self, context):
    from . import playback
    playback.refresh_scene(self)


def _up_axis_changed(self, context):
    from . import operators
    operators.apply_up_axis(self.id_data)


class B4D_SequenceSettings(bpy.types.PropertyGroup):
    """Per-object settings for a splat take (stored on the object)."""
    is_sequence: bpy.props.BoolProperty(default=False, options={"HIDDEN"})
    enabled: bpy.props.BoolProperty(
        name="Show Splats", default=True, update=_refresh,
        description="Load splats for this take as the timeline moves")
    take: bpy.props.StringProperty(name="Take")
    source: bpy.props.StringProperty(name="Source", description="Folder or .zip the take was imported from")
    cache_dir: bpy.props.StringProperty(
        name="Cache", subtype="DIR_PATH", update=_cache_changed,
        description="Converted splat cache for this take (folder containing meta.json)")
    up_axis: bpy.props.EnumProperty(
        name="Up Axis",
        items=[("NEG_Y", "-Y (Y-down)", "Source is Y-down and faces +Z (most 3DGS / 4DGS exports)"),
               ("POS_Y", "+Y", "Source is Y-up and faces +Z"),
               ("POS_Z", "+Z", "Source is Z-up and faces -Y")],
        default="NEG_Y", update=_up_axis_changed,
        description="Which way is up in the source data. Changing it resets the object's rotation")

    # ---- timing (all frame numbers are 1-based take frames) -------------------------
    start_frame: bpy.props.IntProperty(
        name="Start Frame", default=1, update=_refresh,
        description="Timeline frame where the (trimmed) take starts")
    trim_in: bpy.props.IntProperty(
        name="Trim Start", default=1, min=1, update=_refresh,
        description="First take frame to use")
    trim_out: bpy.props.IntProperty(
        name="Trim End", default=0, min=0, update=_refresh,
        description="Last take frame to use (0 = last frame of the take)")
    speed: bpy.props.FloatProperty(
        name="Speed", default=1.0, min=0.0, max=20.0, soft_min=0.05, soft_max=4.0, update=_refresh,
        description="This take's playback speed (0.5 = half speed, 2 = double speed). "
                    "Doesn't change the scene frame rate. Keyframe it for smooth speed ramps")
    reverse: bpy.props.BoolProperty(name="Reverse", default=False, update=_refresh,
                                    description="Play the take backwards")
    out_of_range: bpy.props.EnumProperty(
        name="Outside Take",
        items=[("HOLD", "Hold", "Show the first/last frame"),
               ("LOOP", "Loop", "Repeat the take"),
               ("PING_PONG", "Ping-Pong", "Play forwards then backwards, repeatedly"),
               ("HIDE", "Hide", "Show nothing")],
        default="HOLD", update=_refresh,
        description="What to show before and after the take on the timeline")
    freeze: bpy.props.BoolProperty(name="Freeze Frame", default=False, update=_refresh,
                                   description="Show a single take frame for the whole timeline")
    freeze_frame: bpy.props.IntProperty(name="Frame", default=1, min=1, update=_refresh,
                                        description="Take frame to show while frozen")
    use_time_remap: bpy.props.BoolProperty(
        name="Time Remap", default=False, update=_refresh,
        description="Choose the take frame with the keyframable Take Frame value "
                    "(overrides start, speed, reverse and looping)")
    remap_frame: bpy.props.FloatProperty(
        name="Take Frame", default=1.0, min=1.0, update=_refresh,
        description="Take frame shown when Time Remap is on. Keyframe it for slow motion, holds and reversals")

    # ---- colour quality ------------------------------------------------------------
    full_quality: bpy.props.BoolProperty(
        name="Full-Quality Colour", default=False,
        description="Convert with view-dependent colour (spherical harmonics). "
                    "Looks like the original capture; the cache is about 4x larger")
    view_colour: bpy.props.BoolProperty(
        name="View-Dependent Colour", default=True, update=_refresh,
        description="Colour each splat as seen from the camera / viewport, like the original capture. "
                    "Needs a full-quality cache")

    # ---- detail --------------------------------------------------------------------
    density: bpy.props.FloatProperty(
        name="Density", default=1.0, min=0.02, max=1.0, subtype="FACTOR", update=_refresh,
        description="Share of splats drawn, most important first (viewport and render)")
    playback_detail: bpy.props.FloatProperty(
        name="Playback Detail", default=1.0, min=0.02, max=1.0, subtype="FACTOR", update=_refresh,
        description="Extra reduction while the timeline plays. Paused frames and renders use Density only")

    # ---- echoes ----------------------------------------------------------------------
    echoes: bpy.props.IntProperty(
        name="Echoes", default=0, min=0, max=8, update=_refresh,
        description="Draw this many earlier frames behind the current one (onion-skin trail)")
    echo_spacing: bpy.props.IntProperty(
        name="Spacing", default=3, min=1, max=120, update=_refresh,
        description="Timeline frames between echoes")
    echo_fade: bpy.props.FloatProperty(
        name="Fade", default=0.5, min=0.0, max=1.0, subtype="FACTOR", update=_refresh,
        description="Opacity of each echo relative to the one before it")
    echo_density: bpy.props.FloatProperty(
        name="Echo Density", default=0.5, min=0.02, max=1.0, subtype="FACTOR", update=_refresh,
        description="Share of splats drawn for each echo")

    job_id: bpy.props.StringProperty(options={"HIDDEN"})
    last_error: bpy.props.StringProperty(options={"HIDDEN"})


class B4D_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    cache_location: bpy.props.EnumProperty(
        name="Cache Location",
        items=[("SOURCE", "Next to the Take", "Write '<take>.splatcache' beside the take folder or .zip"),
               ("FOLDER", "Cache Folder", "Write all caches into one folder")],
        default="SOURCE")
    cache_folder: bpy.props.StringProperty(name="Cache Folder", subtype="DIR_PATH")
    workers: bpy.props.IntProperty(
        name="Converter Processes", default=0, min=0, max=64,
        description="Parallel processes used to convert takes (0 = automatic)")

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.prop(self, "cache_location")
        if self.cache_location == "FOLDER":
            layout.prop(self, "cache_folder")
        layout.prop(self, "workers")


def prefs(context=None):
    context = context or bpy.context
    addon = context.preferences.addons.get(__package__)
    return addon.preferences if addon else None


def cache_dir_for(source, context=None):
    """Where the cache for `source` (convert.Source) should live."""
    p = prefs(context)
    if p and p.cache_location == "FOLDER" and p.cache_folder:
        base = bpy.path.abspath(p.cache_folder)
        return os.path.join(base, f"{source.take}-{source.signature[:8]}.splatcache")
    parent = os.path.dirname(source.root.rstrip("\\/"))
    if os.access(parent, os.W_OK):
        return os.path.join(parent, source.take + ".splatcache")
    # Read-only source location: fall back to the extension's user folder.
    base = bpy.utils.extension_path_user(__package__, path="caches", create=True)
    return os.path.join(base, f"{source.take}-{source.signature[:8]}.splatcache")


classes = (B4D_SequenceSettings, B4D_Preferences)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Object.b4d = bpy.props.PointerProperty(type=B4D_SequenceSettings)
    bpy.types.Scene.b4d_speed = bpy.props.FloatProperty(
        name="Playback Speed", default=1.0, min=0.0, max=20.0, soft_min=0.05, soft_max=4.0,
        update=_scene_speed_changed,
        description="Speed of every take in the scene (multiplies each take's own Speed). "
                    "Doesn't change the scene frame rate, and applies to renders too. Keyframe it for speed ramps")


def unregister():
    del bpy.types.Scene.b4d_speed
    del bpy.types.Object.b4d
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
