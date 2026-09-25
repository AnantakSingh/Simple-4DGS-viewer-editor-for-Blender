"""Geometry Nodes + material that draw splats in EEVEE and Cycles.

Each splat becomes one point-cloud sphere (radius = EXTENT x its largest sigma). The
node group stores the splat centre and the rows of its inverse transform
(R * S)^-1 = S^-1 R^T per point. The material maps the camera ray into the
splat's sigma space and evaluates the Gaussian at the ray's closest approach
to the centre:

    d^2 = |p|^2 - (p . v)^2,   alpha = opacity * exp(-d^2 / 2)

Back faces are transparent so every ray counts each splat once. The result only
depends on the ray, so EEVEE (Dithered) and Cycles (exact transparency) agree.

Before that, the node group applies the per-object look controls (all keyframable
modifier inputs): opacity fade, clean-up thresholds, six-sided crop with feather
in the take's upright space, an optional crop-box object, and colour grading.
"""
import bpy

NODE_GROUP = "4DGS Splats"
MATERIAL = "4DGS Splat"
MODIFIER = "Splats"
SHADING_VERSION = 2
EXTENT = 3.0    # sigmas enclosed by each proxy sphere

# Mesh point attributes written by the playback handler.
ATTR_ROT = "splat_rot"          # QUATERNION
ATTR_SCALE = "splat_scale"      # FLOAT_VECTOR, per-axis sigma
ATTR_COLOR = "splat_color"      # FLOAT_VECTOR, linear RGB ("color" is shadowed in Cycles point clouds)
ATTR_OPACITY = "splat_opacity"  # FLOAT

# Modifier inputs: (name, socket type, default, min, max, subtype, description, hidden)
CROP_SIDES = ("Left", "Right", "Front", "Back", "Bottom", "Top")
INPUTS = [
    ("Size", "NodeSocketFloat", 1.0, 0.0, 10.0, "NONE", "Multiplier on every splat's size", False),
    ("Opacity", "NodeSocketFloat", 1.0, 0.0, 1.0, "FACTOR", "Fade the whole take (keyframe for fades)", False),
    ("Min Opacity", "NodeSocketFloat", 0.0, 0.0, 1.0, "FACTOR", "Remove splats fainter than this", False),
    ("Max Splat Radius", "NodeSocketFloat", 0.0, 0.0, 1.0, "DISTANCE",
     "Remove splats larger than this, e.g. blurry floaters (0 = off)", False),
] + [
    (f"Crop {side}", "NodeSocketFloat", 0.0, 0.0, 1.0, "FACTOR",
     f"Cut away this share of the take from the {side.lower()}", False) for side in CROP_SIDES
] + [
    ("Crop Feather", "NodeSocketFloat", 0.0, 0.0, 1.0, "DISTANCE",
     "Fade splats out over this distance inside the crop edges instead of cutting hard", False),
    ("Use Crop Box", "NodeSocketBool", False, None, None, None, "Keep only splats inside the Crop Box object", False),
    ("Crop Box", "NodeSocketObject", None, None, None, None, "Object whose unit cube (-1..1) is the crop volume", False),
    ("Invert Crop Box", "NodeSocketBool", False, None, None, None, "Remove the inside of the crop box instead", False),
    ("Exposure", "NodeSocketFloat", 0.0, -10.0, 10.0, "NONE", "Brightness in stops", False),
    ("Saturation", "NodeSocketFloat", 1.0, 0.0, 4.0, "FACTOR", "Colour saturation", False),
    ("Hue Shift", "NodeSocketFloat", 0.0, -0.5, 0.5, "NONE", "Rotate hues", False),
    ("Tint", "NodeSocketColor", (1.0, 1.0, 1.0, 1.0), None, None, None, "Multiply colours", False),
    ("Upright", "NodeSocketVector", (0.0, 0.0, 0.0), None, None, "EULER",
     "Rotation from source to upright space (set by the add-on)", True),
    ("Bounds Min", "NodeSocketVector", (0.0, 0.0, 0.0), None, None, "NONE", "Upright take bounds (set by the add-on)", True),
    ("Bounds Max", "NodeSocketVector", (1.0, 1.0, 1.0), None, None, "NONE", "Upright take bounds (set by the add-on)", True),
]
INPUT_DEFAULTS = {i[0]: i[2] for i in INPUTS}


