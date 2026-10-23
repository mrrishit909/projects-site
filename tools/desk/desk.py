# Blender 4.5: Blender -b --factory-startup -P desk.py -- <tex_dir> <out_dir> <comp: wide|tall|solo> [samples]
import bpy, sys, math, os
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
TEX, OUT, COMP = argv[0], argv[1], argv[2]
SAMPLES = int(argv[3]) if len(argv) > 3 else 96
os.makedirs(OUT, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.render.engine = "CYCLES"
prefs = bpy.context.preferences.addons["cycles"].preferences
prefs.compute_device_type = "METAL"
prefs.get_devices()
for d in prefs.devices:
    d.use = True
sc.cycles.device = "GPU"
sc.cycles.samples = SAMPLES
sc.cycles.use_denoising = True
sc.view_settings.view_transform = "Standard"
sc.render.film_transparent = True
sc.render.image_settings.file_format = "PNG"
sc.render.image_settings.color_mode = "RGBA"

DESK = (0.86, 0.13, 0.045)  # tomato paper, linear-ish


def mat(name, color=None, tex=None, rough=0.6, alpha_tex=False, bump=None, bump_strength=0.4, spec=0.5):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    p = nt.nodes["Principled BSDF"]
    p.inputs["Roughness"].default_value = rough
    p.inputs["Specular IOR Level"].default_value = spec
    if color:
        p.inputs["Base Color"].default_value = (*color, 1)
    if tex:
        t = nt.nodes.new("ShaderNodeTexImage")
        t.image = bpy.data.images.load(os.path.join(TEX, tex))
        t.interpolation = "Cubic"
        t.extension = "CLIP"
        nt.links.new(t.outputs["Color"], p.inputs["Base Color"])
        if alpha_tex:
            nt.links.new(t.outputs["Alpha"], p.inputs["Alpha"])
    if bump:
        b = nt.nodes.new("ShaderNodeTexImage")
        b.image = bpy.data.images.load(os.path.join(TEX, bump))
        b.image.colorspace_settings.name = "Non-Color"
        b.interpolation = "Cubic"
        bn = nt.nodes.new("ShaderNodeBump")
        bn.inputs["Strength"].default_value = bump_strength
        bn.inputs["Distance"].default_value = 0.02
        nt.links.new(b.outputs["Color"], bn.inputs["Height"])
        nt.links.new(bn.outputs["Normal"], p.inputs["Normal"])
    return m


def grid(name, w, h, nx=40, ny=40):
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=nx, y_subdivisions=ny, size=1, calc_uvs=True)
    o = bpy.context.object
    o.name = name
    o.scale = (w, h, 1)
    bpy.ops.object.transform_apply(scale=True)
    return o


def solid(o, t):
    m = o.modifiers.new("s", "SOLIDIFY")
    m.thickness = t
    m.offset = 1


def bend(o, fn):
    for v in o.data.vertices:
        v.co.z += fn(v.co.x, v.co.y)


def group(name, parts):
    e = bpy.data.objects.new(name, None)
    sc.collection.objects.link(e)
    for p in parts:
        p.parent = e
    return e


# ---- desk
bpy.ops.mesh.primitive_plane_add(size=200)
desk = bpy.context.object
dm = mat("desk", DESK, rough=0.9, spec=0.0)
n = dm.node_tree.nodes
noise = n.new("ShaderNodeTexNoise"); noise.inputs["Scale"].default_value = 180; noise.inputs["Detail"].default_value = 8
bn = n.new("ShaderNodeBump"); bn.inputs["Strength"].default_value = 0.08
dm.node_tree.links.new(noise.outputs["Fac"], bn.inputs["Height"])
dm.node_tree.links.new(bn.outputs["Normal"], n["Principled BSDF"].inputs["Normal"])
desk.data.materials.append(dm)

# ---- artefacts (units: CSS px / 100)
objs = {}
# boarding pass: slight lift at the right end
p = grid("pass_m", 8.0, 3.2)
bend(p, lambda x, y: 0.06 * max(0, (x - 2.0) / 2.0) ** 2)
p.data.materials.append(mat("pass", tex="pass.png", rough=0.55, spec=0.35)); solid(p, 0.025)
objs["pass"] = group("pass", [p])

# receipt: thermal strip with curled ends
r = grid("rcpt_m", 3.0, 10.0, 12, 80)
bend(r, lambda x, y: 0.55 * (abs(y) / 5.0) ** 5 + 0.03 * math.sin(y * 1.3))
r.data.materials.append(mat("rcpt", tex="rcpt.png", rough=0.4, alpha_tex=True, spec=0.4)); solid(r, 0.012)
objs["rcpt"] = group("rcpt", [r])

# ruler: plastic bar with a printed face
bpy.ops.mesh.primitive_cube_add(size=1)
rb = bpy.context.object; rb.scale = (10.0, 1.5, 0.16); rb.location.z = 0.08
bpy.ops.object.transform_apply(scale=True, location=True)
bv = rb.modifiers.new("b", "BEVEL"); bv.width = 0.05; bv.segments = 4
rb.data.materials.append(mat("rulerbody", (0.62, 0.86, 0.09), rough=0.3, spec=0.6))
rf = grid("ruler_face", 10.0, 1.5, 2, 2); rf.location.z = 0.161
rf.data.materials.append(mat("ruler", tex="ruler.png", rough=0.3, alpha_tex=True, spec=0.6))
objs["ruler"] = group("ruler", [rb, rf])

