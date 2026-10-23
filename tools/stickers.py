"""Write the flat data stickers used as accents on the Selected Work screens to assets/stickers/*.svg.

    python3 tools/stickers.py

Hand-drawn shapes (a paper plane, a pie-chart sun, a flower whose petals are bars, a sparkline vine...); Python only does the
trig. Colours are the site palette. No faces: the page is bright but grown-up.
"""
import math
from pathlib import Path

INK, TOM, BUT, SKY, LIL, MINT, WHITE = "#15193A", "#FF7759", "#FFD84D", "#9BD3FF", "#CDC6FF", "#BDEBC8", "#FFFFFF"
LEAF = "#2F8F5B"


def star(cx, cy, n, r1, r2, rot=0):
    pts = []
    for i in range(n * 2):
        r = r1 if i % 2 == 0 else r2
        a = math.pi * i / n + rot
        pts.append(f"{cx + r * math.sin(a):.1f},{cy - r * math.cos(a):.1f}")
    return " ".join(pts)


def leaf(x, y, ang, s=1, fill=LEAF):
    return (f'<g transform="translate({x} {y}) rotate({ang}) scale({s})"><path d="M0 0C14-20 52-24 78 0C52 24 14 20 0 0Z" fill="{fill}"/>'
            f'<path d="M6 0H66M24 0l10-8M24 0l10 8M44 0l9-7M44 0l9 7" stroke="#fff" stroke-width="3" stroke-linecap="round" fill="none" opacity=".85"/></g>')


def svg(vb, body):
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}">{body}</svg>\n'


STICKERS = {
    "plane": svg("0 0 240 180",
                 '<path d="M8 160C40 150 50 120 84 118" stroke="#fff" stroke-width="5" stroke-dasharray="4 12" stroke-linecap="round" fill="none"/>'
                 '<polygon points="70,104 232,20 150,170 122,118" fill="#fff"/><polygon points="122,118 232,20 104,128" fill="#DCE8F7"/>'
                 '<polygon points="122,118 104,128 112,150" fill="#B9CFE6"/>'),
    "cloud": svg("0 0 120 240",
                 f'<defs><clipPath id="c"><ellipse cx="60" cy="120" rx="56" ry="116"/></clipPath></defs><ellipse cx="60" cy="120" rx="56" ry="116" fill="{SKY}"/>'
                 '<g clip-path="url(#c)" fill="#fff"><circle cx="50" cy="70" r="20"/><circle cx="76" cy="62" r="24"/><circle cx="104" cy="74" r="18"/>'
                 '<rect x="40" y="70" width="80" height="22"/><circle cx="30" cy="160" r="22"/><circle cx="62" cy="150" r="26"/><circle cx="96" cy="164" r="18"/>'
                 '<rect x="0" y="162" width="110" height="24"/></g>'),
    "sun": svg("0 0 220 220",
               f'<polygon points="{star(110, 110, 14, 104, 72)}" fill="{BUT}"/><circle cx="110" cy="110" r="58" fill="{TOM}"/>'
               '<path d="M110 110V52A58 58 0 0 1 165 128Z" fill="#fff"/>'
               f'<path d="M110 110L165 128A58 58 0 0 1 128 165Z" fill="{LIL}"/>'),
    "flower": svg("0 0 200 260",
                  f'<path d="M100 120C96 170 112 205 100 256" stroke="{INK}" stroke-width="9" fill="none" stroke-linecap="round"/>'
                  + leaf(102, 200, -35, 0.9) + leaf(98, 175, 215, 0.8) + '<g transform="translate(100 96)">'
                  + "".join(f'<rect x="-12" y="{-L - 14}" width="24" height="{L}" rx="12" fill="{TOM if i % 2 else BUT}" transform="rotate({360 * i / 9:.1f})"/>'
                            for i, L in enumerate((34, 46, 30, 50, 38, 44, 28, 48, 36)))
                  + f'<circle r="20" fill="#fff"/><circle r="9" fill="{TOM}"/></g>'),
    "bag": svg("0 0 200 220",
               f'<path d="M66 70V52a34 34 0 0 1 68 0v18" stroke="{INK}" stroke-width="13" fill="none" stroke-linecap="round"/>'
               f'<path d="M30 70h140l-10 136a10 10 0 0 1-10 9H50a10 10 0 0 1-10-9z" fill="{TOM}"/><path d="M30 70h140l-2 22H32z" fill="#E85A3E"/>'
               '<path d="M72 184v-34M100 184v-60M128 184v-44" stroke="#fff" stroke-width="15" stroke-linecap="round"/>'),
    "vine": svg("0 0 250 200",
                "".join(leaf(x, y, a, 0.55) for (x, y), a in zip([(58, 120), (92, 146), (136, 62), (176, 92)], (-70, 110, -60, 120)))
                + f'<polyline points="14,170 58,120 92,146 136,62 176,92 226,26" fill="none" stroke="{INK}" stroke-width="11" stroke-linejoin="round" stroke-linecap="round"/>'
                + "".join(f'<circle cx="{x}" cy="{y}" r="9" fill="#fff" stroke="{INK}" stroke-width="5"/>' for x, y in [(14, 170), (58, 120), (92, 146), (136, 62), (176, 92)])
                + f'<polygon points="238,14 204,22 228,48" fill="{INK}"/>'),
    "magnifier": svg("0 0 220 220",
                     f'<rect x="132" y="120" width="34" height="96" rx="17" fill="{INK}" transform="rotate(-45 149 168)"/>'
                     f'<circle cx="92" cy="92" r="70" fill="{INK}"/><circle cx="92" cy="92" r="56" fill="{SKY}"/>'
                     '<path d="M58 70a44 44 0 0 1 28-28" stroke="#fff" stroke-width="9" fill="none" stroke-linecap="round"/>'
                     '<path d="M68 98l18 18 34-38" stroke="#fff" stroke-width="12" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'),
    "leaf": svg("0 0 200 120",
                f'<path d="M8 60C50-6 150-6 192 60C150 126 50 126 8 60Z" fill="{LEAF}"/>'
                '<path d="M26 60H170M60 60l22-20M60 60l22 20M100 60l22-22M100 60l22 22M138 60l16-14M138 60l16 14" stroke="#fff" stroke-width="5" stroke-linecap="round" fill="none"/>'),
    "spark": svg("0 0 100 100", f'<polygon points="{star(50, 50, 4, 48, 12)}" fill="#fff"/>'),
    "spark-ink": svg("0 0 100 100", f'<polygon points="{star(50, 50, 4, 48, 12)}" fill="{INK}"/>'),
}

if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "assets" / "stickers"
    out.mkdir(parents=True, exist_ok=True)
    for name, body in STICKERS.items():
        (out / f"{name}.svg").write_text(body)
    print(f"wrote {len(STICKERS)} stickers to {out}")