class _Graph:
    """Tiny helper for building node trees in code."""

    def __init__(self, tree):
        self.tree, self.n = tree, tree.nodes
        self._col = {}

    def node(self, idname, col=0, **attrs):
        nd = self.n.new(idname)
        row = self._col.get(col, 0)
        nd.location = (col * 220, -row * 170)
        self._col[col] = row + 1
        for k, v in attrs.items():
            setattr(nd, k, v)
        return nd

    def link(self, a, b):
        self.tree.links.new(a, b)

    def _feed(self, sock, value):
        if hasattr(value, "is_output"):
            self.link(value, sock)
        elif value is not None:
            sock.default_value = value

    def math(self, op, a, b=None, col=0, clamp=False):
        nd = self.node("ShaderNodeMath", col, operation=op, use_clamp=clamp)
        self._feed(nd.inputs[0], a)
        if b is not None:
            self._feed(nd.inputs[1], b)
        return nd.outputs[0]

    def vmath(self, op, a, b=None, col=0, out="Vector"):
        nd = self.node("ShaderNodeVectorMath", col, operation=op)
        self._feed(nd.inputs[0], a)
        if b is not None:
            self._feed(nd.inputs["Scale"] if op == "SCALE" else nd.inputs[1], b)
        return nd.outputs[out]

    def xyz(self, vec, col=0):
        nd = self.node("ShaderNodeSeparateXYZ", col)
        self._feed(nd.inputs[0], vec)
        return nd.outputs["X"], nd.outputs["Y"], nd.outputs["Z"]

    def bool(self, op, a, b=None, col=0):
        nd = self.node("FunctionNodeBooleanMath", col, operation=op)
        self._feed(nd.inputs[0], a)
        if b is not None:
            self._feed(nd.inputs[1], b)
        return nd.outputs[0]

    def compare(self, op, a, b, col=0):
        nd = self.node("FunctionNodeCompare", col, data_type="FLOAT", operation=op)
        self._feed(nd.inputs["A"], a)
        self._feed(nd.inputs["B"], b)
        return nd.outputs["Result"]

    def named(self, data_type, name, col=0):
        nd = self.node("GeometryNodeInputNamedAttribute", col, data_type=data_type)
        nd.inputs["Name"].default_value = name
        return nd.outputs["Attribute"]

    def store(self, geo, data_type, name, value, col=0):
        nd = self.node("GeometryNodeStoreNamedAttribute", col, data_type=data_type, domain="POINT")
        nd.inputs["Name"].default_value = name
        self._feed(nd.inputs["Geometry"], geo)
        self._feed(nd.inputs["Value"], value)
        return nd.outputs["Geometry"]


def _build_interface(ng):
    ng.interface.clear()
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    for name, stype, default, lo, hi, subtype, desc, hidden in INPUTS:
        s = ng.interface.new_socket(name, in_out="INPUT", socket_type=stype)
        s.description = desc
        if default is not None:
            s.default_value = default
        if lo is not None:
            s.min_value, s.max_value = lo, hi
        if subtype and subtype != "NONE" and hasattr(s, "subtype"):
            try:
                s.subtype = subtype
            except TypeError:
                pass
        if hidden and hasattr(s, "hide_in_modifier"):
            s.hide_in_modifier = True
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")


