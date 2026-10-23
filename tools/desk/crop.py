# Cuts each artefact pass to its alpha box and records where it sits in the frame (percent), so CSS layers line up with the full render.
import json, sys
from PIL import Image, ImageFilter

R, O = "render", "img"
layers = {}
for comp in ("wide", "tall"):
    full = Image.open(f"{R}/{comp}-full.png").convert("RGB")
    W, H = full.size
    full.save(f"{O}/{comp}-full.jpg", quality=86)
    Image.open(f"{R}/{comp}-bg.png").convert("RGB").save(f"{O}/{comp}-bg.jpg", quality=80)
    layers[comp] = {}
    for k in ("book", "rcpt", "pass", "ruler", "tape1", "tape2"):
        im = Image.open(f"{R}/{comp}-{k}.png").convert("RGBA")
        A = im.getchannel("A").point(lambda v: 0 if v < 10 else v)  # drop denoiser speckle
        im.putalpha(A)
        box = A.filter(ImageFilter.MinFilter(5)).point(lambda v: 255 if v > 24 else 0).getbbox()
        pad = 24  # keep the soft shadow tail
        box = (max(0, box[0] - pad), max(0, box[1] - pad), min(W, box[2] + pad), min(H, box[3] + pad))
        assert box, k
        im.crop(box).save(f"{O}/{comp}-{k}.webp", quality=88, method=6)
        x0, y0, x1, y1 = box
        layers[comp][k] = [round(100 * x0 / W, 3), round(100 * y0 / H, 3), round(100 * (x1 - x0) / W, 3), round(100 * (y1 - y0) / H, 3)]
for k in ("pass", "rcpt", "ruler", "book"):
    im = Image.open(f"{R}/solo-{k}.png").convert("RGBA")  # keep the object, drop the baked lift shadow (CSS draws one)
    im.putalpha(im.getchannel("A").point(lambda v: 255 if v > 240 else 0).filter(ImageFilter.GaussianBlur(0.7)))
    im.save(f"{O}/solo-{k}.webp", quality=90, method=6)
open("layers.js", "w").write("window.LAYERS=" + json.dumps(layers) + ";\n")
print(json.dumps(layers))
