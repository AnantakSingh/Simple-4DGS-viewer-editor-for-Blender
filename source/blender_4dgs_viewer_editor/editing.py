"""Editing operators: trim, split, cut, timing reset, time-remap keys, crop box, look reset."""
import bpy
from mathutils import Vector

from . import operators, playback, shading, timing

LOOK_GROUPS = {
    "CROP": [f"Crop {s}" for s in shading.CROP_SIDES] + ["Crop Feather", "Use Crop Box", "Invert Crop Box"],
    "CLEANUP": ["Size", "Opacity", "Min Opacity", "Max Splat Radius"],
    "COLOR": ["Exposure", "Saturation", "Hue Shift", "Tint"],
}


def _ready_sequence(context):
    obj = operators.active_sequence(context)
    if obj is None or obj.b4d.job_id:
        return None, None
    cache = playback.get_cache(obj.b4d.cache_dir)
    return (obj, len(cache.counts)) if cache else (None, None)


def _clock(context, obj):
    return timing.clock_for(obj, context.scene)


def _playhead(context, obj, n):
    """(0-based take index, trimmed local position) under the playhead, or (None, None)."""
    s = obj.b4d
    clock = _clock(context, obj)
    local = timing.local_at(s, context.scene.frame_current, clock)
    if not 0 <= local < timing.trimmed_length(s, n):
        return None, None
    return timing.take_index(s, context.scene.frame_current, n, clock=clock), local


def _duplicate(obj):
    dup = obj.copy()
    dup.data = obj.data.copy()
    for coll in obj.users_collection:
        coll.objects.link(dup)
    return dup


def _refresh_all(context, *objs):
    for o in objs:
        playback.refresh(o)
    context.area.tag_redraw() if context.area else None


class _SequenceOp:
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return _ready_sequence(context)[0] is not None


class _TimingOp(_SequenceOp):
    @classmethod
    def poll(cls, context):
        obj, _n = _ready_sequence(context)
        return obj is not None and not obj.b4d.freeze and not obj.b4d.use_time_remap


# --------------------------------------------------------------------------- timing edits

class B4D_OT_trim_to_playhead(_TimingOp, bpy.types.Operator):
    """Trim the take so it starts or ends at the playhead, keeping the rest in place on the timeline"""
    bl_idname = "b4d.trim_to_playhead"
    bl_label = "Trim to Playhead"

    side: bpy.props.EnumProperty(items=[("START", "Start", "Remove everything before the playhead"),
                                        ("END", "End", "Remove everything after the playhead")])

    def execute(self, context):
        obj, n = _ready_sequence(context)
        s = obj.b4d
        idx, local = _playhead(context, obj, n)
        if idx is None:
            self.report({"ERROR"}, "Move the playhead onto the take first")
            return {"CANCELLED"}
        first_shown = timing.timeline_frame_for_local(s, local, _clock(context, obj))
        keep_low = (self.side == "START") == s.reverse     # which take frames survive
        if keep_low:
            s.trim_out = idx + 1
        else:
            s.trim_in = idx + 1
        if self.side == "START":
            s.start_frame = first_shown
        _refresh_all(context, obj)
        return {"FINISHED"}


class B4D_OT_split(_TimingOp, bpy.types.Operator):
    """Split the take at the playhead into two objects (like a blade cut in a video editor)"""
    bl_idname = "b4d.split"
    bl_label = "Split at Playhead"

    def execute(self, context):
        obj, n = _ready_sequence(context)
        s = obj.b4d
        idx, local = _playhead(context, obj, n)
        lo, hi = timing.trim_range(s, n)
        if idx is None or (idx == lo if not s.reverse else idx == hi):
            self.report({"ERROR"}, "Put the playhead inside the take (not on its first frame)")
            return {"CANCELLED"}
        first_shown = timing.timeline_frame_for_local(s, local, _clock(context, obj))
        second = _duplicate(obj)
        for o in (obj, second):
            o.b4d.out_of_range = "HIDE"
        if not s.reverse:
            s.trim_out = idx                 # 1-based: the frame before the playhead
            second.b4d.trim_in = idx + 1
        else:
            s.trim_in = idx + 2
            second.b4d.trim_out = idx + 1
        second.b4d.start_frame = first_shown
        second.name = obj.name
        operators.select_only(context, second)
        _refresh_all(context, obj, second)
        self.report({"INFO"}, f"Split at take frame {idx + 1}")
        return {"FINISHED"}