def _build_node_group(ng, material):
    ng.nodes.clear()
    _build_interface(ng)
    g = _Graph(ng)
    gi = g.node("NodeGroupInput", -2)
    i = gi.outputs

    # --- per-splat values -------------------------------------------------------------
    pos = g.node("GeometryNodeInputPosition", 0).outputs["Position"]
    rot = g.named("QUATERNION", ATTR_ROT, 0)
    sigma = g.vmath("SCALE", g.named("FLOAT_VECTOR", ATTR_SCALE, 0), i["Size"], 1)
    sx, sy, sz = g.xyz(sigma, 2)
    radius = g.math("MULTIPLY", g.math("MAXIMUM", g.math("MAXIMUM", sx, sy, 3), sz, 4), EXTENT, 5)

    # --- six-sided crop in upright take space, with feather -----------------------------
    upright = g.node("FunctionNodeEulerToRotation", 1)
    g.link(i["Upright"], upright.inputs[0])
    rv = g.node("FunctionNodeRotateVector", 2)
    g.link(pos, rv.inputs["Vector"]); g.link(upright.outputs[0], rv.inputs["Rotation"])
    size = g.vmath("SUBTRACT", i["Bounds Max"], i["Bounds Min"], 2)
    rel = g.vmath("SUBTRACT", rv.outputs["Vector"], i["Bounds Min"], 3)       # metres from min corner
    rx, ry, rz = g.xyz(rel, 4)
    bx, by, bz = g.xyz(size, 4)
    dists = []
    for (lo_name, hi_name), r, b in ((("Crop Left", "Crop Right"), rx, bx),
                                     (("Crop Front", "Crop Back"), ry, by),
                                     (("Crop Bottom", "Crop Top"), rz, bz)):
        # inside distance to the low plane: r - lo*b ; to the high plane: (1 - hi)*b - r
        dists.append(g.math("SUBTRACT", r, g.math("MULTIPLY", i[lo_name], b, 5), 6))
        keep_hi = g.math("MULTIPLY", g.math("SUBTRACT", 1.0, i[hi_name], 5), b, 6)
        dists.append(g.math("SUBTRACT", keep_hi, r, 7))
    d = dists[0]
    for other in dists[1:]:
        d = g.math("MINIMUM", d, other, 8)
    cropped = g.compare("LESS_THAN", d, 0.0, 9)
    feather = g.math("DIVIDE", d, g.math("MAXIMUM", i["Crop Feather"], 1e-5, 8), 9, clamp=True)

    # --- crop box object ------------------------------------------------------------------
    info = g.node("GeometryNodeObjectInfo", 1, transform_space="RELATIVE")
    g.link(i["Crop Box"], info.inputs["Object"])
    inv = g.node("FunctionNodeInvertMatrix", 2)
    g.link(info.outputs["Transform"], inv.inputs[0])
    tp = g.node("FunctionNodeTransformPoint", 3)
    g.link(pos, tp.inputs["Vector"]); g.link(inv.outputs[0], tp.inputs["Transform"])
    ax, ay, az = g.xyz(g.vmath("ABSOLUTE", tp.outputs["Vector"], col=4), 5)
    inside = g.compare("LESS_EQUAL", g.math("MAXIMUM", g.math("MAXIMUM", ax, ay, 6), az, 7), 1.0, 8)
    box_cut = g.bool("AND", i["Use Crop Box"], g.bool("XNOR", inside, i["Invert Crop Box"], 9), 10)

    # --- opacity and clean-up -------------------------------------------------------------
    opacity = g.math("MULTIPLY", g.math("MULTIPLY", g.named("FLOAT", ATTR_OPACITY, 8), i["Opacity"], 9), feather, 10)
    faint = g.compare("LESS_THAN", opacity, g.math("MAXIMUM", i["Min Opacity"], 1e-4, 10), 11)
    use_max = g.compare("GREATER_THAN", i["Max Splat Radius"], 0.0, 9)
    too_big = g.bool("AND", use_max, g.compare("GREATER_THAN", radius, i["Max Splat Radius"], 10), 11)
    remove = g.bool("OR", g.bool("OR", cropped, box_cut, 11), g.bool("OR", faint, too_big, 12), 13)

    # --- colour grading (HSV, then tint and exposure) -------------------------------------
    sep = g.node("FunctionNodeSeparateColor", 8, mode="HSV")
    g.link(g.named("FLOAT_VECTOR", ATTR_COLOR, 7), sep.inputs["Color"])
    comb = g.node("FunctionNodeCombineColor", 10, mode="HSV")
    g.link(g.math("FRACT", g.math("ADD", sep.outputs[0], i["Hue Shift"], 9), col=10), comb.inputs[0])
    g.link(g.math("MULTIPLY", sep.outputs[1], i["Saturation"], 9), comb.inputs[1])
    g.link(sep.outputs[2], comb.inputs[2])
    tinted = g.vmath("MULTIPLY", comb.outputs["Color"], i["Tint"], 11)
    color = g.vmath("SCALE", tinted, g.math("POWER", 2.0, i["Exposure"], 11), 12)

    # --- per-point data the material needs ------------------------------------------------
    geo = g.store(i["Geometry"], "FLOAT", ATTR_OPACITY, opacity, 13)
    geo = g.store(geo, "FLOAT_VECTOR", ATTR_COLOR, color, 14)
    for k, axis in enumerate("XYZ"):
        rvec = g.node("FunctionNodeRotateVector", 11)
        rvec.inputs["Vector"].default_value = tuple(float(j == k) for j in range(3))
        g.link(rot, rvec.inputs["Rotation"])
        row = g.vmath("SCALE", rvec.outputs["Vector"], g.math("DIVIDE", 1.0, (sx, sy, sz)[k], 12), 13)
        geo = g.store(geo, "FLOAT_VECTOR", "splat_a" + axis.lower(), row, 15 + k)
    geo = g.store(geo, "FLOAT_VECTOR", "splat_center", pos, 18)

    cull = g.node("GeometryNodeDeleteGeometry", 19, domain="POINT")
    g.link(geo, cull.inputs["Geometry"]); g.link(remove, cull.inputs["Selection"])
    m2p = g.node("GeometryNodeMeshToPoints", 20)
    g.link(cull.outputs["Geometry"], m2p.inputs["Mesh"]); g.link(radius, m2p.inputs["Radius"])
    out = m2p.outputs["Points"]
    for k, name in enumerate((ATTR_ROT, ATTR_SCALE)):
        rm = g.node("GeometryNodeRemoveAttribute", 21 + k)
        rm.inputs["Name"].default_value = name
        g.link(out, rm.inputs["Geometry"])
        out = rm.outputs["Geometry"]
    setmat = g.node("GeometryNodeSetMaterial", 23)
    setmat.inputs["Material"].default_value = material
    g.link(out, setmat.inputs["Geometry"])
    go = g.node("NodeGroupOutput", 24)
    g.link(setmat.outputs["Geometry"], go.inputs["Geometry"])


