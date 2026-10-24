# Blender 4.5: the rest of the home page, shot on the same desk as the flight (scene.py).
#   print-00..06   the opening beat: the camera square over the boarding pass (the flight's last frame) while the pass
#                  prints from the top down; print-06 is nearly complete and flight frame 47 finishes it
#   shot-pass|rcpt|ruler|book   each project screen's background: the camera low over that object's place on the desk
#                  with the object itself hidden (the page lays the printed object down as HTML so it can lift and flip)
#   shot-about     the open desk between the objects, for the notebook
#   shot-contact   the same table at the end of the day: low warm sun, long shadows
# usage: Blender -b --factory-startup -P tools/desk/world.py -- <out_dir> <w> <h> [only_name]
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy, scene
from mathutils import Vector

a = sys.argv[sys.argv.index("--") + 1:]
OUT, W, H = a[0], int(a[1]), int(a[2])
ONLY = a[3] if len(a) > 3 else None
os.makedirs(OUT, exist_ok=True)

objs, POS, START, END, portrait = scene.build(W, H)
cam, sc = scene.sc.camera, scene.sc
sun = bpy.data.objects["sun"]


def want(name):
    return ONLY is None or name.startswith(ONLY)


def hide(name, on):
    for o in [objs[name]] + list(objs[name].children):
        o.hide_render = on


def over(obj, off, lens, aim_dy=0.0, roll=0.0):
    x, y, _ = POS[obj]
    aim = Vector((x, y + aim_dy, 0.0))
    scene.look(cam, aim + Vector(off), aim, lens, roll)


# ---- the print beat: the pass as the flight leaves it, printing from the top down
px, py, prot = POS["pass"]
aim_end = Vector((px, py + 0.2, 0.0))
scene.look(cam, aim_end + Vector(END["off"]), aim_end, END["lens"], prot)
pass_img = bpy.data.images.load(os.path.join(scene.TEX, "pass.png"))
pw, ph = pass_img.size
full = list(pass_img.pixels)
paper = (*scene.srgb("#fbfaf6"), 1.0)
pass_mat = bpy.data.materials["pass"]
tex_node = next(n for n in pass_mat.node_tree.nodes if n.type == "TEX_IMAGE")
STAGES = [0.0, 0.14, 0.3, 0.46, 0.62, 0.78, 0.9]
for i, f in enumerate(STAGES):
    name = f"print-{i:02d}"
    if not want(name):
        continue
    img = bpy.data.images.new(name, pw, ph, alpha=True)
    cut = int(ph * (1 - f))          # rows are stored bottom-up: everything below the print line is still blank paper
    px_ = full[:]
    for row in range(cut):
        s = row * pw * 4
        px_[s:s + pw * 4] = paper * pw
    img.pixels = px_
    tex_node.image = img
    scene.render(os.path.join(OUT, name + ".png"))
tex_node.image = pass_img

# ---- the project screens: low over each object's place, the object itself hidden
SHOT = (dict(off=(0.0, -9.0, 19.0), lens=32, aim_dy=1.5) if portrait else dict(off=(0.0, -15.0, 13.0), lens=32, aim_dy=2.5))
for k in ("pass", "rcpt", "ruler", "book"):
    name = f"shot-{k}"
    if not want(name):
        continue
    hide(k, True)
    over(k, SHOT["off"], SHOT["lens"], SHOT["aim_dy"])
    scene.render(os.path.join(OUT, name + ".png"))
    hide(k, False)

# ---- about: the open desk between the objects
if portrait:
    scene.look(cam, (0.0, -12.0, 21.0), (0.0, 2.5, 0.0), 32)
else:
    scene.look(cam, (0.0, -19.0, 14.0), (0.0, 1.0, 0.0), 32)
if want("shot-about"):
    scene.render(os.path.join(OUT, "shot-about.png"))

# ---- contact: the same afternoon, seen from the other side of the desk (the visitor has walked round the table)
if want("shot-contact"):
    if portrait:
        scene.look(cam, (9.0, 10.0, 20.0), (0.0, -1.0, 0.0), 34)
    else:
        scene.look(cam, (16.0, 14.0, 13.0), (0.0, -2.0, 0.0), 34)
    scene.render(os.path.join(OUT, "shot-contact.png"))