class B4D_OT_cut(_TimingOp, bpy.types.Operator):
    """Remove a range of take frames from the middle of the take"""
    bl_idname = "b4d.cut"
    bl_label = "Cut Range"

    first: bpy.props.IntProperty(name="From Take Frame", min=1, description="First take frame to remove")
    last: bpy.props.IntProperty(name="To Take Frame", min=1, description="Last take frame to remove")
    close_gap: bpy.props.BoolProperty(name="Close Gap", default=True,
                                      description="Move the rest of the take earlier so there is no pause")

    @classmethod
    def poll(cls, context):
        obj = operators.active_sequence(context)
        return super().poll(context) and not obj.b4d.reverse

    def invoke(self, context, event):
        obj, n = _ready_sequence(context)
        idx, _local = _playhead(context, obj, n)
        lo, hi = timing.trim_range(obj.b4d, n)
        self.first = (idx if idx is not None else lo) + 1
        self.last = min(self.first + 29, hi + 1)
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        obj, n = _ready_sequence(context)
        s = obj.b4d
        lo, hi = timing.trim_range(s, n)
        a, b = sorted((self.first - 1, self.last - 1))          # 0-based take indices
        a, b = max(a, lo), min(b, hi)
        if a > b or (a == lo and b == hi):
            self.report({"ERROR"}, "That range would remove the whole take")
            return {"CANCELLED"}
        clock = _clock(context, obj)
        start_after = timing.timeline_frame_for_local(s, b + 1 - lo, clock)   # where b+1 used to appear
        if a == lo:                          # cut from the front
            s.trim_in = b + 2
            if not self.close_gap:
                s.start_frame = start_after
            _refresh_all(context, obj)
            return {"FINISHED"}
        if b == hi:                          # cut from the back
            s.trim_out = a
            _refresh_all(context, obj)
            return {"FINISHED"}
        second = _duplicate(obj)
        for o in (obj, second):
            o.b4d.out_of_range = "HIDE"
        s.trim_out = a                       # keeps take frames up to a (1-based)
        second.b4d.trim_in = b + 2
        second.b4d.start_frame = (timing.timeline_span(s, n, clock)[1] + 1) if self.close_gap else start_after
        second.name = obj.name
        operators.select_only(context, second)
        _refresh_all(context, obj, second)
        self.report({"INFO"}, f"Removed take frames {a + 1}-{b + 1}")
        return {"FINISHED"}


class B4D_OT_reset_timing(_SequenceOp, bpy.types.Operator):
    """Undo all trims, speed, reverse, freeze and time remap on this take"""
    bl_idname = "b4d.reset_timing"
    bl_label = "Reset Timing"

    def execute(self, context):
        obj, n = _ready_sequence(context)
        s = obj.b4d
        # Keep the footage where it was on the timeline: move the start back by the trimmed-off head.
        if not s.reverse:
            s.start_frame = timing.timeline_frame_for_local(s, -timing.trim_range(s, n)[0], _clock(context, obj))
        timing.clear_animation(obj, timing.SPEED_PATH)
        s.trim_in, s.trim_out, s.speed = 1, 0, 1.0
        s.reverse = s.freeze = s.use_time_remap = False
        s.out_of_range = "HOLD"
        _refresh_all(context, obj)
        return {"FINISHED"}


class B4D_OT_fit_timeline(_SequenceOp, bpy.types.Operator):
    """Set the scene frame range to cover every take in the scene"""
    bl_idname = "b4d.fit_timeline"
    bl_label = "Fit Timeline"

    @classmethod
    def poll(cls, context):
        return any(playback.get_cache(o.b4d.cache_dir) for o in playback.sequence_objects(context.scene))

    def execute(self, context):
        operators.fit_timeline(context.scene)
        return {"FINISHED"}