def _link(tree, a, b):
    tree.links.new(a, b)


def _build_material(mat):
    nt = mat.node_tree
    nt.nodes.clear()
    n = nt.nodes

    def math(op, loc, a=None, b=None):
        m = n.new("ShaderNodeMath"); m.operation = op; m.location = loc
        if a is not None:
            m.inputs[0].default_value = a
        if b is not None:
            m.inputs[1].default_value = b
        return m

    def vmath(op, loc):
        m = n.new("ShaderNodeVectorMath"); m.operation = op; m.location = loc
        return m

    def attr(name, loc):
        a = n.new("ShaderNodeAttribute"); a.location = loc
        a.attribute_type = "GEOMETRY"; a.attribute_name = name
        return a

    def to_sigma_space(vec, loc):
        comb = n.new("ShaderNodeCombineXYZ"); comb.location = (loc[0] + 400, loc[1])
        for i, axis in enumerate("xyz"):
            row = attr("splat_a" + axis, (loc[0], loc[1] - 170 * i))
            d = vmath("DOT_PRODUCT", (loc[0] + 200, loc[1] - 170 * i))
            _link(nt, row.outputs["Vector"], d.inputs[0]); _link(nt, vec, d.inputs[1])
            _link(nt, d.outputs["Value"], comb.inputs[i])
        return comb.outputs["Vector"]

    geo = n.new("ShaderNodeNewGeometry"); geo.location = (-2800, -150)
    view_obj = n.new("ShaderNodeVectorTransform"); view_obj.location = (-2600, -150)
    view_obj.vector_type = "VECTOR"; view_obj.convert_from = "WORLD"; view_obj.convert_to = "OBJECT"
    _link(nt, geo.outputs["Incoming"], view_obj.inputs["Vector"])
    hit_obj = n.new("ShaderNodeVectorTransform"); hit_obj.location = (-2600, 300)
    hit_obj.vector_type = "POINT"; hit_obj.convert_from = "WORLD"; hit_obj.convert_to = "OBJECT"
    _link(nt, geo.outputs["Position"], hit_obj.inputs["Vector"])
    rel = vmath("SUBTRACT", (-2400, 300))
    _link(nt, hit_obj.outputs["Vector"], rel.inputs[0])
    _link(nt, attr("splat_center", (-2600, 450)).outputs["Vector"], rel.inputs[1])
    local = to_sigma_space(rel.outputs["Vector"], (-2200, 300))
    view = to_sigma_space(view_obj.outputs["Vector"], (-2200, -400))

    vnorm = vmath("NORMALIZE", (-1400, -150))
    _link(nt, view, vnorm.inputs[0])
    pp = vmath("DOT_PRODUCT", (-1200, 150))
    _link(nt, local, pp.inputs[0]); _link(nt, local, pp.inputs[1])
    pv = vmath("DOT_PRODUCT", (-1200, -50))
    _link(nt, local, pv.inputs[0]); _link(nt, vnorm.outputs["Vector"], pv.inputs[1])
    pv2 = math("POWER", (-1000, -50), b=2.0)
    _link(nt, pv.outputs["Value"], pv2.inputs[0])
    d2 = math("SUBTRACT", (-800, 100))
    _link(nt, pp.outputs["Value"], d2.inputs[0]); _link(nt, pv2.outputs["Value"], d2.inputs[1])
    half = math("MULTIPLY", (-600, 100), b=-0.5)
    _link(nt, d2.outputs["Value"], half.inputs[0])
    gauss = math("EXPONENT", (-400, 100))
    _link(nt, half.outputs["Value"], gauss.inputs[0])

    opa = attr(ATTR_OPACITY, (-400, -150))
    alpha = math("MULTIPLY", (-200, 0))
    _link(nt, gauss.outputs["Value"], alpha.inputs[0]); _link(nt, opa.outputs["Fac"], alpha.inputs[1])
    keep = math("GREATER_THAN", (0, -150), b=1.0 / 255.0)   # drop invisible tails like 3DGS does
    _link(nt, alpha.outputs["Value"], keep.inputs[0])
    front = math("SUBTRACT", (0, -300), a=1.0)
    _link(nt, geo.outputs["Backfacing"], front.inputs[1])
    a1 = math("MULTIPLY", (200, 0))
    _link(nt, alpha.outputs["Value"], a1.inputs[0]); _link(nt, keep.outputs["Value"], a1.inputs[1])
    a2 = math("MULTIPLY", (400, 0))
    _link(nt, a1.outputs["Value"], a2.inputs[0]); _link(nt, front.outputs["Value"], a2.inputs[1])
    a2.use_clamp = True
    a2.label = "Alpha"

    emit = n.new("ShaderNodeEmission"); emit.location = (400, 300)
    emit.inputs["Strength"].default_value = 1.0
    _link(nt, attr(ATTR_COLOR, (200, 300)).outputs["Vector"], emit.inputs["Color"])
    transp = n.new("ShaderNodeBsdfTransparent"); transp.location = (400, 450)
    mix = n.new("ShaderNodeMixShader"); mix.location = (650, 200)
    _link(nt, a2.outputs["Value"], mix.inputs["Fac"])
    _link(nt, transp.outputs["BSDF"], mix.inputs[1])
    _link(nt, emit.outputs["Emission"], mix.inputs[2])
    out = n.new("ShaderNodeOutputMaterial"); out.location = (850, 200)
    _link(nt, mix.outputs["Shader"], out.inputs["Surface"])

    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = "DITHERED"
    mat.use_backface_culling = True
    if hasattr(mat, "use_backface_culling_shadow"):
        mat.use_backface_culling_shadow = True




