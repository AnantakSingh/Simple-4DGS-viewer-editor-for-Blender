import bpy

from . import editing, jobs, operators, playback, shading


def _ready(context):
    obj = operators.active_sequence(context)
    return obj if obj and not obj.b4d.job_id and playback.get_cache(obj.b4d.cache_dir) else None


_SHORT = {"Max Splat Radius": "Max Radius", "Use Crop Box": "Use Box", "Invert Crop Box": "Invert"}


def _colour_quality(layout, obj):
    """View-dependent colour toggle, or the upgrade offer for compact caches."""
    cache = playback.get_cache(obj.b4d.cache_dir)
    if cache is not None and cache.sh_degree > 0:
        layout.prop(obj.b4d, "view_colour")
        return
    box = layout.box()
    col = box.column(align=True)
    col.scale_y = 0.8
    col.label(text="Compact cache: view-dependent", icon="INFO")
    col.label(text="colour isn't stored (flatter shading).", icon="BLANK1")
    op = box.operator(operators.B4D_OT_convert.bl_idname, text="Upgrade to Full Quality", icon="SHADING_RENDERED")
    op.full_quality = True


def _inputs(layout, obj, names):
    mod = obj.modifiers.get(shading.MODIFIER)
    for name in names:
        ref = shading.modifier_input(mod, name)
        if ref is not None:
            layout.prop(*ref, text=_SHORT.get(name, name.replace("Crop ", "")))


class _Sub:
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Splats"
    bl_parent_id = "B4D_PT_take"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return _ready(context) is not None


class B4D_PT_main(bpy.types.Panel):
    bl_label = "Splat Viewer"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Splats"

    def draw(self, context):
        layout = self.layout
        layout.operator(operators.B4D_OT_import.bl_idname, text="Import Take…", icon="IMPORT")
        seqs = playback.sequence_objects(context.scene)
        if not seqs:
            col = layout.column(align=True)
            col.scale_y = 0.8
            col.label(text="Pick a take folder, one of its .ply")
            col.label(text="files, or the .zip. You can also drag")
            col.label(text="a .zip or .ply into the viewport.")
            return
        layout.prop(context.scene, "b4d_speed")      # scene-wide; the frame rate is untouched
        col = layout.column(align=True)
        active = context.active_object
        for obj in seqs:
            row = col.row(align=True)
            icon = "TIME" if obj.b4d.job_id else ("ERROR" if obj.b4d.last_error else "OUTLINER_OB_POINTCLOUD")
            op = row.operator(operators.B4D_OT_select.bl_idname, text=obj.name, icon=icon, depress=(obj == active))
            op.name = obj.name
            row.prop(obj.b4d, "enabled", text="", icon="HIDE_OFF" if obj.b4d.enabled else "HIDE_ON", emboss=False)


class B4D_PT_take(bpy.types.Panel):
    bl_label = "Take"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Splats"
    bl_parent_id = "B4D_PT_main"

    @classmethod
    def poll(cls, context):
        return operators.active_sequence(context) is not None

    def draw_header(self, context):
        self.layout.label(text=context.active_object.name)

    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        s = obj.b4d

        job = jobs.get(s.job_id) if s.job_id else None
        if job is not None:
            text = f"Converting {job.done}/{job.total} frames" if job.total else "Starting conversion…"
            layout.progress(factor=job.progress, type="BAR", text=text)
            layout.operator(operators.B4D_OT_cancel.bl_idname, icon="CANCEL")
            return
        if s.last_error:
            box = layout.box()
            box.alert = True
            for i, line in enumerate(s.last_error.split("\n")[:4]):
                box.label(text=line, icon="ERROR" if i == 0 else "BLANK1")
            box.operator(operators.B4D_OT_convert.bl_idname, text="Convert", icon="FILE_REFRESH")
            return
        if playback.get_cache(s.cache_dir) is None:
            box = layout.box()
            box.label(text="No converted cache for this take.", icon="INFO")
            box.operator(operators.B4D_OT_convert.bl_idname, text="Convert", icon="FILE_REFRESH")
            box.prop(s, "cache_dir", text="")
            return

        info = playback.status(obj)
        if info:
            layout.label(text=info, icon="INFO")
        col = layout.column()
        col.use_property_split = True
        col.use_property_decorate = False
        col.prop(s, "up_axis")
        row = layout.row(align=True)
        row.operator(operators.B4D_OT_setup_view.bl_idname, icon="CAMERA_DATA")
        row.operator(operators.B4D_OT_reload.bl_idname, text="", icon="FILE_REFRESH")


