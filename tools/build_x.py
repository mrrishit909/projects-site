#!/usr/bin/env python3
"""ATELIER X: writes x/p/<slug>/index.html (every case study) and x/work/index.html (the Work index)
from every <slug>/project.json. Standard library only. Run from the repo root: python3 tools/build_x.py
Refuses to write anything if a project lacks a title or tagline."""
import html
import json
import posixpath
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
X = ROOT / "x"
esc = html.escape


def nodash(s):
    """The site never prints en or em dashes: ranges become hyphens, asides become commas."""
    en, em = chr(0x2013), chr(0x2014)
    s = s.replace("&" + "ndash;", en).replace("&" + "mdash;", em)
    s = re.sub(r"\s*" + em + r"\s*", ", ", s)
    return s.replace(en, "-")


def plain(frag, n=None):
    t = html.unescape(re.sub(r"<[^>]+>", "", frag))
    t = re.sub(r"\s+", " ", t).strip()
    if n and len(t) > n:
        t = t[:n].rsplit(" ", 1)[0] + "…"
    return nodash(t)


def load():
    projects, bad = [], []
    for f in sorted(ROOT.glob("*/project.json")):
        p = json.loads(f.read_text())
        p["slug"] = f.parent.name
        if not p.get("title") or not p.get("tagline"):
            bad.append(p["slug"])
        d = f.parent
        p["webm"] = (d / "loop.webm").exists()
        p["mp4"] = (d / "loop.mp4").exists()
        p["has_cover"] = (d / "cover.jpg").exists()
        p["thumb"] = "cover-800.webp" if (d / "cover-800.webp").exists() else "cover.jpg"
        projects.append(p)
    if bad:
        sys.exit(f"refusing to write: no title/tagline in {', '.join(bad)}")
    projects.sort(key=lambda p: (p.get("date", ""), -p.get("order", 0)), reverse=True)
    return projects


def group(kind):
    return (kind or "Other").split("·")[0].strip() or "Other"


def year(p):
    return (p.get("date") or "")[:4] or "n/a"


def status(p):
    return "Archived" if p.get("frozen") else "Has demo" if p.get("demo") else "Code only"


SLUGS = set()


def fix_urls(frag, slug):
    """Fragments are written relative to <slug>/; from x/p/<slug>/ they need ../../../<slug>/.
    Links to another project's folder go to that project's page here instead."""
    def sub(m):
        attr, u = m.group(1), m.group(2)
        if re.match(r"^(https?:|mailto:|#|data:|//)", u):
            return m.group(0)
        if u.startswith("../"):
            other = u[3:].split("/")[0]
            if other in SLUGS and u[3 + len(other):] in ("", "/"):
                return f'{attr}="../{other}/"'
            return f'{attr}="{posixpath.normpath("../../../" + slug + "/" + u)}"'
        return f'{attr}="../../../{slug}/{u}"'
    frag = re.sub(r'\b(src|href)="([^"]*)"', sub, frag)
    frag = re.sub(r"<img(?![^>]*loading=)", '<img loading="lazy" decoding="async"', frag)
    frag = re.sub(r'<a (?=[^>]*href="https?:)(?![^>]*target=)', '<a target="_blank" rel="noopener" ', frag)
    return frag


def asset(slug, name, root="../../../"):
    return f"{root}{slug}/{name}"


def media(p, root, title, eager=False):
    """The project's loop in a screen; its cover where it has no loop. The hero (eager) shows the small poster
    first; every loop starts after window load, once in view (CASE_JS), so posters are the LCP and nothing competes with them.
    A loop's poster is the small cover-800 (the loop replaces it); a still keeps the full cover.jpg."""
    s = p["slug"]
    loop = p["webm"] or p["mp4"]
    label = f"{title}: the project's animated loop" if loop else f"{title}: screenshot of the project"
    poster = asset(s, p["thumb"] if loop else "cover.jpg", root)
    if loop:
        srcs = ""
        if p["webm"]:
            srcs += f'<source src="{asset(s, "loop.webm", root)}" type="video/webm">'
        if p["mp4"]:
            srcs += f'<source src="{asset(s, "loop.mp4", root)}" type="video/mp4">'
        return (f'<video muted loop playsinline preload="none" poster="{poster}" '
                f'width="1162" height="720" aria-label="{esc(label)}">{srcs}</video>')
    return f'<img src="{poster}" alt="{esc(label)}" width="1400" height="868"{" fetchpriority=\"high\"" if eager else " loading=\"lazy\""} decoding="async">'


def header(root, current):
    nav = [("work/", "Work"), ("about/", "About"), ("contact/", "Contact")]
    links = "".join(f'<a href="{root}{h}"{" aria-current=\"page\"" if t == current else ""}>{t}</a>' for h, t in nav)
    return (f'<a class="skip" href="#main">Skip to content</a>\n'
            f'<header class="top"><a class="logo" href="{root}">Rishit Mathur</a><nav aria-label="Primary">{links}'
            f'<button class="sound keep" type="button" aria-pressed="false"><i><b></b><b></b><b></b></i><span class="lbl">Sound off</span></button></nav></header>')


