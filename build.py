"""Build the projects site: every <slug>/project.json -> <slug>/index.html, plus the root index.html.

    python3 build.py

Text fields in project.json are trusted HTML fragments (we write them ourselves).
Stdlib only, so GitHub never needs to run anything: we commit the built HTML.
"""
import hashlib
import json
import re
import struct
from collections import Counter
from html import escape
from pathlib import Path

ROOT = Path(__file__).parent
PORTFOLIO = "https://mrrishit909.github.io/"
REQUIRED = ["title", "tagline", "kind", "tech", "date", "repo", "problem", "built", "steps", "results", "next"]
# Every project carries the same format: one project.json, one cover.jpg, the standard case-study page, its record on the shelf,
# and the site-wide colours. These checks make the build refuse a project that would break that.
FROZEN_OK = {"trading-bot"}          # published before the standard format; kept as-is. No new project may be frozen.
OWN_STYLING = ("style=", "<style", "<script", "<link", "<font")   # text fields may not bring their own look


def text_fields(p):
    """Every HTML text fragment in a project.json (top-level strings, step titles and bodies)."""
    yield from (v for v in p.values() if isinstance(v, str))
    for st in p.get("steps", []):
        yield from (v for k, v in st.items() if k != "code" and isinstance(v, str))


# ---- motion tiles -------------------------------------------------------------------------------------------
# A project's card on the home page plays <slug>/loop.mp4 (+ loop.webm) when those files exist; otherwise it shows a
# slow pan over cover.jpg. Nothing has to be declared in project.json: files are found by name, and the card's shape
# (aspect ratio) is read from the media itself.
LOOPS = ["loop.mp4", "loop.webm"]


def mp4_aspect(path):
    """Width / height from the track header (tkhd) of an .mp4, or None."""
    data = path.read_bytes()

    def walk(lo, hi):
        i = lo
        while i + 8 <= hi:
            size, kind = struct.unpack(">I4s", data[i:i + 8])
            if size == 1:
                size = struct.unpack(">Q", data[i + 8:i + 16])[0]
            if size < 8:
                return None
            end = min(hi, i + size)
            if kind == b"tkhd":
                w, h = struct.unpack(">II", data[end - 8:end])
                if w and h:
                    return (w >> 16) / (h >> 16)
            elif kind in (b"moov", b"trak"):
                found = walk(i + 8, end)
                if found:
                    return found
            i += size
        return None
    return walk(0, len(data))


