/* The home page: one live Three.js scene of the four printed project objects (boarding pass, till receipt, ruler, Form 10-K
   booklet) in a fixed canvas behind the page. Each section is a pose: the hero's cluster, each project's object brought to
   the front, a stack for about, a scatter for contact. Scroll blends between poses and everything eases toward its target
   so the motion feels heavy; the pointer tilts the objects; the colour field wipes to the next section's colour.
   The opening flies the objects in from far away, then the name slams up. Reduced motion: poses only, no opening. */
import * as THREE from "three";

(() => {
  "use strict";
  const root = document.documentElement, $ = id => document.getElementById(id);
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const fine = matchMedia("(hover: hover) and (pointer: fine)").matches;
  const cl = v => Math.max(0, Math.min(1, v)), smooth = t => t * t * (3 - 2 * t), lerp = (a, b, t) => a + (b - a) * t;
  const scenes = [...document.querySelectorAll(".scene")];
  const fieldEl = $("field"), wipe = $("wipe");

  let lenis = null;
  if (typeof Lenis !== "undefined" && !reduced) { lenis = new Lenis({ lerp: 0.1, autoRaf: true, anchors: true }); root.classList.add("lenis-on"); }

  /* ---- which section is current, how far through it; the fixed field behind the blocks follows so overscroll matches ---- */
  let cur = -1, fieldNow = scenes[0].dataset.field;
  fieldEl.style.setProperty("--field-now", fieldNow); document.body.style.backgroundColor = fieldNow;
  const setField = (i) => {
    const next = scenes[i].dataset.field;
    if (next === fieldNow) return;
    fieldNow = next;
    document.body.style.backgroundColor = next;   // the page's own background follows, so contrast tools see the real field
    if (reduced) { fieldEl.style.setProperty("--field-now", next); return; }
    wipe.classList.remove("is-on"); wipe.style.setProperty("--field-next", next);
    void wipe.offsetHeight;   // restart the transition
    wipe.classList.add("is-on");
    const done = () => { fieldEl.style.setProperty("--field-now", next); wipe.classList.remove("is-on"); wipe.removeEventListener("transitionend", done); };
    wipe.addEventListener("transitionend", done);
    setTimeout(done, 700);
  };
  const counters = scenes.map(s => { const v = s.querySelector(".num-v"); return v ? { v, end: +s.dataset.value, dec: (String(s.dataset.value).split(".")[1] || "").length, final: v.textContent, counts: !/\bof\b/.test(s.dataset.unit), t0: 0 } : null; });
  const nav = $("nav");
  let lastY = scrollY, pos = { i: 0, t: 0 };
  const measure = () => {
    const mid = innerHeight * 0.5;
    let i = 0, t = 0;
    for (let k = 0; k < scenes.length; k++) {
      const r = scenes[k].getBoundingClientRect();
      if (r.top <= mid) { i = k; t = cl((mid - r.top) / Math.max(1, r.height)); }
    }
    pos = { i, t };
    if (i !== cur) { cur = i; setField(i); const c = counters[i]; if (c && c.counts && !c.t0) c.t0 = performance.now(); }
    const y = scrollY;
    if (Math.abs(y - lastY) > 6) { nav.classList.toggle("is-away", y > lastY && y > innerHeight * 0.6); lastY = y; }
  };
  addEventListener("scroll", measure, { passive: true });
  addEventListener("resize", measure);

  /* ---- the scene ---- */
  const cv = $("gl");
  let gl = null;
  try { gl = cv.getContext("webgl2", { antialias: true, alpha: true, powerPreference: "high-performance" }); } catch (_) {}
  if (!gl) { measure(); return; }
  root.classList.add("gl-on");
  const renderer = new THREE.WebGLRenderer({ canvas: cv, context: gl, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
  renderer.setClearColor(0x000000, 0);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(32, 1, 0.1, 100);
  camera.position.set(0, 0, 11);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x8888aa, 1.4));
  const key = new THREE.DirectionalLight(0xffffff, 2.2); key.position.set(-4, 6, 8); scene.add(key);
  const fill = new THREE.DirectionalLight(0xffffff, 0.7); fill.position.set(5, -2, 4); scene.add(fill);

  const loader = new THREE.TextureLoader();
  const tex = n => { const t = loader.load(`assets/objects/${n}.webp`); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 8; return t; };
  const paper = (map, alpha = false) => new THREE.MeshStandardMaterial({ map, roughness: 0.62, metalness: 0, side: THREE.DoubleSide, transparent: alpha, alphaTest: alpha ? 0.5 : 0 });

  // the boarding pass: a bent sheet (8 x 3.2 in the desk's units, here 2.5 x 1.0)
  const passG = new THREE.PlaneGeometry(2.5, 1.0, 32, 8);
  { const p = passG.attributes.position; for (let i = 0; i < p.count; i++) { const x = p.getX(i); p.setZ(i, 0.06 * Math.max(0, (x - 0.6) / 0.65) ** 2); } passG.computeVertexNormals(); }
  const pass = new THREE.Mesh(passG, paper(tex("pass")));
  // the till receipt: a long strip that curls at both ends
  const rcG = new THREE.PlaneGeometry(0.9, 3.0, 8, 64);
  { const p = rcG.attributes.position; for (let i = 0; i < p.count; i++) { const y = p.getY(i); p.setZ(i, 0.35 * Math.abs(y / 1.5) ** 5 + 0.02 * Math.sin(y * 4)); } rcG.computeVertexNormals(); }
  const rcpt = new THREE.Mesh(rcG, paper(tex("rcpt"), true));
  // the ruler: an acid-lime bar with the printed face on top
  const ruler = new THREE.Group();
  ruler.add(new THREE.Mesh(new THREE.BoxGeometry(3.0, 0.45, 0.06), new THREE.MeshStandardMaterial({ color: 0xd8f56a, roughness: 0.35, metalness: 0 })));
  { const face = new THREE.Mesh(new THREE.PlaneGeometry(3.0, 0.45), paper(tex("ruler"), true)); face.position.z = 0.031; ruler.add(face); }
  // the Form 10-K booklet: a block of pages, the cover, three tabs
  const book = new THREE.Group();
  book.add(new THREE.Mesh(new THREE.BoxGeometry(1.9, 2.5, 0.12), new THREE.MeshStandardMaterial({ color: 0xefece4, roughness: 0.85 })));
  { const cover = new THREE.Mesh(new THREE.PlaneGeometry(1.92, 2.52), paper(tex("book"))); cover.position.z = 0.061; book.add(cover); }
  [[0xfcd63c, 0.8], [0xf7a3c0, 0.3], [0xa6e3c2, -0.2]].forEach(([c, y], i) => { const t = new THREE.Mesh(new THREE.BoxGeometry(0.36, 0.26, 0.01), new THREE.MeshStandardMaterial({ color: c, roughness: 0.7 })); t.position.set(1.05, y, 0.03 - i * 0.012); book.add(t); });
  const objs = { pass, rcpt, ruler, book };
  const all = Object.values(objs);
  all.forEach(o => scene.add(o));

  /* poses: [x, y, z, rx, ry, rz, scale] per object per section state. Right column on desktop (x > 0), upper half on phones. */
  /* the words live in the left column on desktop and the lower half on phones; the featured object takes the right column
     (or the upper half), and the other three wait in the corners, small and far back, clear of every line of text */
  const wide = () => innerWidth > 1100, phone = () => innerWidth <= 720;
  const far = () => (wide() ? 1.0 : 0), up = () => (wide() ? 0 : 0.85), sm = () => (phone() ? 0.6 : 1);
  const corner = (names) => {   // three parking spots down the right edge (desktop) or along the top edge (phone), clear of the words
    const spots = phone() ? [[-1.5, 4.6, -5, 0.4], [1.6, 4.7, -5, 0.4], [2.4, 3.0, -6, 0.35]] : wide() ? [[5.6, 3.8, -5, 0.65], [6.4, 0.3, -6, 0.6], [5.8, -3.5, -5, 0.65]] : [[-3.4, 4.8, -5, 0.5], [3.4, 4.8, -5, 0.5], [3.9, 3.0, -6, 0.45]];
    const o = {}; names.forEach((n, i) => { const [x, y, z, s] = spots[i]; o[n] = [x, y, z, 0.4 - i * 0.3, 0.5 * (i % 2 ? -1 : 1), 0.4 * (i - 1), s]; }); return o;
  };
  const POSE = {
    cluster: () => phone()
      ? ({ pass: [0.0, 2.4, -0.5, -0.4, 0.2, -0.25, 0.75], rcpt: [-1.4, 0.6, -1.5, 0.2, 0.3, 0.2, 0.6], ruler: [1.3, 0.4, -1.0, 0.4, -0.3, 0.5, 0.6], book: [0.1, 1.2, -3.0, -0.3, -0.4, 0.15, 0.6] })
      : ({ pass: [0.4, 2.2, -1.2, -0.5, 0.2, -0.3, 1.1], rcpt: [-3.4, 0.8, -0.5, 0.2, 0.3, 0.2, 1.0], ruler: [3.4, 0.2, 0.4, 0.4, -0.3, 0.5, 1.0], book: [-0.6, -0.2, 0.8, -0.3, -0.4, 0.15, 0.9] }),
    pass: () => ({ pass: [1.9 * far() + 0.2, up(), 3.0, -0.25, -0.35, 0.12, 1.35 * sm()], ...corner(["rcpt", "ruler", "book"]) }),
    rcpt: () => ({ rcpt: [1.5 * far() + 0.3, up() - 0.1, 3.0, -0.15, 0.35, 0.18, 1.25 * sm()], ...corner(["pass", "ruler", "book"]) }),
    ruler: () => ({ ruler: [1.3 * far() + 0.2, up(), 3.2, -0.35, 0.25, -0.5, 1.35 * sm()], ...corner(["book", "rcpt", "pass"]) }),
    book: () => ({ book: [1.6 * far() + 0.2, up(), 3.0, -0.2, -0.45, 0.12, 1.3 * sm()], ...corner(["pass", "rcpt", "ruler"]) }),
    stack: () => { const x = 1.9 * far() + 0.2, y = up() + (phone() ? 1.2 : 0), s = phone() ? 0.6 : 1; return { book: [x, y - 0.9, 0.0, -1.2, 0.0, 0.15, s], pass: [x + 0.1, y - 0.5, 0.5, -1.2, 0.0, -0.2, s], ruler: [x - 0.1, y - 0.1, 1.0, -1.2, 0.0, 0.35, 0.9 * s], rcpt: [x + 0.2, y + 0.4, 1.5, -1.2, 0.0, -0.1, 0.8 * s] }; },
    scatter: () => phone()
      ? ({ pass: [-1.3, 4.2, -2, 0.6, -0.6, 0.6, 0.6], rcpt: [1.6, 3.4, -2, -0.4, 0.5, -0.9, 0.6], ruler: [1.2, -4.6, -1, 0.3, 0.6, 0.9, 0.6], book: [-1.6, -4.2, -2, -0.6, 0.6, -0.5, 0.55] })
      : ({ pass: [5.2, 3.0, -1, 0.6, -0.6, 0.6, 1.2], rcpt: [6.2, -0.4, -2, -0.4, 0.5, -0.9, 1.2], ruler: [2.6, -4.2, 0.5, 0.3, 0.6, 0.9, 1.2], book: [5.6, -3.6, -3, -0.6, 0.6, -0.5, 0.9] }),
  };
  const stateOf = i => scenes[Math.max(0, Math.min(scenes.length - 1, i))].dataset.state;
  const now = {}; all.forEach(o => { now[o.uuid] = [0, 0, -40, 0, 0, 0, 0.001]; });
  const pointer = { x: 0, y: 0, tx: 0, ty: 0 };
  if (fine) addEventListener("pointermove", e => { pointer.tx = (e.clientX / innerWidth) * 2 - 1; pointer.ty = -((e.clientY / innerHeight) * 2 - 1); }, { passive: true });

  const resize = () => { const w = innerWidth, h = innerHeight; renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); };
  addEventListener("resize", resize); resize();

  /* ---- the opening ---- */
  const introOn = root.classList.contains("intro") && !reduced;
  let introRun = introOn, t0 = 0;
  const k = root.classList.contains("intro-again") ? 0.45 : 1, FLY = 1700 * k;
  const endIntro = () => { if (!introRun) return; introRun = false; root.classList.add("intro-land", "intro-done"); if (lenis) lenis.start(); };
  if (introRun) {
    if (lenis) lenis.stop();
    scrollTo(0, 0);
    $("intro-skip").addEventListener("click", endIntro);
    for (const ev of ["wheel", "touchstart", "keydown", "pointerdown"]) addEventListener(ev, e => { if (e.target !== $("intro-skip")) endIntro(); }, { passive: true });
    setTimeout(endIntro, 4000 * k);
  } else { root.classList.add("intro-land", "intro-done"); }

  /* ---- the loop: ease every object toward its pose, tilt to the pointer, float, count, render ---- */
  let frames = 0, slowFrames = 0, last = performance.now();
  const tick = t => {
    requestAnimationFrame(tick);
    const dt = Math.min(0.05, (t - last) / 1000); last = t;
    if (!introRun) measure();
    const a = POSE[stateOf(pos.i)](), b = POSE[stateOf(pos.i + 1)]();
    const mix = pos.i >= scenes.length - 1 ? 0 : smooth(cl((pos.t - 0.55) / 0.45));   // the hand-off happens in the last 45% of a section
    let flyMix = 1;
    if (introRun) { if (!t0) t0 = t; const u = cl((t - t0) / FLY); flyMix = 1 - Math.pow(1 - u, 3); if (u > 0.62) root.classList.add("intro-land"); if (u >= 1) endIntro(); }
    pointer.x = lerp(pointer.x, pointer.tx, 0.06); pointer.y = lerp(pointer.y, pointer.ty, 0.06);
    const ease = reduced ? 1 : 1 - Math.pow(0.0025, dt);   // heavy, frame-rate independent
    let idx = 0;
    for (const [name, o] of Object.entries(objs)) {
      const pa = a[name], pb = b[name], target = pa.map((v, j) => lerp(v, pb[j], mix));
      if (introRun) { const start = [idx % 2 ? 9 : -9, idx > 1 ? 7 : -7, -30, 2, 3, 1, 0.3]; for (let j = 0; j < 7; j++) target[j] = lerp(start[j], target[j], flyMix); }
      const c = now[o.uuid];
      for (let j = 0; j < 7; j++) c[j] = lerp(c[j], target[j], ease);
      const ph = idx * 1.7, fl = reduced ? 0 : Math.sin(t / 1000 * 0.8 + ph) * 0.07;
      const featured = stateOf(pos.i) === name ? 1 : 0.35;
      o.position.set(c[0], c[1] + fl, c[2]);
      o.rotation.set(c[3] + pointer.y * 0.22 * featured + (reduced ? 0 : Math.sin(t / 1000 * 0.5 + ph) * 0.03), c[4] + pointer.x * 0.35 * featured, c[5]);
      o.scale.setScalar(c[6]);
      idx++;
    }
    for (const c of counters) if (c && c.counts && c.t0) { const u = cl((t - c.t0) / 1400), e = 1 - Math.pow(1 - u, 3); c.v.textContent = u < 1 ? (c.end * e).toFixed(c.dec) : c.final; }
    renderer.render(scene, camera);
    // adaptive quality: if frames keep taking longer than 24 ms, step the pixel ratio down once
    if (++frames > 60 && dt > 0.024 && ++slowFrames > 30 && renderer.getPixelRatio() > 1) { renderer.setPixelRatio(1); slowFrames = -1e9; }
  };
  measure();
  requestAnimationFrame(tick);

  /* ---- into a case study: the clicked title travels (cross-document View Transitions); back home, no intro ---- */
  const slugOf = url => { try { const path = new URL(url, location.href).pathname; return scenes.map(s => s.dataset.slug).filter(Boolean).find(s => path.endsWith("/" + s + "/")); } catch (_) { return null; } };
  const nameFor = (slug, on) => { const s = scenes.find(s => s.dataset.slug === slug); if (s) s.querySelector("h3 a").style.viewTransitionName = on ? "title" : ""; };
  addEventListener("pageswap", e => { if (!e.viewTransition) return; const to = e.activation && e.activation.entry && e.activation.entry.url, s = to && slugOf(to); if (!s) { e.viewTransition.skipTransition(); return; } nameFor(s, true); try { sessionStorage.setItem("vt", s); } catch (_) {} });
  addEventListener("pagereveal", e => { let s = null; try { s = sessionStorage.getItem("vt"); sessionStorage.removeItem("vt"); } catch (_) {} if (!e.viewTransition) return; if (!s) { e.viewTransition.skipTransition(); return; } nameFor(s, true); e.viewTransition.finished.then(() => nameFor(s, false)); });

  /* ---- phone menu ---- */
  const menuBtn = $("menu-btn"), linksBox = $("nav-links");
  const setMenu = open => { menuBtn.setAttribute("aria-expanded", String(open)); document.body.classList.toggle("menu-open", open); menuBtn.textContent = open ? "Close" : "Menu"; };
  menuBtn.addEventListener("click", () => setMenu(menuBtn.getAttribute("aria-expanded") !== "true"));
  linksBox.addEventListener("click", e => { if (e.target.closest("a")) setMenu(false); });
  addEventListener("keydown", e => { if (e.key === "Escape" && document.body.classList.contains("menu-open")) { setMenu(false); menuBtn.focus(); } });

  /* ---- the clock and the copy button ---- */
  const clock = $("clock");
  if (clock) { const fmt = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" }); const tickClock = () => { clock.textContent = fmt.format(new Date()) + " in Tampa"; }; tickClock(); setInterval(tickClock, 30000); }
  const copyBtn = $("copy-mail");
  if (navigator.clipboard && copyBtn) {
    copyBtn.hidden = false;
    copyBtn.addEventListener("click", async () => {
      const label = copyBtn.querySelector(".copy-text");
      try { await navigator.clipboard.writeText(copyBtn.dataset.mail); label.textContent = "Copied"; $("copy-status").textContent = "E-mail address copied"; }
      catch (_) { label.textContent = "Copy failed"; $("copy-status").textContent = "Could not copy; the address is the link above"; }
      setTimeout(() => { label.textContent = "Copy e-mail"; }, 2200);
    });
  }
})();