def footer(root):
    return (f'<footer class="site-foot"><span>&copy; 2026 Rishit Raj Mathur, Tampa, FL</span><nav aria-label="Footer">'
            f'<a href="{root}work/">Work</a><a href="https://github.com/mrrishit909" rel="noopener" target="_blank">GitHub</a>'
            f'<a href="https://www.linkedin.com/in/rishitrajmathur" rel="noopener" target="_blank">LinkedIn</a></nav></footer>\n'
            f'<canvas class="stars" aria-hidden="true"></canvas>\n<script type="module" src="{root}x.js"></script>')


def doc(title, desc, image, root, style, body, script="", preload=""):
    return nodash(f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<meta property="og:type" content="website">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
{f'<meta property="og:image" content="{image}">' if image else ''}
<meta name="theme-color" content="#000000">
<script>document.documentElement.classList.add("js")</script>
<link rel="icon" href="{root}favicon.svg" type="image/svg+xml">
<link rel="preload" as="font" type="font/woff2" href="{root}../vendor/fonts/InterTight-latin.woff2" crossorigin>
{preload}<link rel="stylesheet" href="{root}x.css">
<style>body::before {{ content: ""; position: fixed; left: 0; right: 0; top: 0; height: 84px; z-index: 25; pointer-events: none; background: linear-gradient(#000 35%, rgba(0,0,0,0)); }}{style}</style>
</head>
<body>
{body}
{script}
</body>
</html>
""")


# ---------------------------------------------------------------------------------------------- case study
CASE_CSS = """
.screen.chroma { box-shadow: -1px 0 0 rgba(255,70,90,.45), 1px 0 0 rgba(70,210,255,.5), 0 0 0 1px rgba(0,0,0,.6), 0 0 60px -12px rgba(47,143,230,.55), 0 30px 120px -40px rgba(47,143,230,.5); }
.screen .hud { position: absolute; z-index: 2; left: 14px; right: 14px; display: flex; justify-content: space-between; gap: 12px; font: 400 var(--fs-hud)/1 var(--mono); letter-spacing: .14em; text-transform: uppercase; color: rgba(255,255,255,.75); text-shadow: 0 0 8px #000; pointer-events: none; }
.screen .hud.t { top: 14px; } .screen .hud.b { bottom: 14px; }
.screen .hud .live::before { content: ""; display: inline-block; width: 6px; height: 6px; margin-right: 8px; border-radius: 50%; background: var(--blue); box-shadow: 0 0 8px var(--blue); animation: blink 1.6s steps(2) infinite; }
@keyframes blink { 50% { opacity: .25; } }
.corner { position: absolute; width: 14px; height: 14px; border: 1px solid var(--blue-hi); z-index: 2; pointer-events: none; }
.corner.a { left: -7px; top: -7px; border-width: 1px 0 0 1px; } .corner.b { right: -7px; top: -7px; border-width: 1px 1px 0 0; }
.corner.c { left: -7px; bottom: -7px; border-width: 0 0 1px 1px; } .corner.d { right: -7px; bottom: -7px; border-width: 0 1px 1px 0; }
.frame { position: relative; }
.hero { padding-top: 4vh; }
.hero .crumb { display: flex; justify-content: space-between; gap: 16px; flex-wrap: wrap; color: var(--w60); margin-bottom: 7vh; }
.hero .crumb a { color: var(--w60); text-decoration: none; } .hero .crumb a:hover { color: var(--white); }
.hero .crumb .n { color: var(--white); }
.hero .h1 { font-size: clamp(2.6rem, 1.2rem + 4.6vw, 6.4rem); max-width: 15ch; padding-bottom: .14em; text-wrap: balance; }
.hero .lead { max-width: 46ch; margin: 28px 0 0; }
.hero .meta { display: grid; grid-template-columns: 1fr auto; gap: 32px; align-items: end; margin-top: 48px; padding-top: 22px; border-top: 1px solid var(--w10); }
.hero .links { display: flex; gap: 10px; flex-wrap: wrap; justify-content: flex-end; }
a.brk { text-decoration: none; transition: border-color var(--t-fast), color var(--t-fast), background var(--t-fast); }
a.brk:hover, a.brk:focus-visible { border-color: var(--blue-hi); color: var(--white); background: rgba(47,143,230,.12); outline: none; }
a.brk.go { color: var(--white); border-color: rgba(159,208,255,.5); }
.hero .frame { margin-top: 9vh; }
.stack { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 18px; }
.chapters { margin-top: 18vh; }
.ch { display: grid; grid-template-columns: minmax(0, 4fr) minmax(0, 8fr); gap: 40px; padding: 9vh 0; border-top: 1px solid var(--w10); }
.ch .side { position: sticky; top: 110px; align-self: start; }
.ch .side .mono { color: var(--blue-hi); display: block; margin-bottom: 18px; }
.ch .side .h3 { max-width: 12ch; }
.ch .body { min-width: 0; }
.ch .prose { font-size: 1.06rem; line-height: 1.65; overflow-wrap: anywhere; }
.ch .prose > :first-child { margin-top: 0; }
.prose img { width: 100%; height: auto; margin: 28px 0; border: 1px solid rgba(159,208,255,.22); background: #07090c; }
.prose ul { padding-left: 1.1em; } .prose li::marker { color: var(--blue); }
.prose em { color: var(--white); font-style: italic; }
.prose table { margin: 20px 0; display: block; max-width: 100%; overflow-x: auto; }
.prose th { color: var(--w60); }
pre { margin: 18px 0 0; padding: 18px 20px; overflow-x: auto; max-width: 100%; background: #05070a; border: 1px solid var(--w10); border-left: 1px solid var(--blue); font: 400 12.5px/1.6 var(--mono); color: var(--blue-hi); }
.steps { list-style: none; margin: 0; padding: 0; counter-reset: s; }
.steps li { display: grid; grid-template-columns: 64px minmax(0, 1fr); gap: 8px 20px; padding: 30px 0; border-top: 1px solid var(--w06); }
.steps li > * { min-width: 0; }
.steps li:first-child { border-top: 0; padding-top: 0; }
.steps .k { color: var(--w60); padding-top: 6px; }
.steps h3 { margin: 0 0 12px; font-weight: 300; font-size: 1.35rem; line-height: 1.2; letter-spacing: -.01em; }
.note { margin-top: 9vh; padding: 26px 28px; border: 1px solid var(--w10); background: rgba(255,255,255,.02); display: grid; grid-template-columns: minmax(0, 4fr) minmax(0, 8fr); gap: 40px; }
.note .mono { color: var(--w60); }
.note p { margin: 0; color: var(--w60); max-width: 68ch; }
.next { margin-top: 20vh; }
.next a { display: block; text-decoration: none; }
.next .top-line { display: flex; justify-content: space-between; gap: 16px; color: var(--w60); margin-bottom: 26px; }
.next .h2 { font-size: clamp(2.4rem, 1rem + 4.4vw, 6rem); line-height: .98; max-width: 16ch; margin-bottom: 6vh; text-wrap: balance; transition: letter-spacing var(--t-slow) var(--ease-out); }
.next a:hover .h2 { letter-spacing: -.045em; }
.next .screen { transition: transform var(--t-slow) var(--ease-out); }
.next a:hover .screen { transform: scale(.985); }
.next .sub { display: flex; justify-content: space-between; gap: 16px; margin-top: 18px; color: var(--w60); }
.readhud { position: fixed; left: var(--pad); bottom: var(--pad); z-index: 20; display: flex; gap: 22px; font: 400 var(--fs-hud)/1 var(--mono); letter-spacing: .14em; text-transform: uppercase; color: var(--w60); mix-blend-mode: difference; pointer-events: none; opacity: 0; transition: opacity .4s; }
.readhud b { color: var(--white); font-weight: 400; font-variant-numeric: tabular-nums; }
.readhud.on { opacity: 1; }
@media (max-width: 900px) {
  .ch, .note { grid-template-columns: 1fr; gap: 22px; }
  .ch .side { position: static; }
  .ch .side .h3 { max-width: none; }
  .hero .meta { grid-template-columns: 1fr; gap: 24px; }
  .hero .links { justify-content: flex-start; }
}
@media (max-width: 560px) {
  .hero .crumb { margin-bottom: 5vh; }
  .hero .crumb .k { display: none; }
  .hero .frame { margin-top: 6vh; }
  .corner { width: 10px; height: 10px; }
  .corner.a, .corner.c { left: -5px; } .corner.b, .corner.d { right: -5px; } .corner.a, .corner.b { top: -5px; } .corner.c, .corner.d { bottom: -5px; }
  .screen .hud { font-size: 9px; left: 10px; right: 10px; } .screen .hud.t { top: 10px; } .screen .hud.b { bottom: 10px; }
  .screen .hud .x { display: none; }
  .chapters { margin-top: 12vh; }
  .ch { padding: 7vh 0; }
  .ch .prose { font-size: 1rem; }
  .steps li { grid-template-columns: minmax(0, 1fr); padding: 24px 0; }
  .steps .k { padding: 0; }
  .note { padding: 20px; }
  .next { margin-top: 14vh; }
  .readhud { gap: 14px; }
  .readhud .c { display: none; }
}
"""

CASE_JS = """<script type="module">
const hud = document.querySelector(".readhud"), pct = hud.querySelector(".p"), chn = hud.querySelector(".c b");
const chs = [...document.querySelectorAll(".ch")];
const vids = [...document.querySelectorAll("video")];
if (matchMedia("(prefers-reduced-motion: reduce)").matches) vids.forEach((v) => { v.removeAttribute("autoplay"); v.pause(); });
else {
  const vo = new IntersectionObserver((es) => es.forEach((e) => { const v = e.target; if (e.isIntersecting) { if (v.preload === "none") { v.preload = "auto"; v.load(); } v.play().catch(() => {}); } else v.pause(); }), { rootMargin: "200px 0px" });
  const go = () => vids.forEach((v) => vo.observe(v));
  if (document.readyState === "complete") go(); else addEventListener("load", go, { once: true });
}
let ticking = false;
function upd() {
  ticking = false;
  const max = document.documentElement.scrollHeight - innerHeight, y = scrollY;
  pct.textContent = String(Math.round(max > 0 ? (y / max) * 100 : 0)).padStart(2, "0") + "%";
  let k = 0; chs.forEach((c, i) => { if (c.getBoundingClientRect().top < innerHeight * 0.5) k = i + 1; });
  chn.textContent = String(k).padStart(2, "0");
  hud.classList.toggle("on", y > innerHeight * 0.4 && document.querySelector(".next").getBoundingClientRect().top > innerHeight * 0.7);
}
addEventListener("scroll", () => { if (!ticking) { ticking = true; requestAnimationFrame(upd); } }, { passive: true });
upd();
</script>"""

CHAPTERS = [("problem", "The problem", "What needed answering"), ("built", "What was built", "The build"),
            ("steps", "How it was done", "Step by step"), ("results", "What it found", "Results"),
            ("next", "What comes next", "Next")]


def case_page(p, idx, total, nxt):
    s, root = p["slug"], "../../"
    title = plain(p["title"])
    tech = p.get("tech") or []
    links = [f'<a class="brk" href="{esc(p["repo"])}" target="_blank" rel="noopener" data-cursor="Code">[ Code on GitHub ]</a>'] if p.get("repo") else []
    if p.get("demo"):
        d = p["demo"] if re.match(r"^https?:", p["demo"]) else f'../../../{s}/{p["demo"]}'
        ext = ' target="_blank" rel="noopener"' if d.startswith("http") else ""
        links.insert(0, f'<a class="brk go" href="{esc(d)}"{ext} data-cursor="Open">[ {esc(plain(p.get("demo_label") or "Open the demo"))} ]</a>')
    hud = "".join(f"<span>{k}<b>{esc(v)}</b></span>" for k, v in [
        ("Kind", group(p.get("kind"))), ("Year", year(p)), ("Tools", f"{len(tech):02d}"), ("Status", status(p))])
    playing = "live" if (p["webm"] or p["mp4"]) else ""
    n = f"{idx:03d}"
    chapters, k = [], 0
    for key, lbl, h in CHAPTERS:
        v = p.get(key)
        if not v:
            continue
        k += 1
        if key == "steps":
            items = []
            for j, st in enumerate(v, 1):
                code = f'<pre tabindex="0"><code>{esc(st["code"])}</code></pre>' if st.get("code") else ""
                items.append(f'<li><span class="k mono">Step {j:02d}</span><div><h3>{st.get("title", "")}</h3>'
                             f'<div class="prose">{fix_urls(st.get("body", ""), s)}</div>{code}</div></li>')
            body = f'<ol class="steps">{"".join(items)}</ol>'
        else:
            body = f'<div class="prose">{fix_urls(v, s)}</div>'
        chapters.append(f'<section class="ch rv" id="{key}" aria-labelledby="h-{key}"><div class="side"><span class="mono">{k:02d} / {lbl}</span>'
                        f'<h2 class="h3 grad" id="h-{key}">{h}</h2></div><div class="body">{body}</div></section>')
    note = (f'<aside class="note rv" aria-label="Limitations"><span class="mono">[ Note ]</span><p>{fix_urls(p["note"], s)}</p></aside>'
            if p.get("note") else "")
    stack = "".join(f'<span class="brk">{esc(t)}</span>' for t in tech)
    nt = plain(nxt["title"])
    body = f"""{header(root, "Work")}
<main id="main" class="page">
<article>
<section class="hero wrap" aria-labelledby="title">
  <p class="crumb mono"><a href="../../work/">[ Work ]</a><span class="k">{esc(plain(p.get("kind", "")))}</span><span>Case <span class="n">{n}</span> / {total}</span></p>
  <h1 class="h1 grad" id="title">{esc(title)}</h1>
  <p class="lead">{esc(plain(p["tagline"]))}</p>
  <div class="meta"><div class="hud-row">{hud}</div><div class="links">{"".join(links)}</div></div>
  <div class="frame"><div class="screen chroma">{media(p, "../../../", title, eager=True)}
    <div class="hud t"><span class="{playing}">{"Running" if playing else "Still"}</span><span class="x">{esc(s)}{"/loop.webm" if p["webm"] else "/cover.jpg"}</span></div>
    <div class="hud b"><span>[{n}]</span><span class="x">1162 x 720</span></div></div>
    <i class="corner a"></i><i class="corner b"></i><i class="corner c"></i><i class="corner d"></i></div>
  <div class="stack" aria-label="Tools">{stack}</div>
</section>
<div class="chapters wrap">
{"".join(chapters)}
{note}
</div>
</article>
<section class="next wrap rv" aria-labelledby="h-next-project">
  <a href="../{nxt["slug"]}/" data-cursor="Next">
    <p class="top-line mono"><span>Next project</span><span>Case {nxt["_i"]:03d} / {total}</span></p>
    <h2 class="h2 grad" id="h-next-project">{esc(nt)}</h2>
    <div class="screen chroma">{media(nxt, "../../../", nt)}</div>
    <p class="sub mono"><span>{esc(plain(nxt.get("kind", "")))}</span><span>{year(nxt)}</span></p>
  </a>
</section>
</main>
<div class="readhud" aria-hidden="true"><span>Case <b>{n}</b></span><span class="c">Chapter <b>00</b> / {k:02d}</span><span>Read <b class="p">00%</b></span></div>
{footer(root)}"""
    desc = plain(p["tagline"], 300)
    pre = f'<link rel="preload" as="image" href="../../../{s}/{p["thumb"] if p["webm"] or p["mp4"] else "cover.jpg"}" fetchpriority="high">\n'
    return doc(f"{title}, Rishit Mathur", desc, f"../../../{s}/cover.jpg" if p["has_cover"] else "", root, CASE_CSS, body, CASE_JS, pre)


# ---------------------------------------------------------------------------------------------- work index
WORK_CSS = """
.head { display: grid; grid-template-columns: 1fr auto; align-items: end; gap: 32px; padding-top: 6vh; }
.head .h1 { font-size: clamp(4.2rem, 2rem + 9vw, 11rem); line-height: .86; letter-spacing: -.05em; }
.head .h1 sup { font: 400 clamp(12px, .7rem + .4vw, 15px)/1 var(--mono); letter-spacing: .12em; vertical-align: top; margin-left: .5em; -webkit-text-fill-color: var(--blue-hi); position: relative; top: .9em; }
.head .lead { max-width: 34ch; margin: 0 0 .6em; }
.head .hud-row { grid-column: 1 / -1; padding-top: 20px; border-top: 1px solid var(--w10); }
.tools { position: sticky; top: 0; z-index: 26; margin-top: calc(9vh - 76px); padding: 76px 0 18px; background: #000; }
.tools::after { content: ""; position: absolute; left: 0; right: 0; top: 100%; height: 36px; background: linear-gradient(#000, rgba(0,0,0,0)); pointer-events: none; }
.bar { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 18px; align-items: center; }
.search { position: relative; display: flex; align-items: center; gap: 12px; border-bottom: 1px solid var(--w20); transition: border-color var(--t-med); }
.search:focus-within { border-color: var(--blue-hi); }
.search label { color: var(--w60); white-space: nowrap; }
.search input { flex: 1; min-width: 0; background: none; border: 0; color: var(--white); font: 300 clamp(1.2rem, 1rem + .8vw, 1.7rem)/1 var(--sans); padding: 14px 0; outline: none; }
.search input::placeholder { color: var(--w40); }
.search input::-webkit-search-cancel-button { display: none; }
.views { display: flex; border: 1px solid var(--w20); }
.views button { background: none; border: 0; color: var(--w60); font: 400 var(--fs-hud)/1 var(--mono); letter-spacing: .14em; text-transform: uppercase; padding: 10px 14px; cursor: pointer; }
.views button[aria-pressed="true"] { background: var(--white); color: #000; }
.chips { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 14px; }
.chips button { background: none; border: 1px solid var(--w20); color: var(--w60); font: 400 var(--fs-hud)/1 var(--mono); letter-spacing: .14em; text-transform: uppercase; padding: 8px 10px; cursor: pointer; transition: border-color var(--t-fast), color var(--t-fast), background var(--t-fast); }
.chips button sup { color: var(--w60); margin-left: 6px; font-size: 9px; vertical-align: 0; }
.chips button:hover { border-color: var(--w60); color: var(--white); }
.chips button[aria-pressed="true"] { border-color: var(--blue-hi); color: var(--white); background: rgba(47,143,230,.16); }
.chips button[aria-pressed="true"] sup { color: var(--blue-hi); }
.status { display: flex; justify-content: space-between; gap: 16px; margin-top: 14px; color: var(--w60); }
.status b { color: var(--white); font-weight: 400; }
html:not(.js) .tools-js { display: none; }
#items { list-style: none; margin: 34px 0 0; padding: 0; }
#items li[hidden] { display: none; }
#items a { text-decoration: none; display: block; }
/* list view: an editorial index */
.list li { border-top: 1px solid var(--w10); }
.list li:last-child { border-bottom: 1px solid var(--w10); }
.list a { display: grid !important; grid-template-columns: 64px minmax(0, 6fr) minmax(0, 3fr) 60px; gap: 20px; align-items: baseline; padding: 15px 0; transition: background var(--t-fast), padding var(--t-med) var(--ease-out); }
.list a:hover, .list a:focus-visible { background: rgba(47,143,230,.08); padding-left: 10px; outline: none; }
.list .t { font-size: 1.2rem; font-weight: 300; letter-spacing: -.01em; }
.list a:hover .t { color: var(--white); }
.list .n, .list .k, .list .y { font: 400 var(--fs-hud)/1.4 var(--mono); letter-spacing: .12em; text-transform: uppercase; color: var(--w60); }
.list .y { text-align: right; font-variant-numeric: tabular-nums; }
.list .screen, .list .badge { display: none; }
.list .n { grid-column: 1; grid-row: 1; } .list .t { grid-column: 2; grid-row: 1; } .list .k { grid-column: 3; grid-row: 1; } .list .y { grid-column: 4; grid-row: 1; }
/* screens view */
.screens { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); grid-auto-flow: dense; gap: 56px 26px; }
.screens li.big { grid-column: span 2; grid-row: span 2; }
.screens li.big a { height: 100%; grid-template-rows: minmax(0, 1fr) auto auto; }
.screens li.big .screen { aspect-ratio: auto; height: 100%; min-height: 0; }
.screens li.big .screen img, .screens li.big .screen video { object-position: 0 50%; }
.screens a { display: grid !important; grid-template-columns: auto minmax(0, 1fr) auto; gap: 6px 14px; align-items: baseline; }
.screens .screen { grid-column: 1 / -1; margin-bottom: 12px; transition: transform var(--t-slow) var(--ease-out), box-shadow var(--t-med); }
.screens .screen img { transition: opacity .5s, transform 1.4s var(--ease-out); }
.screens .screen video { position: absolute; inset: 0; opacity: 0; transition: opacity .5s; }
.screens .screen video.on { opacity: 1; }
.screens a:hover .screen, .screens a:focus-visible .screen, .screens li.play .screen { box-shadow: -1px 0 0 rgba(255,70,90,.5), 1px 0 0 rgba(70,210,255,.55), 0 0 0 1px rgba(0,0,0,.6), 0 0 60px -10px rgba(47,143,230,.7); }
.screens a:hover .screen img { transform: scale(1.03); }
.screens a:focus-visible { outline: none; } .screens a:focus-visible .t { text-decoration: underline; text-decoration-color: var(--blue-hi); text-underline-offset: 4px; }
.screens .badge { position: absolute; z-index: 2; left: 10px; top: 10px; font: 400 9px/1 var(--mono); letter-spacing: .14em; text-transform: uppercase; color: rgba(255,255,255,.8); text-shadow: 0 0 6px #000; opacity: 0; transition: opacity .3s; }
.screens .badge::before { content: ""; display: inline-block; width: 5px; height: 5px; border-radius: 50%; margin-right: 7px; background: var(--blue); box-shadow: 0 0 8px var(--blue); }
.screens li.play .badge { opacity: 1; }
.screens .n { font: 400 var(--fs-hud)/1 var(--mono); letter-spacing: .12em; color: var(--blue-hi); }
.screens .t { font-size: 1.05rem; line-height: 1.25; font-weight: 300; letter-spacing: -.01em; }
.screens li.big .t { font-size: clamp(1.15rem, .9rem + .7vw, 1.6rem); }
.screens .y { font: 400 var(--fs-hud)/1 var(--mono); letter-spacing: .12em; color: var(--w60); }
.screens .k { grid-column: 2 / -1; font: 400 12px/1.5 var(--mono); letter-spacing: .12em; text-transform: uppercase; color: var(--w60); }
.empty { padding: 14vh 0 10vh; text-align: center; }
.empty .mono { color: var(--w60); display: block; margin-bottom: 22px; }
.empty .h2 { max-width: 18ch; margin: 0 auto 32px; text-wrap: balance; }
@media (max-width: 1100px) { .screens { grid-template-columns: repeat(2, minmax(0, 1fr)); } .screens li.big { grid-row: auto; } .screens li.big a { height: auto; grid-template-rows: none; } .screens li.big .screen { aspect-ratio: 1.614; height: auto; } }
@media (max-width: 760px) {
  .head { grid-template-columns: 1fr; gap: 20px; }
  .tools { padding-top: 64px; margin-top: 14px; }
  .bar { gap: 12px; }
  .search label { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
  .views button { padding: 10px 11px; }
  .chips { flex-wrap: nowrap; overflow-x: auto; margin-inline: calc(var(--pad) * -1); padding-inline: var(--pad); scrollbar-width: none; }
  .chips::-webkit-scrollbar { display: none; }
  .chips button { flex: none; }
  .screens { grid-template-columns: 1fr; gap: 44px; }
  .screens li.big { grid-column: auto; }
  .list a { grid-template-columns: 44px minmax(0, 1fr) 40px; gap: 4px 12px; padding: 14px 0; }
  .list .k { grid-column: 2 / 3; grid-row: 2; }
  .list .y { grid-row: 1; grid-column: 3; }
  .list .t { font-size: 1.05rem; }
}
"""

WORK_JS = r"""<script type="module">
const data = JSON.parse(document.getElementById("work-data").textContent);
const $ = (s) => document.querySelector(s);
const list = $("#items"), items = [...list.children], input = $("#q"), chips = [...document.querySelectorAll(".chips button")];
const viewBtns = [...document.querySelectorAll(".views button")], count = $("#count"), shown = $("#shown"), empty = $("#empty");
const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches, touch = matchMedia("(hover: none), (pointer: coarse)").matches;
const top8 = new Set(chips.map((c) => c.dataset.kind).filter((k) => k && k !== "Other"));
const hay = data.map((d) => (d.title + " " + d.kind + " " + d.tech.join(" ")).toLowerCase());
let state = { q: "", kind: "", view: "screens" };
function readURL() { const u = new URLSearchParams(location.search); const k = u.get("kind") || ""; state = { q: u.get("q") || "", kind: chips.some((c) => c.dataset.kind === k) ? k : "", view: u.get("view") === "list" ? "list" : "screens" }; }
function writeURL(push) {
  const u = new URLSearchParams(); if (state.q) u.set("q", state.q); if (state.kind) u.set("kind", state.kind); if (state.view !== "screens") u.set("view", state.view);
  const s = u.toString(), url = location.pathname + (s ? "?" + s : "");
  if (url !== location.pathname + location.search) history[push ? "pushState" : "replaceState"](null, "", url);
}
function render() {
  if (input.value !== state.q) input.value = state.q;
  const terms = state.q.toLowerCase().split(/\s+/).filter(Boolean);
  let n = 0, pos = 0;
  items.forEach((li, i) => {
    const d = data[i];
    const okKind = !state.kind || (state.kind === "Other" ? !top8.has(d.group) : d.group === state.kind);
    const ok = okKind && terms.every((t) => hay[i].includes(t));
    li.hidden = !ok;
    if (ok) { n++; li.classList.toggle("big", pos % 10 === 0 || pos % 10 === 7); pos++; } else stopTile(li);
  });
  chips.forEach((c) => c.setAttribute("aria-pressed", String((c.dataset.kind || "") === state.kind)));
  viewBtns.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.view === state.view)));
  list.className = state.view;
  if (state.view === "list") items.forEach(stopTile);
  count.textContent = n; shown.textContent = String(n).padStart(3, "0");
  empty.hidden = n > 0;
  if (!n) $("#empty-q").textContent = [state.q && `"${state.q}"`, state.kind && `in ${state.kind}`].filter(Boolean).join(" ") || "these filters";
  if (touch) observeAll();
}
input.addEventListener("input", () => { state.q = input.value; writeURL(false); render(); });
input.addEventListener("keydown", (e) => { if (e.key === "Escape") { state.q = ""; writeURL(true); render(); } });
input.addEventListener("change", () => writeURL(true));
chips.forEach((c) => c.addEventListener("click", () => { state.kind = c.dataset.kind || ""; writeURL(true); render(); window.xSound?.blip(660); }));
viewBtns.forEach((b) => b.addEventListener("click", () => { state.view = b.dataset.view; writeURL(true); render(); window.xSound?.blip(520); }));
document.querySelectorAll("[data-clear]").forEach((b) => b.addEventListener("click", () => { state.q = ""; state.kind = ""; writeURL(true); render(); input.focus(); }));
addEventListener("popstate", () => { readURL(); render(); });
addEventListener("keydown", (e) => { if (e.key === "/" && document.activeElement !== input) { e.preventDefault(); input.focus(); } });

// loops: made on demand, never 236 videos at once
function playTile(li) {
  if (reduce || list.className !== "screens" || li.hidden) return;
  const d = data[items.indexOf(li)]; if (!d.loop) return;
  const scr = li.querySelector(".screen"); let v = scr.querySelector("video");
  if (!v) {
    v = document.createElement("video"); v.muted = true; v.loop = true; v.playsInline = true; v.setAttribute("muted", ""); v.setAttribute("aria-hidden", "true");
    for (const [f, t] of d.loop) { const s = document.createElement("source"); s.src = `../../${d.slug}/${f}`; s.type = t; v.appendChild(s); }
    v.addEventListener("playing", () => v.classList.add("on"));
    scr.appendChild(v);
  }
  li.classList.add("play"); v.play().catch(() => {});
}
function stopTile(li) { const v = li.querySelector("video"); li.classList.remove("play"); if (v) { v.pause(); v.classList.remove("on"); } }
if (!touch) {
  items.forEach((li) => {
    const a = li.querySelector("a");
    a.addEventListener("pointerenter", () => playTile(li)); a.addEventListener("pointerleave", () => stopTile(li));
    a.addEventListener("focus", () => playTile(li)); a.addEventListener("blur", () => stopTile(li));
  });
}
let io = null; const playing = [];
function observeAll() {
  if (!io) io = new IntersectionObserver((es) => es.forEach((e) => {
    const li = e.target;
    if (e.isIntersecting) { if (!playing.includes(li)) { playing.push(li); playTile(li); } while (playing.length > 4) stopTile(playing.shift()); }
    else { const k = playing.indexOf(li); if (k >= 0) playing.splice(k, 1); stopTile(li); }
  }), { threshold: 0.6 });
  items.forEach((li) => io.observe(li));
}
readURL(); render();
</script>"""


def img_attrs(i):
    """Above the fold on Work: the first tiles load eagerly, the first one first."""
    return ' fetchpriority="high"' if i == 1 else "" if i <= 4 else ' loading="lazy"'


def work_page(projects):
    total = len(projects)
    groups = {}
    for p in projects:
        groups[group(p.get("kind"))] = groups.get(group(p.get("kind")), 0) + 1
    top = sorted(groups.items(), key=lambda kv: (-kv[1], kv[0]))[:8]
    other = total - sum(c for _, c in top)
    chips = [f'<button type="button" data-kind="" aria-pressed="true">All<sup>{total}</sup></button>']
    chips += [f'<button type="button" data-kind="{esc(g)}" aria-pressed="false">{esc(g)}<sup>{c}</sup></button>' for g, c in top]
    if other:
        chips.append(f'<button type="button" data-kind="Other" aria-pressed="false">Other<sup>{other}</sup></button>')
    rows, data = [], []
    for i, p in enumerate(projects, 1):
        s, t = p["slug"], plain(p["title"])
        kind = plain(p.get("kind", ""))
        loop = ([["loop.webm", "video/webm"]] if p["webm"] else []) + ([["loop.mp4", "video/mp4"]] if p["mp4"] else [])
        data.append({"slug": s, "title": t, "kind": kind, "group": group(p.get("kind")), "tech": [plain(x) for x in p.get("tech") or []], "loop": loop})
        big = (i - 1) % 10 in (0, 7)
        rows.append(f'<li{" class=\"big\"" if big else ""}><a href="../p/{s}/" data-cursor="{"Play" if loop else "Open"}">'
                    f'<span class="screen"><img src="../../{s}/{p["thumb"]}" alt="" width="800" height="496"{img_attrs(i)} decoding="async">{'<span class="badge">Running</span>' if loop else ''}</span>'
                    f'<span class="n">{i:03d}</span><span class="t">{esc(t)}</span><span class="y">{year(p)}</span>'
                    f'<span class="k">{esc(kind)}</span></a></li>')
    demos = sum(1 for p in projects if p.get("demo"))
    loops = sum(1 for p in projects if p["webm"])
    tools = len({plain(x).lower() for p in projects for x in p.get("tech") or []})
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    body = f"""{header("../", "Work")}
<main id="main" class="page">
<div class="wrap">
<section class="head" aria-labelledby="work-title">
  <h1 class="h1 grad" id="work-title">Work<sup><span id="count">{total}</span></sup></h1>
  <p class="lead">{loops} of {total} projects running their own loop. Search them, filter them, open the case study.</p>
  <div class="hud-row"><span>Projects<b>{total}</b></span><span>Demo links<b>{demos}</b></span><span>Loops<b>{loops}</b></span><span>Tools<b>{tools}</b></span><span>Showing<b id="shown">{total:03d}</b></span></div>
</section>
<div class="tools">
  <div class="tools-js">
    <div class="bar">
      <div class="search"><label class="mono" for="q">[ Search ]</label><input id="q" type="search" placeholder="Title, kind or tool" autocomplete="off" spellcheck="false"></div>
      <div class="views" role="group" aria-label="View"><button type="button" data-view="screens" aria-pressed="true">Screens</button><button type="button" data-view="list" aria-pressed="false">List</button></div>
    </div>
    <div class="chips" role="group" aria-label="Filter by kind">{"".join(chips)}</div>
  </div>
</div>
<ol id="items" class="screens" aria-label="Projects">
{chr(10).join(rows)}
</ol>
<div class="empty" id="empty" hidden><span class="mono">[ 000 results ]</span><h2 class="h2 grad">No project matches <span id="empty-q">these filters</span>.</h2><button class="btn" type="button" data-clear>Clear filters</button></div>
</div>
</main>
{footer("../")}
<script type="application/json" id="work-data">{blob}</script>"""
    return doc("Work, Rishit Mathur", f"All {total} projects by Rishit Mathur: analytics, machine learning and data systems, each with a case study.",
               "", "../", WORK_CSS, body, WORK_JS,
               f'<link rel="preload" as="image" href="../../{projects[0]["slug"]}/{projects[0]["thumb"]}" fetchpriority="high">\n')


def main():
    projects = load()
    SLUGS.update(p["slug"] for p in projects)
    total = len(projects)
    for i, p in enumerate(projects, 1):
        p["_i"] = i
    written = 0
    for i, p in enumerate(projects):
        out = X / "p" / p["slug"] / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(case_page(p, i + 1, total, projects[(i + 1) % total]))
        written += 1
    (X / "work").mkdir(parents=True, exist_ok=True)
    (X / "work" / "index.html").write_text(work_page(projects))
    print(f"projects: {total}")
    print(f"case pages written: {written} (x/p/<slug>/index.html)")
    print(f"work index: x/work/index.html")
    print(f"loops: webm {sum(p['webm'] for p in projects)}, mp4 {sum(p['mp4'] for p in projects)}, "
          f"cover only {sum(not (p['webm'] or p['mp4']) for p in projects)}")
    print(f"thumbs falling back to cover.jpg: {sum(p['thumb'] == 'cover.jpg' for p in projects)}; missing cover.jpg: {sum(not p['has_cover'] for p in projects)}")


if __name__ == "__main__":
    main()