def image_size(path):
    """(width, height) of a .jpg or .png, or None."""
    d = path.read_bytes()
    if d[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", d[16:24])
    i = 2
    while d[:2] == b"\xff\xd8" and i + 9 < len(d):
        if d[i] != 0xFF:
            i += 1
            continue
        m = d[i + 1]
        if m in (0xC0, 0xC1, 0xC2):
            h, w = struct.unpack(">HH", d[i + 5:i + 9])
            return w, h
        i += 2 + struct.unpack(">H", d[i + 2:i + 4])[0]
    return None


def image_aspect(path):
    """Width / height of a .jpg or .png, or None."""
    wh = image_size(path)
    return wh[0] / wh[1] if wh else None


def tile_media(folder, p):
    """-> (existing loop files, card aspect ratio). Cards keep a calm range of shapes so the row stays balanced."""
    loops = [f for f in LOOPS if (folder / f).exists()]
    aspect = None
    if (folder / "loop.mp4").exists():
        aspect = mp4_aspect(folder / "loop.mp4")
    if aspect is None and p.get("cover") and (folder / p["cover"]).exists():
        aspect = image_aspect(folder / p["cover"])
        if aspect:                       # a screenshot is cropped to fit the card, so keep it in a sane range
            aspect = min(1.9, max(1.3, aspect))
    return loops, round(aspect or 1.7, 3)


GH_ALIAS = {s: "crm-showcases" for s in ("akaunting-crm", "dolibarr-crm", "erpnext-crm", "huly-crm", "idurar-crm", "krayin-crm", "monica-crm", "nocobase-crm", "suitecrm-crm", "twenty-crm")}


def github():
    """data/github.json: one record per public repository (tools/github.sh), keyed by name."""
    f = ROOT / "data" / "github.json"
    return {r["name"]: r for r in json.loads(f.read_text())} if f.exists() else {}


def load():
    gh = github()
    projects = []
    for f in sorted(ROOT.glob("*/project.json")):
        p = json.loads(f.read_text())
        missing = [k for k in REQUIRED if not p.get(k)]
        assert not missing, f"{f}: missing {missing}"
        assert all(s.get("title") and s.get("body") for s in p["steps"]), f"{f}: every step needs title + body"
        p["slug"] = f.parent.name
        p["loops"], p["aspect"] = tile_media(f.parent, p)
        assert p.get("cover") == "cover.jpg" and (f.parent / "cover.jpg").exists(), \
            f"{f}: every project needs \"cover\": \"cover.jpg\" and the file next to project.json (it is the record sleeve)"
        assert not p.get("frozen") or p["slug"] in FROZEN_OK, \
            f"{f}: new projects can't be frozen; they use the standard case-study format"
        bad = [t for t in OWN_STYLING for v in text_fields(p) if t in v.lower()]
        assert not bad, f"{f}: text fields can't carry their own styling or scripts ({', '.join(sorted(set(bad)))}); theme.css sets the look"
        if not p["loops"]:
            print(f"warning: {p['slug']} has no motion tile yet (loop.mp4/loop.webm); every project should get one, see CLAUDE.md")
        p["gh"] = gh.get(GH_ALIAS.get(p["slug"], p["slug"]))
        projects.append(p)
    # newest first; "order" breaks ties / pins
    return sorted(projects, key=lambda p: (p["date"], -p.get("order", 0)), reverse=True)


# ---- text contrast ------------------------------------------------------------------------------------------
# Readable text must clear WCAG AA (4.5:1) on the paper. theme.css keeps --faint, --wood and --accent for decorative marks;
# a case-study footer shipped in --faint at 1.95:1, so the build refuses page CSS that sets a text `color:` to any token
# under 4.5:1 against --paper. (--paper/--ink are allowed: ink is the text colour on the hot button. ::marker is decoration.)
def contrast(a, b):
    def lum(h):
        c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def low_contrast_text():
    css = (ROOT / "theme.css").read_text() + (ROOT / "site.css").read_text()   # site.css defines its own tokens now
    tokens = dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})\b", css))
    aliases = dict(re.findall(r"--([\w-]+):\s*var\(--([\w-]+)\)", css))     # semantic -> primitive chains

    def resolve(tok, depth=0):
        return tokens.get(tok) if tok in tokens or depth > 8 else resolve(aliases.get(tok, ""), depth + 1)
    paper = resolve("paper")
    bad = []
    for name in ("site.css",):   # portfolio.css (the fog environment) is checked from computed styles by tests/portfolio-check.cjs
        for sel, decls in re.findall(r"([^{}]+)\{([^{}]*)\}", (ROOT / name).read_text()):
            if "::marker" in sel:
                continue
            for tok in re.findall(r"(?<![-\w])color:\s*var\(--([\w-]+)\)", decls):
                hexv = resolve(tok)
                if hexv and tok not in ("paper", "ink", "sheet", "s-canvas", "s-text-inverse", "p-color-white") and contrast(hexv, paper) < 4.5:
                    bad.append(f"{name}: {sel.strip()[-60:]} uses --{tok} ({contrast(hexv, paper):.2f}:1)")
    return bad


def asset_version(name):
    """?v=<hash of the file>: a changed stylesheet or script gets a new URL, so browsers never use a stale cached copy."""
    return hashlib.sha1((ROOT / name).read_bytes()).hexdigest()[:10]


