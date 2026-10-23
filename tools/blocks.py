# Toy blocks for the portfolio hero: a loose pile that stacks itself, block by block, into a rising bar chart.
# Transparent background so the page's colour field shows through.
#   Blender -b --factory-startup -P blocks.py -- <outdir> <frames> [only ...]
import bpy, math, random, sys
from mathutils import Euler

argv = sys.argv[sys.argv.index("--") + 1:]
OUT, NF = argv[0], int(argv[1]); FORM = argv[2] if len(argv) > 2 and not argv[2].isdigit() else "chart"
ONLY = [int(a) for a in argv[3 if FORM != "chart" or (len(argv) > 2 and not argv[2].isdigit()) else 2:] if a.isdigit()]
RES = 1400 if not FORM.startswith("icon") else 640
for o in list(bpy.data.objects): bpy.data.objects.remove(o)
sc = bpy.context.scene
for eng in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
    try: sc.render.engine = eng; break
    except TypeError: pass
sc.render.resolution_x = sc.render.resolution_y = RES
sc.render.film_transparent = True
sc.render.image_settings.file_format = "PNG"; sc.render.image_settings.color_mode = "RGBA"
sc.view_settings.view_transform = "Standard"
try:
    sc.eevee.taa_render_samples = 64
    sc.eevee.use_shadows = True
except AttributeError: pass
w = bpy.data.worlds.new("w"); sc.world = w; w.use_nodes = True
w.node_tree.nodes["Background"].inputs[0].default_value = (0.85, 0.93, 1.0, 1); w.node_tree.nodes["Background"].inputs[1].default_value = 0.55

def lacquer(name, col):
    m = bpy.data.materials.new(name); m.use_nodes = True
    p = m.node_tree.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = (*col, 1); p.inputs["Roughness"].default_value = 0.28
    p.inputs["Coat Weight"].default_value = 0.5; p.inputs["Coat Roughness"].default_value = 0.15
    return m

COLS = [lacquer("tomato", (1.0, 0.18, 0.07)), lacquer("butter", (1.0, 0.72, 0.12)), lacquer("forest", (0.02, 0.2, 0.12)),
        lacquer("cream", (1.0, 0.93, 0.8)), lacquer("mint", (0.42, 0.85, 0.56))]

S = 0.5           # block size
GAP = 0.06
P = S + GAP
def grid(rows, colour_of):
    """Rows of a pixel pattern, top first, standing upright in the x/z plane."""
    out = []
    H = len(rows)
    for r, row in enumerate(rows):
        for c, ch in enumerate(row):
            if ch != ".":
                out.append(((c - (len(row) - 1) / 2) * P, 0.0, S / 2 + (H - 1 - r) * (S + 0.004), colour_of(r, c, ch)))
    return out
targets = []
if FORM == "chart":
    # six bars rising left to right (1, 2, 2, 3, 4, 5 blocks), one colour per bar
    for c, h in enumerate([1, 2, 2, 3, 4, 5]):
        for r in range(h):
            targets.append(((c - 2.5) * P, 0.0, S / 2 + r * (S + 0.004), c))
elif FORM == "letter_r":
    targets = grid(["XXX.", "X..X", "XXX.", "X.X.", "X..X"], lambda r, c, ch: [0, 1, 4, 3, 0][r])
elif FORM == "stairs":
    for c, h in enumerate([1, 2, 3, 4]):
        for r in range(h):
            targets.append(((c - 1.5) * P, 0.0, S / 2 + r * (S + 0.004), [4, 1, 3, 0][c]))
elif FORM == "hi":
    targets = grid(["X.X.X", "X.X.X", "XXX.X", "X.X.X", "X.X.X"], lambda r, c, ch: 3 if (r + c) % 2 == 0 else 1)
elif FORM == "icon_bars":
    for c, h in enumerate([1, 2, 3]):
        for r in range(h):
            targets.append(((c - 1) * P, 0.0, S / 2 + r * (S + 0.004), [0, 1, 4][c]))
elif FORM == "icon_pipe":
    for c in range(4):
        targets.append(((c - 1.5) * (P + 0.12), 0.0, S / 2 + (0.0 if c % 2 == 0 else 0.0), [3, 1, 4, 0][c]))
elif FORM == "icon_trend":
    for c in range(4):
        targets.append(((c - 1.5) * P, 0.0, S / 2 + c * (S * 0.62), [4, 1, 3, 0][c]))
elif FORM == "icon_ai":
    for x in (0, 1):
        for y in (0, 1):
            for z in (0, 1):
                targets.append(((x - 0.5) * P, (y - 0.5) * P, S / 2 + z * (S + 0.004), 0 if (x, y, z) == (0, 0, 1) else [2, 4, 3, 1][(x + y + z) % 4]))