# 10-K booklet: page block, cover, sticky tabs
bpy.ops.mesh.primitive_cube_add(size=1)
pb = bpy.context.object; pb.scale = (6.25, 8.25, 0.32); pb.location = (-0.05, -0.05, 0.16)
bpy.ops.object.transform_apply(scale=True, location=True)
b2 = pb.modifiers.new("b", "BEVEL"); b2.width = 0.03; b2.segments = 3
pb.data.materials.append(mat("pages", (0.86, 0.84, 0.79), rough=0.8))
cv = grid("cover", 6.4, 8.4, 2, 2); cv.location.z = 0.33
cv.data.materials.append(mat("book", tex="book.png", rough=0.45, spec=0.4)); solid(cv, 0.03)
tabs = []
for i, (c, y) in enumerate([((0.99, 0.82, 0.15), 2.6), ((0.97, 0.45, 0.62), 0.9), ((0.45, 0.85, 0.62), -0.9)]):
    bpy.ops.mesh.primitive_cube_add(size=1)
    t = bpy.context.object; t.scale = (1.2, 0.9, 0.01); t.location = (3.35, y, 0.2 - i * 0.05)
    t.data.materials.append(mat(f"tab{i}", c, rough=0.7)); tabs.append(t)
objs["book"] = group("book", [pb, cv] + tabs)

# label-maker tapes, scaled 1.6x so the name reads as the headline
for key, png, w in [("tape1", "tape1.png", 6.54), ("tape2", "tape2.png", 6.10)]:
    t = grid(key + "_m", w * 1.45, 1.1 * 1.45, 60, 6)
    bend(t, lambda x, y: 0.02 * math.sin(x * 0.9))
    t.data.materials.append(mat(key, tex=png, rough=0.34, spec=0.4, bump=png.replace(".png", "h.png"), bump_strength=0.6))
    solid(t, 0.04)
    objs[key] = group(key, [t])

LAYOUT = {
    "wide": dict(scale=22, res=(2880, 1800), pos={
        "book": (-7.9, 2.4, 9), "rcpt": (8.9, 2.4, -7), "pass": (-5.4, -4.9, -4),
        "ruler": (6.0, -5.6, 8), "tape1": (1.2, 1.6, 3), "tape2": (2.0, -0.1, -2)}),
    "tall": dict(scale=26, res=(1170, 2532), pos={
        "book": (-2.6, 8.9, 7), "rcpt": (4.2, 7.6, -8), "pass": (-1.4, -5.4, -5),
        "ruler": (1.6, -10.8, 7), "tape1": (-0.2, 0.5, 3), "tape2": (0.4, -1.3, -2)}),
}

# ---- light
bpy.ops.object.light_add(type="SUN")
sun = bpy.context.object
sun.data.energy = 3.2
sun.data.angle = math.radians(6)
sun.rotation_euler = (math.radians(32), math.radians(-14), math.radians(-30))
w = sc.world or bpy.data.worlds.new("w"); sc.world = w
w.use_nodes = True
w.node_tree.nodes["Background"].inputs["Color"].default_value = (1, 0.97, 0.93, 1)
w.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.55

bpy.ops.object.camera_add()
cam = bpy.context.object; sc.camera = cam
cam.data.type = "ORTHO"
cam.rotation_euler = (0, 0, 0)


def show(only):
    for k, o in objs.items():
        vis = only is None or k in only
        for c in [o] + list(o.children):
            c.hide_render = not vis


def render(path):
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    print("WROTE", path)


if COMP in LAYOUT:
    L = LAYOUT[COMP]
    sc.render.resolution_x, sc.render.resolution_y = L["res"]
    sc.render.resolution_percentage = 100
    cam.data.ortho_scale = L["scale"]
    cam.location = (0, 0, 50)
    for k, (x, y, rot) in L["pos"].items():
        objs[k].location = (x, y, 0.02 * list(L["pos"]).index(k))
        objs[k].rotation_euler.z = math.radians(rot)
    only = argv[4].split(",") if len(argv) > 4 else None
    jobs = only or ["full", "bg"] + list(objs)
    for j in jobs:
        desk.is_shadow_catcher = j not in ("full", "bg")
        show(None if j == "full" else [] if j == "bg" else [j])
        render(os.path.join(OUT, f"{COMP}-{j}.png"))
else:  # solo: each artefact lifted off the desk, framed tight, for the work screens
    desk.is_shadow_catcher = True
    for k in ["pass", "rcpt", "ruler", "book"]:
        show([k])
        o = objs[k]
        o.location = (0, 0, 1.4)
        o.rotation_euler.z = 0
        bpy.context.view_layer.update()
        pts = [c.matrix_world @ Vector(v) for c in o.children for v in c.bound_box]
        xs = [v.x for v in pts]; ys = [v.y for v in pts]
        mx, Mx, my, My = min(xs) - 0.6, max(xs) + 1.8, min(ys) - 1.8, max(ys) + 0.6
        wv, hv = Mx - mx, My - my
        longpx = 2000
        if wv >= hv:
            sc.render.resolution_x, sc.render.resolution_y = longpx, int(longpx * hv / wv)
        else:
            sc.render.resolution_x, sc.render.resolution_y = int(longpx * wv / hv), longpx
        cam.data.ortho_scale = max(wv, hv)
        cam.location = ((mx + Mx) / 2, (my + My) / 2, 50)
        render(os.path.join(OUT, f"solo-{k}.png"))
        o.location = (0, 0, -100)