def page(title, desc, body):
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="{escape(desc)}">
<title>{escape(title)}</title>
<meta name="theme-color" content="#07070c">
<link rel="preload" as="font" type="font/woff2" href="../vendor/fonts/Bricolage-latin.woff2" crossorigin>
<link rel="stylesheet" href="../site.css?v={asset_version("site.css")}">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' fill='%2307070c'/%3E%3Crect x='7' y='9' width='18' height='14' fill='%23ff4d00'/%3E%3C/svg%3E">
<script src="../case.js?v={asset_version("case.js")}" defer></script>
</head>
<body>
{body}
</body>
</html>
"""


def featured():
    """featured.json by slug: the four flagships whose printed object opens their case study."""
    return {f["slug"]: f for f in json.loads((ROOT / "featured.json").read_text())}


def project_page(p, nxt):
    steps = []
    for i, s in enumerate(p["steps"], 1):
        code = f'<pre><code>{escape(s["code"])}</code></pre>' if s.get("code") else ""
        steps.append(f'<li><span class="n">{i:02d}</span><div><h3>{escape(s["title"])}</h3>{s["body"]}{code}</div></li>')
    links = [f'<a href="{escape(p["repo"])}" target="_blank" rel="noopener">Code on GitHub &#8599;</a>']
    if p.get("demo"):
        links.insert(0, f'<a href="{escape(p["demo"])}">{escape(p.get("demo_label", "See it"))} &#8599;</a>')
    cover = (f'<figure class="cover"><img src="{escape(p["cover"])}" srcset="cover-800.webp 800w, {escape(p["cover"])} 1400w" sizes="(max-width: 900px) calc(100vw - 40px), 1068px" alt="Screenshot of {escape(p["title"])}" width="1400" height="{round(1400 / (p.get("aspect") or 1.75))}" fetchpriority="high" decoding="async"></figure>'
             if p.get("cover") else "")
    note = f'<p class="note">{p["note"]}</p>' if p.get("note") else ""
    feat = featured().get(p["slug"])
    obj = ""
    home = f"../#feature-{p['slug']}" if feat else "../"
    g = p.get("gh")
    facts = ""
    if g:
        langs = sorted(g.get("languages", {}).items(), key=lambda kv: -kv[1])
        tot = sum(v for _, v in langs) or 1
        lang_s = ", ".join(f"{k} {round(100 * v / tot)}%" for k, v in langs[:3])
        pages = f'<a href="{escape(g["homepage"])}" target="_blank" rel="noopener">{escape(g["homepage"].replace("https://", ""))}</a>' if g.get("homepage") else ""
        topics = ", ".join(escape(t) for t in g.get("topics", [])[:6])
        facts = ('<dl class="facts-strip" aria-label="From the repository">'
                 f'<div><dt>Repository</dt><dd><a href="{escape(p["repo"])}" target="_blank" rel="noopener">github.com/mrrishit909/{escape(g["name"])}</a></dd></div>'
                 f'<div><dt>Commits</dt><dd>{g["commits"]}</dd></div>'
                 f'<div><dt>Last push</dt><dd>{g["pushed_at"][:10]}</dd></div>'
                 f'<div><dt>Created</dt><dd>{g["created_at"][:10]}</dd></div>'
                 f'<div><dt>Languages</dt><dd>{escape(lang_s) if lang_s else escape(g.get("language") or "")}</dd></div>'
                 + (f'<div><dt>Live</dt><dd>{pages}</dd></div>' if pages else "")
                 + (f'<div><dt>Topics</dt><dd>{topics}</dd></div>' if topics else "")
                 + (f'<div><dt>Licence</dt><dd>{escape(g["license"])}</dd></div>' if g.get("license") else "")
                 + '</dl>')
    field = ' class="is-flagship"' if feat else ""
    # the next project's motion tile, played by case.js while the link is on screen
    peek = ("".join([f'<video muted loop playsinline preload="none" aria-hidden="true" poster="../{nxt["slug"]}/cover-800.webp">' if nxt.get("cover") else
                     '<video muted loop playsinline preload="none" aria-hidden="true">'] +
                    [f'<source src="../{nxt["slug"]}/{f}" type="video/{f.split(".")[1]}">' for f in sorted(nxt["loops"], reverse=True)] + ["</video>"])
            if nxt.get("loops") else "")
    sections = [("The problem", p["problem"]), ("What I built", p["built"]),
                ("How it was built", f'<ol class="steps">{"".join(steps)}</ol>'),
                ("Results", p["results"]), ("What I'd do next", p["next"])]
    ids = ["problem", "built", "how", "results", "next-steps"]
    secs = "".join(f'<section class="s" id="{ids[n - 1]}"><h2 class="cap">{n:02d} / {escape(t)}</h2><div class="body">{b}</div></section>'
                   for n, (t, b) in enumerate(sections, 1))
    body = f"""<header class="bar"><a href="{PORTFOLIO}">Rishit Raj Mathur</a><nav><a href="{home}">Home</a><a href="../all.html">Index</a><a href="{PORTFOLIO}resume.pdf">Résumé</a></nav></header>