def ensure(force=False):
    """Return the shared splat node group, (re)building it and the material if needed."""
    mat = bpy.data.materials.get(MATERIAL)
    ng = bpy.data.node_groups.get(NODE_GROUP)
    current = ng is not None and mat is not None and ng.get("b4d_version") == SHADING_VERSION
    if current and not force:
        return ng
    if mat is None:
        mat = bpy.data.materials.new(MATERIAL)
    if getattr(mat, "node_tree", None) is None:
        mat.use_nodes = True
    _build_material(mat)
    if ng is None:
        ng = bpy.data.node_groups.new(NODE_GROUP, "GeometryNodeTree")
    _build_node_group(ng, mat)
    ng["b4d_version"] = SHADING_VERSION
    return ng


def ensure_modifier(obj):
    mod = obj.modifiers.get(MODIFIER)
    if mod is None or mod.type != "NODES":
        mod = obj.modifiers.new(MODIFIER, "NODES")
    mod.node_group = ensure()
    return mod


def _identifier(mod, name):
    if mod is None or mod.node_group is None:
        return None
    for item in mod.node_group.interface.items_tree:
        if getattr(item, "in_out", None) == "INPUT" and item.name == name:
            return item.identifier
    return None


def modifier_input(mod, name):
    """(data, property path) for a modifier input, for layout.prop(); works on Blender 4.2-5.x."""
    ident = _identifier(mod, name)
    if ident is None:
        return None
    props = getattr(mod, "properties", None)
    if props is not None and hasattr(props, "inputs"):          # Blender 5.x
        sock = getattr(props.inputs, ident, None)
        return (sock, "value") if sock is not None else None
    return (mod, f'["{ident}"]')                               # Blender 4.x


def get_input(mod, name):
    ref = modifier_input(mod, name)
    if ref is None:
        return None
    data, path = ref
    return data.path_resolve(path) if path.startswith("[") else getattr(data, path)


def set_input(mod, name, value):
    ref = modifier_input(mod, name)
    if ref is None:
        return False
    data, path = ref
    if path.startswith("["):
        data[path[2:-2]] = value
    else:
        setattr(data, path, value)
    return True