class B4D_OT_remap_key(_SequenceOp, bpy.types.Operator):
    """Key the take frame shown at the playhead. The first key switches the take to Time Remap"""
    bl_idname = "b4d.remap_key"
    bl_label = "Key Take Frame"

    def execute(self, context):
        obj, n = _ready_sequence(context)
        s = obj.b4d
        frame = context.scene.frame_current
        if not s.use_time_remap:
            idx = timing.take_index(s, frame, n, clock=_clock(context, obj))
            s.remap_frame = (idx if idx is not None else 0) + 1
            s.use_time_remap = True
        obj.keyframe_insert(data_path=timing.REMAP_PATH, frame=frame)
        _refresh_all(context, obj)
        return {"FINISHED"}


# --------------------------------------------------------------------------- crop box & look

class B4D_OT_add_crop_box(_SequenceOp, bpy.types.Operator):
    """Add a box object around the take; only splats inside it are kept. Move, rotate and scale it freely"""
    bl_idname = "b4d.add_crop_box"
    bl_label = "Add Crop Box"

    def execute(self, context):
        obj, _n = _ready_sequence(context)
        mod = obj.modifiers.get(shading.MODIFIER)
        cache = playback.get_cache(obj.b4d.cache_dir)
        lo, hi = operators.world_bounds(obj, cache.meta)
        box = bpy.data.objects.new(f"{obj.name} Crop Box", None)
        box.empty_display_type = "CUBE"
        box.empty_display_size = 1.0
        box.location = (lo + hi) / 2
        box.scale = (hi - lo) / 2 * 1.02 + Vector((0.01, 0.01, 0.01))
        for coll in obj.users_collection:
            coll.objects.link(box)
        shading.set_input(mod, "Crop Box", box)
        shading.set_input(mod, "Use Crop Box", True)
        operators.select_only(context, box)
        obj.update_tag()
        return {"FINISHED"}


class B4D_OT_remove_crop_box(_SequenceOp, bpy.types.Operator):
    """Stop using the crop box (and delete it if nothing else uses it)"""
    bl_idname = "b4d.remove_crop_box"
    bl_label = "Remove Crop Box"

    def execute(self, context):
        obj, _n = _ready_sequence(context)
        mod = obj.modifiers.get(shading.MODIFIER)
        box = shading.get_input(mod, "Crop Box")
        shading.set_input(mod, "Crop Box", None)
        shading.set_input(mod, "Use Crop Box", False)
        if box is not None:
            users = [o for o in bpy.data.objects if o.b4d.is_sequence and o is not obj
                     and shading.get_input(o.modifiers.get(shading.MODIFIER), "Crop Box") == box]
            if not users and box.type == "EMPTY":
                bpy.data.objects.remove(box)
        obj.update_tag()
        return {"FINISHED"}


class B4D_OT_reset_look(_SequenceOp, bpy.types.Operator):
    """Reset a group of look settings to their defaults"""
    bl_idname = "b4d.reset_look"
    bl_label = "Reset"

    group: bpy.props.EnumProperty(items=[("CROP", "Crop", ""), ("CLEANUP", "Clean-up", ""),
                                         ("COLOR", "Colour", ""), ("ALL", "All", "")], default="ALL")

    def execute(self, context):
        obj, _n = _ready_sequence(context)
        mod = obj.modifiers.get(shading.MODIFIER)
        groups = LOOK_GROUPS.values() if self.group == "ALL" else [LOOK_GROUPS[self.group]]
        for names in groups:
            for name in names:
                shading.set_input(mod, name, shading.INPUT_DEFAULTS[name])
        obj.update_tag()
        return {"FINISHED"}


classes = (B4D_OT_trim_to_playhead, B4D_OT_split, B4D_OT_cut, B4D_OT_reset_timing, B4D_OT_fit_timeline,
           B4D_OT_remap_key, B4D_OT_add_crop_box, B4D_OT_remove_crop_box, B4D_OT_reset_look)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