<main class="wrap">
  <div class="hero"{field}>
    <p class="cap dim"><span>{escape(p["kind"])}</span> &middot; {escape(p["date"])}</p>
    <h1>{escape(p["title"])}</h1>
    <p class="tagline">{escape(p["tagline"])}</p>
    <div class="meta cap"><span class="tech">{" &middot; ".join(escape(t) for t in p["tech"])}</span><span class="links">{"".join(links)}</span></div>
  </div>
  {cover}
  {facts}
  {note}
  {secs}
  <a class="next" href="../{nxt["slug"]}/"><span class="cap">Next project</span><span class="t">{escape(nxt["title"])} &rarr;</span>{peek}</a>
</main>
<footer class="cap"><span>&copy; 2026 Rishit Raj Mathur</span><a href="https://github.com/mrrishit909">GitHub</a></footer>"""
    return page(f'{p["title"]} · Rishit Mathur', p["tagline"], body)


def demo_url(p):
    d = p.get("demo")
    return d if not d or d.startswith("http") else f'{p["slug"]}/{d}'


def unit_split(sc):
    """'75.5', '%' / '31', 'of 31': the big number and its smaller unit."""
    return f"{sc['value']:g}", sc["unit"].strip()


def home_page(projects):
    """The home (index.template.html + portfolio.css + home.js): a rendered world. Every case study is one screen in a tower
    (assets/atlas/atlas.json, built by tools/atlas.py from the thumbnails); the four flagships from featured.json each get a
    scene; the repository inventory supplies the live counts."""
    by_slug = {p["slug"]: p for p in projects}
    gh = github()
    atlas = json.loads((ROOT / "assets" / "atlas" / "atlas.json").read_text())
    feats, scenes = [], []
    for i, f in enumerate(json.loads((ROOT / "featured.json").read_text()), 1):
        p, sc = by_slug[f["slug"]], f["scale"]
        big, unit = unit_split(sc)
        line = f["result"].split(". ")[0].rstrip(".") + "."
        links = [f'<a class="btn btn-fill" href="{p["slug"]}/">Read the case study</a>', f'<a class="btn" href="{escape(p["repo"])}" target="_blank" rel="noopener">Code</a>']
        if p.get("demo"):
            links.append(f'<a class="btn" href="{escape(demo_url(p))}">{escape(p.get("demo_label", "Demo"))}</a>')
        side = "right" if i % 2 else "left"   # the screen hangs on the left wall for odd rooms, so the copy sits right
        feats.append(
            f'<section class="scene card" data-cam="card" data-n="{i}" aria-hidden="true"><div class="scene-in">'
            f'<p class="mono meta"><span>{i:02d} / 04</span><span>{escape(f["area"])}</span></p>'
            f'<p class="display card-line">{escape(f["card"])}</p></div></section>'
            f'<section class="scene room" id="feature-{p["slug"]}" data-cam="room" data-n="{i}" data-side="{side}" data-slug="{p["slug"]}" data-value="{sc["value"]}" data-unit="{escape(sc["unit"], quote=True)}" '
            f'data-title="{escape(p["title"], quote=True)}" aria-labelledby="t-{p["slug"]}">'
            f'<div class="scene-in">'
            f'<p class="mono meta"><span>{i:02d} / 04</span><span>{escape(f["area"])}</span><span>{escape(sc["metric"])}</span></p>'
            f'<p class="num mono"><span class="num-v">{big}</span><span class="num-u">{escape(unit)}</span></p>'
            f'<h2 class="display">{escape(f["word"])}</h2>'
            f'<div class="copy"><h3 id="t-{p["slug"]}"><a href="{p["slug"]}/">{escape(p["title"])}</a></h3><p class="line">{line}</p>'
            f'<p class="mono small">{escape(sc["note"])}</p><p class="btns">{"".join(links)}</p></div>'
            f'<img class="still" src="{p["slug"]}/cover-800.webp" alt="Screenshot of {escape(p["title"], quote=True)}" width="{webp_size(ROOT / p["slug"] / "cover-800.webp")[0]}" height="{webp_size(ROOT / p["slug"] / "cover-800.webp")[1]}" loading="lazy" decoding="async">'
            f'</div></section>')
        scenes.append(f'<script src="motion/scenes/{p["slug"]}.js?v={asset_version("motion/scenes/" + p["slug"] + ".js")}" defer></script>')
    commits = sum(r["commits"] for r in gh.values())
    last = max((r["pushed_at"][:10] for r in gh.values()), default="")
    tpl = (ROOT / "index.template.html").read_text()
    assert "{{FEATURED}}" in tpl and "{{SCENES}}" in tpl and "/*ATLAS*/{}" in tpl
    return (tpl.replace("{{FEATURED}}", "".join(feats)).replace("{{SCENES}}", "".join(scenes)).replace("{{COUNT}}", str(len(projects))).replace("{{REPOS}}", str(len(gh)))
               .replace("{{COMMITS}}", f"{commits:,}").replace("{{LAST_PUSH}}", last).replace("{{PAGES}}", str(sum(1 for r in gh.values() if r.get("homepage"))))
               .replace("/*ATLAS*/{}", json.dumps(atlas, separators=(",", ":")).replace("</", "<\\/"))
               .replace("{{PORTFOLIO_CSS}}", asset_version("portfolio.css")).replace("{{HOME_JS}}", asset_version("home.js")))


def webp_size(path):
    """(width, height) of a .webp (VP8X / VP8 / VP8L)."""
    d = path.read_bytes()
    kind = d[12:16]
    if kind == b"VP8X":
        return 1 + int.from_bytes(d[24:27], "little"), 1 + int.from_bytes(d[27:30], "little")
    if kind == b"VP8L":
        bits = int.from_bytes(d[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    w, h = struct.unpack("<HH", d[26:30])
    return w & 0x3FFF, h & 0x3FFF


def all_page(projects):
    """all.html (all.template.html + portfolio.css + catalog.js): every project as a real link with its thumbnail
    (assets/thumbs/<slug>.webp, made by tools/thumbs.py), plus search, the kind filter and the data the detail dialog reads."""
    order = {p["slug"]: i + 1 for i, p in enumerate(projects)}
    heads = Counter(p["kind"].split("\u00b7")[0].strip() for p in projects)
    tiles = []
    for n, p in enumerate(projects):
        head = p["kind"].split("\u00b7")[0].strip()
        search = escape(" ".join([p["title"], p["kind"], *p["tech"]]).lower(), quote=True)
        if (ROOT / "assets" / "thumbs" / f'{p["slug"]}.webp').exists():
            src, attrs = f'assets/thumbs/{p["slug"]}.webp', 'alt="" width="880" height="503"'
            if n < 3:   # the first row is above the fold: loads at once
                thumb = f'<img class="tile-thumb" src="{src}" {attrs}{" fetchpriority=\"high\"" if n == 0 else ""}>'
            else:       # the rest start after the page has loaded (catalog.js), so they never compete with the first paint
                thumb = f'<img class="tile-thumb" data-src="{src}" {attrs} loading="lazy" decoding="async"><noscript><img class="tile-thumb" src="{src}" {attrs} loading="lazy"></noscript>'
        else:
            print(f'warning: {p["slug"]} has no thumbnail yet (run python3 tools/thumbs.py)')
            thumb = '<span class="tile-thumb" aria-hidden="true"></span>'
        g = p.get("gh") or {}
        lang, commits, year = g.get("language") or "", g.get("commits") or 0, p["date"][:4]
        tiles.append(f'<li class="tile" data-slug="{p["slug"]}" data-kind="{escape(head, quote=True)}" data-lang="{escape(lang, quote=True)}" data-year="{year}" data-commits="{commits}" data-live="{"1" if (p.get("demo") or g.get("homepage")) else "0"}" data-search="{search}">'
                     f'<a class="tile-link" href="{p["slug"]}/">{thumb}<span class="tile-no mono">{order[p["slug"]]:03d}</span>'
                     f'<span class="tile-title">{escape(p["title"])}</span><span class="tile-kind">{escape(p["kind"])}</span>'
                     f'<span class="tile-gh mono">{escape(lang)} · {year} · {commits} commits</span></a></li>')
    keys = ("slug", "title", "kind", "date", "cover", "tagline", "tech", "repo", "demo", "demo_label")
    data = []
    for p in projects:
        d = {k: p.get(k) for k in keys if p.get(k) is not None}
        g = p.get("gh")
        if g: d["gh"] = {"language": g.get("language"), "commits": g.get("commits"), "pushed": g.get("pushed_at", "")[:10], "homepage": g.get("homepage"), "topics": g.get("topics", [])}
        data.append(d)
    kinds = ", ".join(escape(k) for k, _ in heads.most_common(5))
    options = "".join(f'<option value="{escape(k, quote=True)}">{escape(k)} ({n})</option>' for k, n in heads.most_common())
    tabs = "".join(f'<button class="kind-tab" type="button" data-kind="{escape(k, quote=True)}" aria-pressed="false">{escape(k)}</button>' for k, _ in heads.most_common(5))
    tpl = (ROOT / "all.template.html").read_text()
    assert "{{CATALOG}}" in tpl and "/*DATA*/[]" in tpl
    return (tpl.replace("{{CATALOG}}", "".join(tiles)).replace("/*DATA*/[]", json.dumps(data).replace("</", "<\\/"))
               .replace("{{COUNT}}", str(len(projects))).replace("{{REPOS}}", str(len(github()))).replace("{{KINDS_OPTIONS}}", options).replace("{{KINDS_TABS}}", tabs).replace("{{KINDS}}", kinds)
               .replace("{{PORTFOLIO_CSS}}", asset_version("portfolio.css")).replace("{{CATALOG_JS}}", asset_version("catalog.js")))


if __name__ == "__main__":
    bad = low_contrast_text()
    assert not bad, "text under 4.5:1 on the paper (use --muted or darker; see theme.css):\n  " + "\n  ".join(bad)
    projects = load()
    for i, p in enumerate(projects):
        if p.get("frozen"):   # page kept exactly as published; its old style.css stays too
            continue
        (ROOT / p["slug"] / "index.html").write_text(project_page(p, projects[(i + 1) % len(projects)]))
    (ROOT / "index.html").write_text(home_page(projects))
    (ROOT / "all.html").write_text(all_page(projects))
    nfrozen = sum(bool(p.get("frozen")) for p in projects)
    print(f"built {len(projects) - nfrozen} project pages (+{nfrozen} frozen) + index.html + all.html")
