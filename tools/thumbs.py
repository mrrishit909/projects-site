"""Catalogue thumbnails: every <slug>/cover.jpg -> assets/thumbs/<slug>.webp, 880x503 (twice the widest tile).

    python3 tools/thumbs.py          (macOS sips + cwebp; skips thumbnails newer than their cover)

The crop keeps the top-left 72% of the cover's width (where the covers put their headline or chart title) at the tile's
1.75 aspect, so a tile shows a legible part of the page instead of the whole page shrunk to unreadable text.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "thumbs"
W, H, KEEP = 880, 503, 0.72


def size(path):
    out = subprocess.run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(path)], capture_output=True, text=True, check=True).stdout
    vals = [int(line.split()[-1]) for line in out.splitlines() if "pixel" in line]
    return vals[0], vals[1]


def crop_box(w, h):
    """(crop_w, crop_h): KEEP of the width at W:H, never taller than the cover."""
    cw = round(w * KEEP)
    ch = round(cw * H / W)
    if ch > h:
        ch, cw = h, round(h * W / H)
    return cw, ch


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    covers = sorted(p for p in ROOT.glob("*/cover.jpg") if (p.parent / "project.json").exists())
    made = 0
    with tempfile.TemporaryDirectory() as tmp:
        for cover in covers:
            dst = OUT / f"{cover.parent.name}.webp"
            if dst.exists() and dst.stat().st_mtime >= cover.stat().st_mtime and "--all" not in sys.argv:
                continue
            cw, ch = crop_box(*size(cover))
            mid = Path(tmp) / "c.png"
            subprocess.run(["sips", "-s", "format", "png", "--cropOffset", "1", "1", "-c", str(ch), str(cw), str(cover), "--out", str(mid)],
                           capture_output=True, check=True)
            subprocess.run(["cwebp", "-quiet", "-q", "80", "-m", "6", "-resize", str(W), str(H), str(mid), "-o", str(dst)], check=True)
            made += 1
    print(f"{made} thumbnails written, {len(covers)} covers")


if __name__ == "__main__":
    assert crop_box(1400, 780) == (1008, 576) and crop_box(1000, 300) == (525, 300)
    main()
