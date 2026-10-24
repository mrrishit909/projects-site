# Blender 4.5: the one desk every home-page render comes from. flight.py (the camera flight) and world.py (the section
# backgrounds and the print beat) both call build(); the scene is identical, so every frame on the site is the same table
# under the same afternoon sun. Textures: tools/desk/tex/*.png (printed with tools/desk/tex.html + shoot.cjs).
import bpy, math, os
from mathutils import Vector

TEX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tex")
sc = None


def srgb(h):
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c)


def mat(name, color=None, tex=None, rough=0.6, alpha_tex=False, spec=0.5, image=None):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    p = nt.nodes["Principled BSDF"]
    p.inputs["Roughness"].default_value = rough
    p.inputs["Specular IOR Level"].default_value = spec
    if color:
        p.inputs["Base Color"].default_value = (*srgb(color), 1)
    if tex or image:
        t = nt.nodes.new("ShaderNodeTexImage")
        t.image = image or bpy.data.images.load(os.path.join(TEX, tex))
        t.interpolation = "Cubic"
        t.extension = "CLIP"
        nt.links.new(t.outputs["Color"], p.inputs["Base Color"])
        if alpha_tex:
            nt.links.new(t.outputs["Alpha"], p.inputs["Alpha"])
            m.surface_render_method = "DITHERED"
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


