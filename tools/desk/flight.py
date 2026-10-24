# Blender 4.5: the home page hero. The four printed project objects on a pale oak desk; the camera starts high and wide and
# glides down onto the boarding pass, which the first Selected Work screen then carries. The scene itself is scene.py.
# usage: Blender -b --factory-startup -P tools/desk/flight.py -- <out_prefix> <w> <h> <frames> [only_frame]
#   frames 1 = the opening still.
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scene
from mathutils import Vector

a = sys.argv[sys.argv.index("--") + 1:]
out, W, H, NF = a[0], int(a[1]), int(a[2]), int(a[3])
ONLY = int(a[4]) if len(a) > 4 else None

objs, POS, START, END, portrait = scene.build(W, H)
cam = scene.sc.camera
px, py, prot = POS["pass"]
aim_end = Vector((px, py + 0.2, 0.0))
eye_end = aim_end + Vector(END["off"])


def smooth(t):
    return t * t * t * (t * (t * 6 - 15) + 10)


def place(t):
    """Camera at flight time t in [0, 1]: high and wide at 0, square over the boarding pass at 1."""
    e = smooth(t)
    eye = Vector(START["eye"]).lerp(eye_end, e)
    aim = Vector(START["aim"]).lerp(aim_end, e)
    scene.look(cam, eye, aim, START["lens"] + (END["lens"] - START["lens"]) * e, prot * e)


if __name__ == "__main__":
    for i in (range(NF) if ONLY is None else [ONLY]):
        place(i / max(1, NF - 1))
        scene.render(f"{out}{i:03d}.png")
