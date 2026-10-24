/* The home: one WebGL field of points, one per public repository (data/github.json via build.py), behind the page.
   The opening counts them in (000 to the total) while they arrive; the count stays as the headline. Scroll changes the
   state of the field, not just the copy: by month and language in the hero, a 75.5% ratio, 31 tests passing, a forecast
   curve with its band, 20 of 20 locked, a stack by language, a grid for the index, a ring for contact. Every point eases
   toward its target with a frame-rate-independent lerp and a per-point delay so each change reads as a wave. */
import * as THREE from "three";

(() => {
  "use strict";
  const root = document.documentElement, $ = id => document.getElementById(id);
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const fine = matchMedia("(hover: hover) and (pointer: fine)").matches;
  const cl = v => Math.max(0, Math.min(1, v)), lerp = (a, b, t) => a + (b - a) * t, sm = t => t * t * (3 - 2 * t);
  const DATA = JSON.parse($("field-data").textContent), N = DATA.length;
  const scenes = [...document.querySelectorAll(".scene")];

  let lenis = null;
  if (typeof Lenis !== "undefined" && !reduced) { lenis = new Lenis({ lerp: 0.1, autoRaf: true, anchors: true }); root.classList.add("lenis-on"); }

  /* ---- the clock, the push date, the copy button, the nav ---- */
  const fmt = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" });
  const tickClock = () => { const t = fmt.format(new Date()) + " Tampa"; for (const id of ["clock", "clock2"]) { const el = $(id); if (el) el.textContent = t; } };
  tickClock(); setInterval(tickClock, 30000);
  const last = DATA.reduce((m, r) => (r.m > m ? r.m : m), ""), pushed = $("pushed");
  if (pushed) { const d = Math.round((Date.now() - new Date(last)) / 864e5); pushed.textContent = d <= 0 ? "pushed today" : `last push ${d}d ago`; }
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
  const nav = $("nav");
  let lastY = scrollY, pos = { i: 0, t: 0 }, cur = -1;
  const counters = scenes.map(s => { const v = s.querySelector(".num-v"); return v ? { v, end: +s.dataset.value, dec: (String(s.dataset.value).split(".")[1] || "").length, final: v.textContent, counts: !/\bof\b/.test(s.dataset.unit), t0: 0 } : null; });
  const measure = () => {
    const mid = innerHeight * 0.5;
    let i = 0, t = 0;
    for (let k = 0; k < scenes.length; k++) { const r = scenes[k].getBoundingClientRect(); if (r.top <= mid) { i = k; t = cl((mid - r.top) / Math.max(1, r.height)); } }
    pos = { i, t };
    if (i !== cur) { cur = i; const c = counters[i]; if (c && c.counts && !c.t0) c.t0 = performance.now(); }
    const y = scrollY;
    if (Math.abs(y - lastY) > 6) { nav.classList.toggle("is-away", y > lastY && y > innerHeight * 0.6); lastY = y; }
  };
  addEventListener("scroll", measure, { passive: true });
  addEventListener("resize", measure);

  /* ---- into a case study: the clicked title travels (cross-document View Transitions); back home, no count ---- */
  const slugOf = url => { try { const path = new URL(url, location.href).pathname; return scenes.map(s => s.dataset.slug).filter(Boolean).find(s => path.endsWith("/" + s + "/")); } catch (_) { return null; } };
  const nameFor = (slug, on) => { const s = scenes.find(s => s.dataset.slug === slug); if (s) s.querySelector("h3 a").style.viewTransitionName = on ? "title" : ""; };
  addEventListener("pageswap", e => { if (!e.viewTransition) return; const to = e.activation && e.activation.entry && e.activation.entry.url, s = to && slugOf(to); if (!s) { e.viewTransition.skipTransition(); return; } nameFor(s, true); try { sessionStorage.setItem("vt", s); } catch (_) {} });
  addEventListener("pagereveal", e => { let s = null; try { s = sessionStorage.getItem("vt"); sessionStorage.removeItem("vt"); } catch (_) {} if (!e.viewTransition) return; if (!s) { e.viewTransition.skipTransition(); return; } nameFor(s, true); e.viewTransition.finished.then(() => nameFor(s, false)); });

  /* ---- the field ---- */
  const cv = $("field");
  let gl = null;
  try { gl = cv.getContext("webgl2", { antialias: false, alpha: true, powerPreference: "high-performance" }); } catch (_) {}
  if (!gl) { measure(); root.classList.add("intro-land", "intro-done"); return; }
  root.classList.add("gl-on");
  const renderer = new THREE.WebGLRenderer({ canvas: cv, context: gl, antialias: false, alpha: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
  renderer.setClearColor(0x000000, 0);
  const scene = new THREE.Scene();
  const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, -10, 10);   // x in [-aspect, aspect], y in [-1, 1]
  let aspect = 1;
  const resize = () => { const w = innerWidth, h = innerHeight; aspect = w / h; renderer.setSize(w, h, false); camera.left = -aspect; camera.right = aspect; camera.updateProjectionMatrix(); };
  addEventListener("resize", resize); resize();

  const geo = new THREE.BufferGeometry();
  const posA = new Float32Array(N * 3), sizeA = new Float32Array(N), litA = new Float32Array(N), seedA = new Float32Array(N);
  for (let i = 0; i < N; i++) seedA[i] = Math.random();
  geo.setAttribute("position", new THREE.BufferAttribute(posA, 3));
  geo.setAttribute("aSize", new THREE.BufferAttribute(sizeA, 1));
  geo.setAttribute("aLit", new THREE.BufferAttribute(litA, 1));
  geo.setAttribute("aSeed", new THREE.BufferAttribute(seedA, 1));
  const mat = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, depthTest: false,
    uniforms: { uDpr: { value: renderer.getPixelRatio() }, uCount: { value: N }, uTime: { value: 0 }, uSignal: { value: new THREE.Color(0xd4ff3a) }, uWhite: { value: new THREE.Color(0xffffff) } },
    vertexShader: `attribute float aSize; attribute float aLit; attribute float aSeed; uniform float uDpr; uniform float uCount; uniform float uTime;
      varying float vLit; varying float vOn;
      void main() { vLit = aLit; float idx = float(gl_VertexID); vOn = step(idx, uCount - 0.5);
        vec3 p = position; p.y += sin(uTime * 0.6 + aSeed * 6.28318) * 0.004;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
        gl_PointSize = aSize * uDpr * vOn; }`,
    fragmentShader: `precision highp float; uniform vec3 uSignal; uniform vec3 uWhite; varying float vLit; varying float vOn;
      void main() { vec2 c = gl_PointCoord - 0.5; float d = length(c); if (d > 0.5) discard;
        float edge = 1.0 - smoothstep(0.42, 0.5, d);
        vec3 col = mix(uWhite, uSignal, vLit); float a = mix(0.42, 1.0, vLit) * edge * vOn;
        gl_FragColor = vec4(col, a); }`,
  });
  scene.add(new THREE.Points(geo, mat));

  /* ---- states: a target (x, y, size, lit) per point. Units: y in [-1, 1], x in [-aspect, aspect]. ---- */
  const wide = () => innerWidth > 1100, phone = () => innerWidth <= 720;
  // the region the field occupies: the right of the screen on desktop, the upper half on phones
  const region = () => phone() ? { x0: -aspect * 0.92, x1: aspect * 0.92, y0: 0.0, y1: 0.5 } : wide() ? { x0: aspect * 0.12, x1: aspect * 0.92, y0: -0.74, y1: 0.56 } : { x0: -aspect * 0.9, x1: aspect * 0.9, y0: 0.0, y1: 0.62 };
  const LANGS = ["Python", "TypeScript", "HTML", "R", "JavaScript", "Java", "Other"];
  const T = new Float32Array(N * 4);
  const put = (i, x, y, s, l) => { T[i * 4] = x; T[i * 4 + 1] = y; T[i * 4 + 2] = s; T[i * 4 + 3] = l; };
  const sizeOf = r => 4 + Math.min(22, Math.sqrt(r.c) * 3.2);
  const STATES = {
    hero() {   // a ribbon: x = the order the repository was created in, y = its language row; size by commits; case studies lit
      const R0 = region(), R = phone() ? { ...R0, y0: -0.3, y1: 0.0 } : R0, rows = LANGS.length, used = {}, per = {};   // on phones the count sits above the ribbon
      DATA.forEach(r => { per[r.l] = (per[r.l] || 0) + 1; });
      DATA.forEach((r, i) => {
        const li = Math.max(0, LANGS.indexOf(r.l)), n = used[r.l] = (used[r.l] || 0) + 1, cols = Math.min(per[r.l], phone() ? 14 : 26);
        const x = lerp(R.x0, R.x1, 0.02 + 0.96 * (((n - 1) % cols) + 0.5) / cols), w = Math.floor((n - 1) / cols);
        const y = lerp(R.y1, R.y0, (li + 0.5) / rows) + (w - 1.5) * (phone() ? 0.042 : 0.034) + (seedA[i] - 0.5) * 0.012;
        put(i, x, y, sizeOf(r) * (phone() ? 0.7 : 1), r.u ? 1 : 0.35);
      });
    },
    ratio() {   // 75.5% of the points lit, in a grid
      const R = region(), cols = phone() ? 16 : 20, rows = Math.ceil(N / cols), lit = Math.round(N * 0.755);
      DATA.forEach((r, i) => { const c = i % cols, w = Math.floor(i / cols); put(i, lerp(R.x0, R.x1, (c + 0.5) / cols), lerp(R.y1, R.y0, (w + 0.5) / rows), phone() ? 9 : 13, i < lit ? 1 : 0); });
    },
    tests() {   // 31 tests, each a large point; the rest a thin baseline (the 1.07M lines)
      const R = region();
      DATA.forEach((r, i) => {
        if (i < 31) { const c = i % 8, w = Math.floor(i / 8); put(i, lerp(R.x0, R.x1, (c + 0.5) / 8), lerp(R.y1, R.y1 - (R.y1 - R.y0) * 0.6, (w + 0.5) / 4), phone() ? 18 : 28, 1); }
        else { const t = (i - 31) / (N - 31); put(i, lerp(R.x0, R.x1, t), R.y0 + 0.02 + Math.sin(t * 40) * 0.006, 4, 0.15); }
      });
    },
    curve() {   // the forecast: a seasonal series, the band above and below after the forecast origin, the forecast lit
      const R = region(), n = Math.floor(N / 3);
      DATA.forEach((r, i) => {
        const band = Math.floor(i / n), j = i % n, t = j / (n - 1), fc = t > 0.72;
        const base = 0.5 + 0.22 * Math.sin(t * 6.28318 * 2.4 + 1.3) + t * 0.18 + (t > 0.9 ? 0.08 : 0);
        const spread = fc ? (t - 0.72) * 0.55 : 0;
        const y = base + (band === 1 ? spread : band === 2 ? -spread : 0);
        put(i, lerp(R.x0, R.x1, t), lerp(R.y0, R.y1, cl(y)), band === 0 ? (fc ? 9 : 7) : 4, band === 0 && fc ? 1 : band === 0 ? 0.5 : 0.12);
      });
    },
    lock() {   // 20 of 20 locked into a 5 x 4 grid; the rest orbit faintly
      const R = region(), cx = (R.x0 + R.x1) / 2, cy = (R.y0 + R.y1) / 2, rad = Math.min(R.x1 - R.x0, R.y1 - R.y0) * 0.5;
      DATA.forEach((r, i) => {
        if (i < 20) { const c = i % 5, w = Math.floor(i / 5); put(i, lerp(cx - rad * 0.6, cx + rad * 0.6, (c + 0.5) / 5), lerp(cy + rad * 0.5, cy - rad * 0.5, (w + 0.5) / 4), phone() ? 16 : 24, 1); }
        else { const a = (i / N) * 6.28318 * 3, rr = rad * (0.78 + 0.22 * seedA[i]); put(i, cx + Math.cos(a) * rr * 1.15, cy + Math.sin(a) * rr, 4, 0.1); }
      });
    },
    stack() {   // columns by language on desktop, rows by language on phones; real counts
      const R = region(), counts = {}, used = {};
      DATA.forEach(r => { counts[r.l] = (counts[r.l] || 0) + 1; });
      const order = LANGS.filter(l => counts[l]), cols = order.length;
      if (phone()) {
        const per = 18;
        DATA.forEach((r, i) => { const li = Math.max(0, order.indexOf(r.l)), n = used[r.l] = (used[r.l] || 0) + 1, c = (n - 1) % per, w = Math.floor((n - 1) / per);
          put(i, lerp(R.x0, R.x1, (c + 0.5) / per), lerp(R.y1, R.y0 + 0.1, (li + 0.5) / cols) + (w - 1) * 0.026, 7, 0.9); });
      } else {
        const per = 8;
        DATA.forEach((r, i) => { const li = Math.max(0, order.indexOf(r.l)), n = used[r.l] = (used[r.l] || 0) + 1, c = (n - 1) % per, w = Math.floor((n - 1) / per);
          put(i, lerp(R.x0, R.x1, (li + 0.5) / cols) + (c - (per - 1) / 2) * 0.034, R.y0 + w * 0.04, 11, 0.9); });
      }
    },
    grid() {   // the index: a tight grid, every point lit, small
      const R = region(), cols = phone() ? 15 : 22, rows = Math.ceil(N / cols);
      DATA.forEach((r, i) => { const c = i % cols, w = Math.floor(i / cols); put(i, lerp(R.x0, R.x1, (c + 0.5) / cols), lerp(R.y1, R.y0, (w + 0.5) / rows), 6, 0.85); });
    },
    ring() {   // contact: a ring
      const R = region(), cx = (R.x0 + R.x1) / 2, cy = (R.y0 + R.y1) / 2, rad = Math.min(R.x1 - R.x0, R.y1 - R.y0) * 0.46;
      DATA.forEach((r, i) => { const a = (i / N) * 6.28318, rr = rad * (i % 2 ? 1 : 0.88); put(i, cx + Math.cos(a) * rr * 1.1, cy + Math.sin(a) * rr, 6 + (i % 7 === 0 ? 10 : 0), i % 7 === 0 ? 1 : 0.5); });
    },
  };
  const stateOf = i => { const s = scenes[Math.max(0, Math.min(scenes.length - 1, i))].dataset.state; return STATES[s] ? s : "hero"; };
  const cache = {};
  const targetsFor = name => { if (!cache[name]) { STATES[name](); cache[name] = Float32Array.from(T); } return cache[name]; };
  addEventListener("resize", () => { for (const k in cache) delete cache[k]; });
  const now = new Float32Array(N * 4);   // current x, y, size, lit
  for (let i = 0; i < N; i++) { now[i * 4] = (seedA[i] - 0.5) * 4; now[i * 4 + 1] = (Math.random() - 0.5) * 3; now[i * 4 + 2] = 2; now[i * 4 + 3] = 0; }
  const pointer = { x: 0, y: 0, tx: 0, ty: 0 };
  if (fine) addEventListener("pointermove", e => { pointer.tx = (e.clientX / innerWidth) * 2 - 1; pointer.ty = -((e.clientY / innerHeight) * 2 - 1); }, { passive: true });

  /* ---- the opening: count 000 to N over 1.9 s while the points arrive in order; skip ends it ---- */
  const introOn = root.classList.contains("intro") && !reduced;
  let introRun = introOn, t0 = 0;
  const k = root.classList.contains("intro-again") ? 0.45 : 1, D = 1900 * k;
  const counter = $("counter");
  const endIntro = () => { if (!introRun) return; introRun = false; mat.uniforms.uCount.value = N; counter.textContent = String(N); root.classList.add("intro-land", "intro-done"); if (lenis) lenis.start(); };
  if (introRun) {
    if (lenis) lenis.stop();
    scrollTo(0, 0);
    counter.textContent = "000";
    mat.uniforms.uCount.value = 0;
    $("intro-skip").addEventListener("click", endIntro);
    for (const ev of ["wheel", "touchstart", "keydown"]) addEventListener(ev, () => endIntro(), { passive: true });
    setTimeout(endIntro, 4000 * k);
  } else { root.classList.add("intro-land", "intro-done"); }

  /* ---- the loop ---- */
  let frames = 0, slow = 0, lastT = performance.now();
  const tick = t => {
    requestAnimationFrame(tick);
    const dt = Math.min(0.05, (t - lastT) / 1000); lastT = t;
    if (!introRun) measure();
    if (introRun) { if (!t0) t0 = t; const u = cl((t - t0) / D), e = 1 - Math.pow(1 - u, 3), c = Math.round(N * e); mat.uniforms.uCount.value = c; counter.textContent = String(c).padStart(3, "0"); if (u >= 1) endIntro(); }
    const a = targetsFor(stateOf(pos.i)), b = targetsFor(stateOf(pos.i + 1));
    const mix = pos.i >= scenes.length - 1 ? 0 : sm(cl((pos.t - 0.55) / 0.45));
    pointer.x = lerp(pointer.x, pointer.tx, 0.05); pointer.y = lerp(pointer.y, pointer.ty, 0.05);
    const px = pointer.x * 0.03, py = pointer.y * 0.02;
    const ease = reduced ? 1 : 1 - Math.pow(0.004, dt);
    for (let i = 0; i < N; i++) {
      const o = i * 4, m = sm(cl((mix - seedA[i] * 0.35) / 0.65));   // per-point delay: the change reads as a wave
      for (let j = 0; j < 4; j++) now[o + j] = lerp(now[o + j], lerp(a[o + j], b[o + j], m), ease);
      posA[i * 3] = now[o] + px; posA[i * 3 + 1] = now[o + 1] + py; sizeA[i] = now[o + 2]; litA[i] = now[o + 3];
    }
    geo.attributes.position.needsUpdate = true; geo.attributes.aSize.needsUpdate = true; geo.attributes.aLit.needsUpdate = true;
    mat.uniforms.uTime.value = t / 1000;
    for (const c of counters) if (c && c.counts && c.t0) { const u = cl((t - c.t0) / 1400), e = 1 - Math.pow(1 - u, 3); c.v.textContent = u < 1 ? (c.end * e).toFixed(c.dec) : c.final; }
    renderer.render(scene, camera);
    if (++frames > 60 && dt > 0.024 && ++slow > 30 && renderer.getPixelRatio() > 1) { renderer.setPixelRatio(1); mat.uniforms.uDpr.value = 1; slow = -1e9; }
  };
  measure();
  requestAnimationFrame(tick);
})();