class B4D_PT_timing(_Sub, bpy.types.Panel):
    bl_label = "Timing"
    bl_options = set()

    def draw(self, context):
        layout = self.layout
        obj = _ready(context)
        s = obj.b4d
        n = len(playback.get_cache(s.cache_dir).counts)

        row = layout.row(align=True)
        row.operator(editing.B4D_OT_trim_to_playhead.bl_idname, text="Trim Start", icon="TRIA_LEFT_BAR").side = "START"
        row.operator(editing.B4D_OT_split.bl_idname, text="Split", icon="SCULPTMODE_HLT")
        row.operator(editing.B4D_OT_trim_to_playhead.bl_idname, text="Trim End", icon="TRIA_RIGHT_BAR").side = "END"
        row = layout.row(align=True)
        row.operator(editing.B4D_OT_cut.bl_idname, icon="X")
        row.operator(editing.B4D_OT_fit_timeline.bl_idname, icon="ARROW_LEFTRIGHT")

        col = layout.column()
        col.use_property_split = True
        col.use_property_decorate = False
        sub = col.column(align=True)
        sub.prop(s, "start_frame")
        sub.prop(s, "trim_in")
        sub.prop(s, "trim_out", text="Trim End")
        sub.label(text=f"Take has {n} frames (Trim End 0 = last)")
        sub = col.column(align=True)
        sub.active = not (s.freeze or s.use_time_remap)
        speed_row = sub.row(align=True)
        speed_row.use_property_decorate = True          # keyframe button: animate for speed ramps
        speed_row.prop(s, "speed")
        master = context.scene.b4d_speed
        if abs(master - 1.0) > 1e-6:
            sub.label(text=f"× scene Playback Speed {master:.2f}", icon="INFO")
        sub.prop(s, "reverse")
        sub.prop(s, "out_of_range")

        col.separator()
        row = col.row(heading="Freeze")
        row.prop(s, "freeze", text="")
        sub = row.row()
        sub.active = s.freeze
        sub.prop(s, "freeze_frame", text="Take Frame")

        row = col.row(heading="Time Remap")
        row.prop(s, "use_time_remap", text="")
        sub = row.row(align=True)
        sub.active = s.use_time_remap
        sub.use_property_decorate = True
        sub.prop(s, "remap_frame", text="")
        layout.operator(editing.B4D_OT_remap_key.bl_idname, icon="KEY_HLT")
        layout.operator(editing.B4D_OT_reset_timing.bl_idname, icon="LOOP_BACK")


class B4D_PT_crop(_Sub, bpy.types.Panel):
    bl_label = "Crop"

    def draw(self, context):
        layout = self.layout
        obj = _ready(context)
        col = layout.column()
        col.use_property_split = True
        grid = col.column(align=True)
        _inputs(grid, obj, [f"Crop {side}" for side in shading.CROP_SIDES])
        _inputs(col, obj, ["Crop Feather"])

        mod = obj.modifiers.get(shading.MODIFIER)
        box = layout.box()
        if shading.get_input(mod, "Crop Box") is None:
            box.operator(editing.B4D_OT_add_crop_box.bl_idname, icon="CUBE")
        else:
            bcol = box.column()
            bcol.use_property_split = True
            _inputs(bcol, obj, ["Use Crop Box", "Crop Box", "Invert Crop Box"])
            box.operator(editing.B4D_OT_remove_crop_box.bl_idname, icon="X")
        layout.operator(editing.B4D_OT_reset_look.bl_idname, text="Reset Crop", icon="LOOP_BACK").group = "CROP"


class B4D_PT_look(_Sub, bpy.types.Panel):
    bl_label = "Look"

    def draw(self, context):
        layout = self.layout
        obj = _ready(context)
        s = obj.b4d
        col = layout.column()
        col.use_property_split = True
        _colour_quality(col, obj)
        _inputs(col, obj, ["Size", "Opacity", "Min Opacity", "Max Splat Radius"])
        sub = col.column()
        sub.use_property_decorate = False
        sub.prop(s, "density", slider=True)
        sub.prop(s, "playback_detail", slider=True)
        col.separator()
        _inputs(col, obj, ["Exposure", "Saturation", "Hue Shift", "Tint"])
        row = layout.row(align=True)
        row.operator(editing.B4D_OT_reset_look.bl_idname, text="Reset Clean-up").group = "CLEANUP"
        row.operator(editing.B4D_OT_reset_look.bl_idname, text="Reset Colour").group = "COLOR"


class B4D_PT_echoes(_Sub, bpy.types.Panel):
    bl_label = "Echoes"

    def draw_header(self, context):
        obj = _ready(context)
        self.layout.label(text="", icon="ONIONSKIN_ON" if obj and obj.b4d.echoes else "ONIONSKIN_OFF")

    def draw(self, context):
        layout = self.layout
        s = _ready(context).b4d
        col = layout.column()
        col.use_property_split = True
        col.use_property_decorate = False
        col.prop(s, "echoes")
        sub = col.column()
        sub.active = s.echoes > 0
        sub.prop(s, "echo_spacing")
        sub.prop(s, "echo_fade", slider=True)
        sub.prop(s, "echo_density", slider=True)


class B4D_PT_files(_Sub, bpy.types.Panel):
    bl_label = "Files"

    @classmethod
    def poll(cls, context):
        return operators.active_sequence(context) is not None

    def draw(self, context):
        layout = self.layout
        s = context.active_object.b4d
        col = layout.column()
        col.prop(s, "source", text="Source")
        col.prop(s, "cache_dir", text="Cache")
        cache = playback.get_cache(s.cache_dir)
        if cache is not None:
            kind = (f"Full quality (view-dependent colour, SH degree {cache.sh_degree})"
                    if cache.sh_degree else "Compact (base colour only)")
            col.label(text=kind, icon="CHECKMARK" if cache.sh_degree else "INFO")
        op = col.operator(operators.B4D_OT_convert.bl_idname, text="Rebuild Cache", icon="TRASH")
        op.rebuild = True


classes = (B4D_PT_main, B4D_PT_take, B4D_PT_timing, B4D_PT_crop, B4D_PT_look, B4D_PT_echoes, B4D_PT_files)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