def build(W, H, samples=64):
    """Renderer, desk, the four objects where they lie, the sun. Returns (objs, POS, START, END, portrait)."""
    global sc
    portrait = H > W
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    r = sc.render
    r.engine = "BLENDER_EEVEE_NEXT"
    r.resolution_x, r.resolution_y, r.resolution_percentage = W, H, 100
    r.image_settings.file_format = "PNG"
    r.image_settings.color_mode = "RGB"
    sc.view_settings.view_transform = "Standard"
    sc.view_settings.look = "None"
    ee = sc.eevee
    ee.taa_render_samples = samples
    ee.use_shadows = True
    ee.use_raytracing = True
    ee.ray_tracing_options.resolution_scale = "1"
    ee.fast_gi_method = "GLOBAL_ILLUMINATION"
    ee.shadow_resolution_scale = 1.0

    # ---- desk: pale oak, fine grain along x
    bpy.ops.mesh.primitive_plane_add(size=240)
    desk = bpy.context.object
    dm = mat("oak", rough=0.55, spec=0.3)
    n, L = dm.node_tree.nodes, dm.node_tree.links
    tc = n.new("ShaderNodeTexCoord")
    mp = n.new("ShaderNodeMapping"); mp.inputs["Scale"].default_value = (0.04, 1.6, 1.0)
    wave = n.new("ShaderNodeTexNoise"); wave.inputs["Scale"].default_value = 2.2; wave.inputs["Detail"].default_value = 10.0; wave.inputs["Roughness"].default_value = 0.62
    noise = n.new("ShaderNodeTexNoise"); noise.inputs["Scale"].default_value = 9.0; noise.inputs["Detail"].default_value = 6.0
    mix = n.new("ShaderNodeMix"); mix.data_type = "FLOAT"; mix.inputs["Factor"].default_value = 0.55
    ramp = n.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position, ramp.color_ramp.elements[0].color = 0.3, (*srgb("#e8dfcf"), 1)
    ramp.color_ramp.elements[1].position, ramp.color_ramp.elements[1].color = 0.75, (*srgb("#d9cab0"), 1)
    L.new(tc.outputs["Object"], mp.inputs["Vector"])
    L.new(mp.outputs["Vector"], wave.inputs["Vector"]); L.new(mp.outputs["Vector"], noise.inputs["Vector"])
    L.new(wave.outputs["Fac"], mix.inputs["A"]); L.new(noise.outputs["Fac"], mix.inputs["B"])
    L.new(mix.outputs["Result"], ramp.inputs["Fac"])
    L.new(ramp.outputs["Color"], n["Principled BSDF"].inputs["Base Color"])
    bn = n.new("ShaderNodeBump"); bn.inputs["Strength"].default_value = 0.05
    L.new(mix.outputs["Result"], bn.inputs["Height"]); L.new(bn.outputs["Normal"], n["Principled BSDF"].inputs["Normal"])
    desk.data.materials.append(dm)

    # ---- the four objects (units: CSS px / 100 of the printed textures), as in tools/desk/desk.py
    objs = {}
    p = grid("pass_m", 8.0, 3.2)
    bend(p, lambda x, y: 0.06 * max(0, (x - 2.0) / 2.0) ** 2)
    p.data.materials.append(mat("pass", tex="pass.png", rough=0.55, spec=0.35)); solid(p, 0.025)
    objs["pass"] = group("pass", [p])

    rc = grid("rcpt_m", 3.0, 10.0, 12, 80)
    bend(rc, lambda x, y: 0.55 * (abs(y) / 5.0) ** 5 + 0.03 * math.sin(y * 1.3))
    rc.location.z = 0.045
    rc.data.materials.append(mat("rcpt", tex="rcpt.png", rough=0.4, alpha_tex=True, spec=0.4)); solid(rc, 0.012)
    objs["rcpt"] = group("rcpt", [rc])

    bpy.ops.mesh.primitive_cube_add(size=1)
    rb = bpy.context.object; rb.scale = (10.0, 1.5, 0.16); rb.location.z = 0.08
    bpy.ops.object.transform_apply(scale=True, location=True)
    bv = rb.modifiers.new("b", "BEVEL"); bv.width = 0.05; bv.segments = 4
    rb.data.materials.append(mat("rulerbody", "#d8f56a", rough=0.3, spec=0.6))
    rf = grid("ruler_face", 10.0, 1.5, 2, 2); rf.location.z = 0.161
    rf.data.materials.append(mat("ruler", tex="ruler.png", rough=0.3, alpha_tex=True, spec=0.6))
    objs["ruler"] = group("ruler", [rb, rf])

    bpy.ops.mesh.primitive_cube_add(size=1)
    pb = bpy.context.object; pb.scale = (6.25, 8.25, 0.32); pb.location = (-0.05, -0.05, 0.16)
    bpy.ops.object.transform_apply(scale=True, location=True)
    b2 = pb.modifiers.new("b", "BEVEL"); b2.width = 0.03; b2.segments = 3
    pb.data.materials.append(mat("pages", "#efece4", rough=0.8))
    cv = grid("cover", 6.4, 8.4, 2, 2); cv.location.z = 0.33
    cv.data.materials.append(mat("book", tex="book.png", rough=0.45, spec=0.4)); solid(cv, 0.03)
    tabs = []
    for i, (c, y) in enumerate([("#fcd63c", 2.6), ("#f7a3c0", 0.9), ("#a6e3c2", -0.9)]):
        bpy.ops.mesh.primitive_cube_add(size=1)
        t = bpy.context.object; t.scale = (1.2, 0.9, 0.01); t.location = (3.35, y, 0.2 - i * 0.05)
        t.data.materials.append(mat(f"tab{i}", c, rough=0.7)); tabs.append(t)
    objs["book"] = group("book", [pb, cv] + tabs)

    # where they lie (x, y, degrees). The camera looks toward +y, so the open desk beyond them carries the wordmark.
    if portrait:
        POS = {"pass": (0.0, -2.4, -4), "book": (-3.6, 7.2, 9), "rcpt": (3.9, 6.2, -8), "ruler": (0.6, -10.0, 5)}
        START = dict(eye=(0.0, -15.0, 24.0), aim=(0.0, 2.6, 0.0), lens=30)
        END = dict(off=(0.0, -6.5, 23.0), lens=42)
    else:
        POS = {"pass": (-1.5, -9.0, -4), "book": (-11.5, -1.0, 10), "rcpt": (11.0, -1.5, -9), "ruler": (9.0, -11.0, 7)}
        START = dict(eye=(0.0, -25.0, 14.0), aim=(0.0, 3.5, 0.0), lens=30)
        END = dict(off=(0.0, -6.2, 9.8), lens=40)
    for k, (x, y, rot) in POS.items():
        objs[k].location = (x, y, 0.0)
        objs[k].rotation_euler.z = math.radians(rot)

    # ---- light: soft afternoon sun from the upper left plus a warm sky
    bpy.ops.object.light_add(type="SUN")
    sun = bpy.context.object
    sun.name = "sun"
    sun.data.energy = 2.3
    sun.data.angle = math.radians(9)
    sun.rotation_euler = (math.radians(36), math.radians(-18), math.radians(-35))
    w = bpy.data.worlds.new("w"); sc.world = w
    w.use_nodes = True
    w.node_tree.nodes["Background"].inputs["Color"].default_value = (*srgb("#fff6ea"), 1)
    w.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.5

    bpy.ops.object.camera_add()
    cam = bpy.context.object; sc.camera = cam
    cam.data.sensor_fit = "AUTO"
    cam.data.clip_start, cam.data.clip_end = 0.1, 500
    return objs, POS, START, END, portrait


def look(cam, eye, aim, lens, roll_deg=0.0):
    """Put the camera at eye looking at aim, rolled about its own axis."""
    cam.location = Vector(eye)
    d = Vector(aim) - Vector(eye)
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    cam.rotation_euler.rotate_axis("Z", math.radians(roll_deg))
    cam.data.lens = lens


def render(path):
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    print("WROTE", path)