rng = random.Random(11)
blocks = []
for i, (tx, ty, tz, c) in enumerate(targets):
    bpy.ops.mesh.primitive_cube_add(size=S)
    b = bpy.context.object
    bev = b.modifiers.new("b", "BEVEL"); bev.width = 0.06; bev.segments = 5
    bpy.ops.object.shade_smooth()
    b.data.materials.append(COLS[c % len(COLS)])
    # loose pile: scattered on the floor and in the air, tumbled
    px, py = rng.uniform(-1.9, 1.9), rng.uniform(-0.9, 0.9)
    pz = S / 2 + rng.choice([0, 0, 0, S, S * 2]) + rng.uniform(0, 0.4)
    prot = (rng.uniform(-0.6, 0.6), rng.uniform(-0.6, 0.6), rng.uniform(-math.pi, math.pi))
    blocks.append((b, (px, py, pz), prot, (tx, ty, tz)))

if FORM == "icon_pipe":
    bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=0.06, depth=4 * (P + 0.12), rotation=(0, math.pi / 2, 0), location=(0, 0, S / 2))
    rod = bpy.context.object; rod.data.materials.append(COLS[2]); bpy.ops.object.shade_smooth()

# floor that only catches shadows (transparent otherwise)
bpy.ops.mesh.primitive_plane_add(size=30)
floor = bpy.context.object
try: floor.is_shadow_catcher = True
except AttributeError: pass
floor.visible_camera = True
fm = bpy.data.materials.new("floor"); fm.use_nodes = True
nt = fm.node_tree
for n in list(nt.nodes): nt.nodes.remove(n)
out = nt.nodes.new("ShaderNodeOutputMaterial"); sh = nt.nodes.new("ShaderNodeBsdfDiffuse"); tr = nt.nodes.new("ShaderNodeBsdfTransparent")
mix = nt.nodes.new("ShaderNodeMixShader"); lp = nt.nodes.new("ShaderNodeLightPath")
sh.inputs[0].default_value = (0.2, 0.3, 0.45, 1)
nt.links.new(lp.outputs["Is Camera Ray"], mix.inputs[0]); nt.links.new(sh.outputs[0], mix.inputs[1]); nt.links.new(tr.outputs[0], mix.inputs[2])
nt.links.new(mix.outputs[0], out.inputs[0])
try: fm.blend_method = "BLEND"
except Exception: pass
floor.data.materials.append(fm)
floor.hide_render = True   # replaced by the CSS contact shadow; kept for experiments

sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN")); sc.collection.objects.link(sun)
sun.data.energy = 3.2; sun.data.angle = math.radians(8); sun.rotation_euler = (math.radians(52), 0, math.radians(-38))
fill = bpy.data.objects.new("fill", bpy.data.lights.new("fill", "AREA")); sc.collection.objects.link(fill)
fill.data.energy = 160; fill.data.size = 6; fill.location = (3, -3, 2.5); fill.rotation_euler = (math.radians(60), 0, math.radians(45))

cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); sc.collection.objects.link(cam); sc.camera = cam
cam.data.lens = 60
tgt = bpy.data.objects.new("t", None); sc.collection.objects.link(tgt)
ZC = max(t[2] for t in targets) / 2 + S / 4
tgt.location = (0, 0, ZC)
DIST = {"chart": 7.4, "letter_r": 7.0, "stairs": 6.2, "hi": 7.6}.get(FORM, 5.2)
tc = cam.constraints.new("TRACK_TO"); tc.target = tgt; tc.track_axis = "TRACK_NEGATIVE_Z"; tc.up_axis = "UP_Y"

def ease_back(t, s=1.4):
    t -= 1
    return t * t * ((s + 1) * t + s) + 1

def lerp(a, b, t): return a + (b - a) * t

n = len(blocks)
for fi in (ONLY or range(NF)):
    u = fi / max(NF - 1, 1)
    for i, (b, p0, r0, p1) in enumerate(blocks):
        # build order: bottom rows first, left to right, so the chart grows as a stack
        order = sorted(range(n), key=lambda k: (blocks[k][3][2], blocks[k][3][0])).index(i)
        start = 0.05 + 0.75 * order / n
        k = max(0.0, min(1.0, (u - start) / 0.2))
        e = ease_back(k) if k > 0 else 0
        lift = math.sin(min(1, k) * math.pi) * 0.9          # each block hops up on its way
        b.location = (lerp(p0[0], p1[0], e), lerp(p0[1], p1[1], e), lerp(p0[2], p1[2], min(1, e)) + lift)
        b.rotation_euler = Euler((lerp(r0[0], 0, min(1, e)), lerp(r0[1], 0, min(1, e)), lerp(r0[2], 0, min(1, e))))
    # camera: a slow orbit from three-quarter to a near-front view
    a = math.radians(lerp(-38, -16, u) if not FORM.startswith("icon") else -30)
    cam.location = (DIST * math.sin(a), -DIST * math.cos(a), ZC + lerp(2.4, 1.4, u) if not FORM.startswith("icon") else ZC + 2.2)
    sc.render.filepath = f"{OUT}/{fi:03d}.png"
    bpy.ops.render.render(write_still=True)
