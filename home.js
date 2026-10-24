/* The home: a rendered world. Every case study is one screen in a tower of 224, standing in a dark hall over a reflecting
   floor, lit by its own screens, with dust in the air. The opening assembles the tower screen by screen while the count
   runs; scroll flies the camera: around the tower, up to each flagship (its screen comes forward to face you), inside the
   tower, back to see it unwrap into a wall of everything, and out across the floor to say goodbye. One post pass adds grain,
   vignette and a touch of chromatic aberration that grows with speed. Reduced motion: no opening, poses only. */
(async () => {
  "use strict";
  const root = document.documentElement, $ = id => document.getElementById(id);
  const scenes = [...document.querySelectorAll(".scene")];

  /* ---- into a case study: the clicked title travels (cross-document View Transitions); back home, no opening.
     Registered before anything else: pagereveal fires at the first render ---- */
  const slugOf = url => { try { const path = new URL(url, location.href).pathname; return scenes.map(s => s.dataset.slug).filter(Boolean).find(s => path.endsWith("/" + s + "/")); } catch (_) { return null; } };
  const nameFor = (slug, on) => { const s = scenes.find(s => s.dataset.slug === slug); if (s) s.querySelector("h3 a").style.viewTransitionName = on ? "title" : ""; };
  addEventListener("pageswap", e => { if (!e.viewTransition) return; const to = e.activation && e.activation.entry && e.activation.entry.url, s = to && slugOf(to); if (!s) { e.viewTransition.skipTransition(); return; } nameFor(s, true); try { sessionStorage.setItem("vt", s); } catch (_) {} });
  addEventListener("pagereveal", e => { let s = null; try { s = sessionStorage.getItem("vt"); sessionStorage.removeItem("vt"); } catch (_) {} if (!e.viewTransition) return; if (!s) { e.viewTransition.skipTransition(); return; } nameFor(s, true); e.viewTransition.finished.then(() => nameFor(s, false)); });

  /* the statement paints first; the world (Three.js, then the two atlases) loads just after it, so a slow connection
     reads the line before it downloads the 1.8 MB of screens */
  await new Promise(r => { const go = () => setTimeout(r, 400); document.readyState === "complete" ? go() : addEventListener("load", go, { once: true }); });
  const THREE = await import("three");
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const fine = matchMedia("(hover: hover) and (pointer: fine)").matches;
  const cl = v => Math.max(0, Math.min(1, v)), lerp = (a, b, t) => a + (b - a) * t, sm = t => t * t * (3 - 2 * t), easeOut = t => 1 - Math.pow(1 - t, 3);
  const ATLAS = JSON.parse($("atlas-data").textContent), ITEMS = ATLAS.items, N = ITEMS.length;
  const phone = () => innerWidth <= 720, wide = () => innerWidth > 1100;

  let lenis = null;
  if (typeof Lenis !== "undefined" && !reduced) { lenis = new Lenis({ lerp: 0.09, autoRaf: true, anchors: true }); root.classList.add("lenis-on"); }

  /* ---- HUD: clock, push date, copy button, nav ---- */
  const fmt = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" });
  const tickClock = () => { const t = fmt.format(new Date()) + " Tampa"; for (const id of ["clock", "clock2"]) { const el = $(id); if (el) el.textContent = t; } };
  tickClock(); setInterval(tickClock, 30000);
  const pushed = $("pushed");
  if (pushed) { const m = pushed.textContent.match(/(\d{4}-\d{2}-\d{2})/); if (m) { const d = Math.round((Date.now() - new Date(m[1])) / 864e5); pushed.textContent = d <= 0 ? "pushed today" : `last push ${d}d ago`; } }
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
  const nav = $("nav"), hint = $("hint"), countHud = $("count-hud"), counter = $("counter");
  let lastY = scrollY, pos = { i: 0, t: 0 }, cur = -1, vel = 0;
  const counters = scenes.map(s => { const v = s.querySelector(".num-v"); return v ? { v, end: +s.dataset.value, dec: (String(s.dataset.value).split(".")[1] || "").length, final: v.textContent, counts: !/\bof\b/.test(s.dataset.unit), t0: 0 } : null; });
  const measure = () => {
    const mid = innerHeight * 0.5;
    let i = 0, t = 0;
    for (let k = 0; k < scenes.length; k++) { const r = scenes[k].getBoundingClientRect(); if (r.top <= mid) { i = k; t = cl((mid - r.top) / Math.max(1, r.height)); } }
    pos = { i, t };
    if (i !== cur) { cur = i; const c = counters[i]; if (c && c.counts && !c.t0) c.t0 = performance.now(); }
    const y = scrollY; vel = lerp(vel, Math.abs(y - lastY), 0.3);
    if (Math.abs(y - lastY) > 6) { nav.classList.toggle("is-away", y > lastY && y > innerHeight * 0.6); lastY = y; }
    if (hint) hint.style.opacity = y > 40 ? "0" : "";
    if (countHud) countHud.style.opacity = y > innerHeight * 0.4 ? "0" : "";
  };
  addEventListener("scroll", measure, { passive: true });
  addEventListener("resize", measure);

  /* ---- the world ---- */
  const cv = $("world");
  let gl = null;
  try { gl = cv.getContext("webgl2", { antialias: false, alpha: false, powerPreference: "high-performance" }); } catch (_) {}
  if (!gl) { measure(); root.classList.add("intro-land", "intro-done"); return; }
  root.classList.add("gl-on");
  const renderer = new THREE.WebGLRenderer({ canvas: cv, context: gl, antialias: false, alpha: false });
  let dpr = Math.min(devicePixelRatio || 1, phone() ? 1.5 : 2);
  renderer.setPixelRatio(dpr);
  renderer.setClearColor(0x07070c, 1);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  const scene = new THREE.Scene();
  const INK = new THREE.Color(0x07070c);
  scene.background = INK;
  const camera = new THREE.PerspectiveCamera(34, 1, 0.1, 400);
  const FOG = { color: INK, density: 0.014 };

  /* fog shared by the custom shaders */
  const FOG_GLSL = `uniform vec3 uFog; uniform float uFogD; float fogF(float d){ return 1.0 - exp(-uFogD * uFogD * d * d); }`;

  /* ---- the screens: two instanced meshes, one per atlas ---- */
  const TILE_W = 1.9, TILE_H = TILE_W / 1.75, RING = 16, RINGS = Math.ceil(N / RING), RADIUS = (TILE_W * RING) / (2 * Math.PI) * 1.06, PITCH = TILE_H * 1.12;
  const TOWER_H = RINGS * PITCH;
  const tex = [];
  // ImageBitmapLoader decodes the two 4096px atlases off the main thread (TextureLoader decodes at upload, a long task)
  const bitmaps = new THREE.ImageBitmapLoader().setOptions({ imageOrientation: "from-image", premultiplyAlpha: "none" });
  const slot = new Int32Array(N);   // instance index inside its atlas mesh
  const groups = [];
  const atlasCount = Math.max(...ITEMS.map(it => it.a)) + 1;
  const perAtlas = Array.from({ length: atlasCount }, () => []);
  ITEMS.forEach((it, i) => perAtlas[it.a].push(i));
  const tileGeo = new THREE.PlaneGeometry(TILE_W, TILE_H, 1, 1);
  const makeMaterial = (map, mirror) => new THREE.ShaderMaterial({
    transparent: mirror, depthWrite: !mirror, side: THREE.DoubleSide,
    uniforms: { uMap: { value: map }, uCols: { value: ATLAS.cols }, uRows: { value: ATLAS.rows }, uFog: { value: FOG.color }, uFogD: { value: FOG.density }, uTime: { value: 0 }, uMirror: { value: mirror ? 1 : 0 } },
    vertexShader: `attribute vec2 aCell; attribute float aLit; attribute float aSel; uniform float uCols; uniform float uRows;
      varying vec2 vUv; varying float vLit; varying float vSel; varying float vDist; varying float vY; varying float vFace;
      void main() { vUv = (aCell + vec2(uv.x, 1.0 - uv.y)) / vec2(uCols, uRows); vLit = aLit; vSel = aSel;
        vec4 wp = instanceMatrix * vec4(position, 1.0); vec4 mvp = modelViewMatrix * wp; vY = (modelMatrix * wp).y; vDist = -mvp.z;
        vec3 n = normalize((modelViewMatrix * instanceMatrix * vec4(0.0, 0.0, 1.0, 0.0)).xyz); vFace = n.z;
        gl_Position = projectionMatrix * mvp; }`,
    fragmentShader: `precision highp float; uniform sampler2D uMap; uniform float uTime; uniform float uMirror; ${FOG_GLSL}
      varying vec2 vUv; varying float vLit; varying float vSel; varying float vDist; varying float vY; varying float vFace;
      void main() { vec3 c = texture2D(uMap, vUv).rgb;
        vec2 e = abs(fract(vUv * vec2(${ATLAS.cols}.0, ${ATLAS.rows}.0)) - 0.5); float frame = smoothstep(0.5, 0.47, max(e.x, e.y));
        float back = step(vFace, 0.0); c = mix(c, vec3(0.06, 0.06, 0.08), back * 0.92);
        float lit = mix(0.28, 1.0, vLit) + vSel * 0.25;
        c = c * lit * frame + vec3(0.02, 0.02, 0.03) * (1.0 - frame);
        float scan = 0.96 + 0.04 * sin(vUv.y * 900.0 + uTime * 2.0); c *= mix(1.0, scan, 0.5 * vLit);
        float a = 1.0;
        if (uMirror > 0.5) { a = clamp(1.0 + vY / 7.0, 0.0, 1.0) * 0.32; }
        c = mix(c, uFog, fogF(vDist));
        gl_FragColor = vec4(c, a); }`,
  });
  const meshes = [], mirrors = [];
  const cells = [], lits = [], sels = [];
  for (let a = 0; a < atlasCount; a++) {
    const t = new THREE.Texture();
    bitmaps.load(`assets/atlas/atlas-${a}${phone() ? "-2k" : ""}.webp`, bm => { t.image = bm; t.needsUpdate = true; if (a === 0) root.classList.add("atlas-ready"); });
    t.flipY = false; t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4; t.generateMipmaps = true; t.minFilter = THREE.LinearMipmapLinearFilter;
    tex.push(t);
    const n = perAtlas[a].length, geo = tileGeo.clone();
    const cell = new Float32Array(n * 2), lit = new Float32Array(n), sel = new Float32Array(n);
    perAtlas[a].forEach((idx, k) => { cell[k * 2] = ITEMS[idx].c; cell[k * 2 + 1] = ITEMS[idx].r; lit[k] = 1; slot[idx] = k; });
    geo.setAttribute("aCell", new THREE.InstancedBufferAttribute(cell, 2));
    geo.setAttribute("aLit", new THREE.InstancedBufferAttribute(lit, 1));
    geo.setAttribute("aSel", new THREE.InstancedBufferAttribute(sel, 1));
    const m = new THREE.InstancedMesh(geo, makeMaterial(t, false), n); m.frustumCulled = false;
    const mm = new THREE.InstancedMesh(geo, makeMaterial(t, true), n); mm.frustumCulled = false; mm.renderOrder = -1;
    meshes.push(m); mirrors.push(mm); cells.push(cell); lits.push(lit); sels.push(sel);
  }
  const tower = new THREE.Group(), mirrorGroup = new THREE.Group();
  meshes.forEach(m => tower.add(m)); mirrors.forEach(m => mirrorGroup.add(m));
  mirrorGroup.scale.y = -1;
  scene.add(tower, mirrorGroup);

  /* ---- the floor: ink with a faint grid, a glow under the tower, fog ---- */
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(600, 600), new THREE.ShaderMaterial({
    depthWrite: false,   // so the mirrored screens below it show through as reflections
    uniforms: { uFog: { value: FOG.color }, uFogD: { value: FOG.density }, uGlow: { value: 1 } },
    vertexShader: `varying vec2 vP; varying float vDist; void main() { vP = position.xy; vec4 mvp = modelViewMatrix * vec4(position, 1.0); vDist = -mvp.z; gl_Position = projectionMatrix * mvp; }`,
    fragmentShader: `precision highp float; uniform float uGlow; ${FOG_GLSL} varying vec2 vP; varying float vDist;
      void main() { vec2 g = abs(fract(vP / 2.0) - 0.5); float line = 1.0 - smoothstep(0.0, 0.03, min(g.x, g.y));
        float r = length(vP); float glow = exp(-r * r / 140.0) * 0.16 * uGlow;
        vec3 c = vec3(0.028, 0.028, 0.047) + line * 0.035 * exp(-r / 60.0) + vec3(0.12, 0.09, 0.16) * glow;
        c = mix(c, uFog, fogF(vDist)); gl_FragColor = vec4(c, 1.0); }`,
  }));
  floor.rotation.x = -Math.PI / 2; floor.position.y = -0.02;
  scene.add(floor);

  /* ---- dust ---- */
  const DUST = phone() ? 350 : 900;
  const dustGeo = new THREE.BufferGeometry(), dp = new Float32Array(DUST * 3), ds = new Float32Array(DUST);
  for (let i = 0; i < DUST; i++) { dp[i * 3] = (Math.random() - 0.5) * 60; dp[i * 3 + 1] = Math.random() * 26; dp[i * 3 + 2] = (Math.random() - 0.5) * 60; ds[i] = Math.random(); }
  dustGeo.setAttribute("position", new THREE.BufferAttribute(dp, 3)); dustGeo.setAttribute("aSeed", new THREE.BufferAttribute(ds, 1));
  const dust = new THREE.Points(dustGeo, new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    uniforms: { uTime: { value: 0 }, uDpr: { value: dpr }, uFog: { value: FOG.color }, uFogD: { value: FOG.density } },
    vertexShader: `attribute float aSeed; uniform float uTime; uniform float uDpr; varying float vA; varying float vDist;
      void main() { vec3 p = position; p.y = mod(p.y + uTime * (0.15 + aSeed * 0.25), 26.0); p.x += sin(uTime * 0.3 + aSeed * 20.0) * 0.6;
        vec4 mvp = modelViewMatrix * vec4(p, 1.0); vDist = -mvp.z; vA = 0.25 + 0.75 * aSeed; gl_Position = projectionMatrix * mvp; gl_PointSize = (1.2 + aSeed * 2.2) * uDpr * 90.0 / max(1.0, -mvp.z); }`,
    fragmentShader: `precision highp float; ${FOG_GLSL} varying float vA; varying float vDist; void main() { float d = length(gl_PointCoord - 0.5); if (d > 0.5) discard; float a = (1.0 - d * 2.0) * vA * 0.5 * (1.0 - fogF(vDist)); gl_FragColor = vec4(0.85, 0.82, 0.9, a); }`,
  }));
  scene.add(dust);

  /* ---- post: grain, vignette, chromatic aberration ---- */
  const rt = new THREE.WebGLRenderTarget(1, 1, { minFilter: THREE.LinearFilter, magFilter: THREE.LinearFilter, depthBuffer: true });
  const postScene = new THREE.Scene(), postCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
  const post = new THREE.ShaderMaterial({
    uniforms: { tDiffuse: { value: rt.texture }, uTime: { value: 0 }, uAb: { value: 0 }, uRes: { value: new THREE.Vector2(1, 1) } },
    vertexShader: `varying vec2 vUv; void main() { vUv = uv; gl_Position = vec4(position, 1.0); }`,
    fragmentShader: `precision highp float; uniform sampler2D tDiffuse; uniform float uTime; uniform float uAb; uniform vec2 uRes; varying vec2 vUv;
      float hash(vec2 p) { return fract(sin(dot(p, vec2(12.9898, 78.233)) + uTime) * 43758.5453); }
      void main() { vec2 d = (vUv - 0.5) * uAb;
        float r = texture2D(tDiffuse, vUv + d).r, g = texture2D(tDiffuse, vUv).g, b = texture2D(tDiffuse, vUv - d).b;
        vec3 c = vec3(r, g, b);
        float v = smoothstep(1.25, 0.35, length((vUv - 0.5) * vec2(1.0, uRes.y / uRes.x) * 1.2)); c *= mix(0.72, 1.0, v);
        c += (hash(gl_FragCoord.xy) - 0.5) * 0.055;
        gl_FragColor = vec4(c, 1.0); }`,
  });
  postScene.add(new THREE.Mesh(new THREE.PlaneGeometry(2, 2), post));
  const resize = () => { const w = innerWidth, h = innerHeight; renderer.setSize(w, h, false); rt.setSize(Math.round(w * dpr), Math.round(h * dpr)); camera.aspect = w / h; camera.updateProjectionMatrix(); post.uniforms.uRes.value.set(w, h); };
  addEventListener("resize", resize); resize();

  /* ---- layouts: per screen a target [x, y, z, yaw, scale]. Tower: rings; wall: a flat grid; the flagship: on stage ---- */
  const T = new Float32Array(N * 5);
  const put = (i, x, y, z, yaw, s) => { T[i * 5] = x; T[i * 5 + 1] = y; T[i * 5 + 2] = z; T[i * 5 + 3] = yaw; T[i * 5 + 4] = s; };
  const towerPos = i => { const ring = Math.floor(i / RING), k = i % RING, a = (k / RING) * Math.PI * 2 + ring * 0.11; return [Math.sin(a) * RADIUS, 0.6 + ring * PITCH + TILE_H / 2, Math.cos(a) * RADIUS, a]; };
  const LAYOUT = {
    tower() { for (let i = 0; i < N; i++) { const [x, y, z, a] = towerPos(i); put(i, x, y, z, a, 1); } },
    wall() {   // a flat wall of everything, facing +z, centred on the tower's axis
      const cols = phone() ? 8 : 16, gw = TILE_W * 1.06, gh = TILE_H * 1.1, rows = Math.ceil(N / cols);
      for (let i = 0; i < N; i++) { const c = i % cols, r = Math.floor(i / cols); put(i, (c - (cols - 1) / 2) * gw, 1.2 + (rows - 1 - r) * gh + TILE_H / 2, 0, 0, 1); }
    },
  };
  const layouts = { tower: null, wall: null };
  const layoutFor = name => { if (!layouts[name]) { LAYOUT[name](); layouts[name] = Float32Array.from(T); } return layouts[name]; };
  addEventListener("resize", () => { layouts.tower = null; layouts.wall = null; });
  const slugIndex = {}; ITEMS.forEach((it, i) => { slugIndex[it.slug] = i; });
  const flagshipOf = s => s.dataset.state === "flagship" ? slugIndex[s.dataset.slug] : -1;

  /* ---- camera per section: [eye x,y,z, aim x,y,z, fov]; the tower's own yaw per section ---- */
  const H = TOWER_H;
  const CAM = {
    tower: () => phone() ? [0, H * 0.55, 34, 0, H * 0.5, 0, 40] : [12, H * 0.62, 26, 0, H * 0.48, 0, 34],
    flagship: k => { const a = 0.9 + k * 1.5, r = phone() ? 20 : 16; return [Math.sin(a) * r, 2.5 + k * 2.6 + (phone() ? 3 : 0), Math.cos(a) * r, 0, H * 0.42, 0, phone() ? 44 : 36]; },
    inside: () => phone() ? [0, H + 9, 1.2, 0.3, 2, 0, 58] : [0, H + 7, 2.2, 0.4, 2, 0, 62],
    wall: () => phone() ? [0, H * 0.5 + 1, 46, 0, H * 0.5 - 2, 0, 50] : [0, H * 0.5 + 1, 34, 0, H * 0.5 - 2.5, 0, 42],
    far: () => phone() ? [10, 5, 60, 0, H * 0.4, 0, 40] : [22, 4, 54, 0, H * 0.4, 0, 34],
  };
  const camFor = i => { const s = scenes[Math.max(0, Math.min(scenes.length - 1, i))], st = s.dataset.state; if (st === "flagship") return CAM.flagship(scenes.slice(0, i).filter(x => x.dataset.state === "flagship").length); return (CAM[st] || CAM.tower)(); };
  const stateOf = i => scenes[Math.max(0, Math.min(scenes.length - 1, i))].dataset.state;
  const layoutOf = i => stateOf(i) === "wall" ? "wall" : "tower";

  /* ---- state ---- */
  const now = new Float32Array(N * 5), seed = new Float32Array(N);
  for (let i = 0; i < N; i++) { seed[i] = Math.random(); const a = seed[i] * Math.PI * 2; now[i * 5] = Math.sin(a) * 90; now[i * 5 + 1] = 40 + Math.random() * 40; now[i * 5 + 2] = Math.cos(a) * 90; now[i * 5 + 3] = a; now[i * 5 + 4] = 0.001; }
  const cam = { e: new THREE.Vector3(0, 40, 70), a: new THREE.Vector3(0, H * 0.5, 0), fov: 34 };
  const pointer = { x: 0, y: 0, tx: 0, ty: 0 };
  if (fine) addEventListener("pointermove", e => { pointer.tx = (e.clientX / innerWidth) * 2 - 1; pointer.ty = -((e.clientY / innerHeight) * 2 - 1); }, { passive: true });
  const M = new THREE.Matrix4(), Q = new THREE.Quaternion(), P = new THREE.Vector3(), S = new THREE.Vector3(), UP = new THREE.Vector3(0, 1, 0);
  let towerYaw = 0;

  /* ---- the opening: the tower assembles in order while the count runs; skip, wheel, key or touch ends it ---- */
  const introOn = root.classList.contains("intro") && !reduced;
  let introRun = introOn, t0 = 0, arrived = 0;
  const k = root.classList.contains("intro-again") ? 0.45 : 1, D = 2600 * k;
  const endIntro = () => { if (!introRun) return; introRun = false; arrived = N; counter.textContent = String(N).padStart(3, "0"); root.classList.add("intro-land", "intro-done"); if (lenis) lenis.start(); };
  if (introRun) { if (lenis) lenis.stop(); scrollTo(0, 0); counter.textContent = "000"; $("intro-skip").addEventListener("click", endIntro); for (const ev of ["wheel", "touchstart", "keydown"]) addEventListener(ev, () => endIntro(), { passive: true }); setTimeout(endIntro, 6500 * k); }
  else { root.classList.add("intro-land", "intro-done"); arrived = N; counter.textContent = String(N).padStart(3, "0"); }

  /* ---- the loop ---- */
  let frames = 0, slow = 0, lastT = performance.now();
  const tick = t => {
    requestAnimationFrame(tick);
    const dt = Math.min(0.05, (t - lastT) / 1000); lastT = t; const time = t / 1000;
    if (!introRun) measure();
    if (introRun) { if (!t0) t0 = t; const u = cl((t - t0) / D); arrived = Math.round(N * easeOut(u)); counter.textContent = String(arrived).padStart(3, "0"); if (u > 0.7) root.classList.add("intro-land"); if (u >= 1) endIntro(); }
    pointer.x = lerp(pointer.x, pointer.tx, 0.04); pointer.y = lerp(pointer.y, pointer.ty, 0.04);
    const ease = reduced ? 1 : 1 - Math.pow(0.0035, dt), camEase = reduced ? 1 : 1 - Math.pow(0.012, dt);

    // targets: current section's layout blended into the next over the last 45% of the section
    const i0 = pos.i, i1 = Math.min(scenes.length - 1, pos.i + 1), mix = i1 === i0 ? 0 : sm(cl((pos.t - 0.55) / 0.45));
    const A = layoutFor(layoutOf(i0)), B = layoutFor(layoutOf(i1));
    const fA = flagshipOf(scenes[i0]), fB = flagshipOf(scenes[i1]);
    const c0 = camFor(i0), c1 = camFor(i1);
    const ce = [], ca = []; for (let j = 0; j < 3; j++) { ce[j] = lerp(c0[j], c1[j], mix); ca[j] = lerp(c0[j + 3], c1[j + 3], mix); }
    const fov = lerp(c0[6], c1[6], mix);
    if (introRun) { const u = cl((t - t0) / D), e = easeOut(u); ce[0] = lerp(0, ce[0], e); ce[1] = lerp(40, ce[1], e); ce[2] = lerp(70, ce[2], e); }
    cam.e.x = lerp(cam.e.x, ce[0] + pointer.x * 1.4, camEase); cam.e.y = lerp(cam.e.y, ce[1] + pointer.y * 0.8, camEase); cam.e.z = lerp(cam.e.z, ce[2], camEase);
    cam.a.x = lerp(cam.a.x, ca[0], camEase); cam.a.y = lerp(cam.a.y, ca[1], camEase); cam.a.z = lerp(cam.a.z, ca[2], camEase);
    cam.fov = lerp(cam.fov, fov, camEase);
    camera.position.copy(cam.e); camera.lookAt(cam.a); if (Math.abs(camera.fov - cam.fov) > 0.01) { camera.fov = cam.fov; camera.updateProjectionMatrix(); }
    // the tower turns slowly, and not at all when it is a wall
    const wallMix = (layoutOf(i0) === "wall" ? 1 - mix : 0) + (layoutOf(i1) === "wall" ? mix : 0);
    towerYaw += dt * 0.05 * (1 - wallMix) * (reduced ? 0 : 1);
    tower.rotation.y = towerYaw * (1 - wallMix); mirrorGroup.rotation.y = tower.rotation.y;
    // the stage: where a flagship's screen comes to face the camera
    const fwd = new THREE.Vector3().subVectors(cam.a, cam.e).normalize(), right = new THREE.Vector3().crossVectors(fwd, UP).normalize(), up = new THREE.Vector3().crossVectors(right, fwd).normalize();
    const stage = new THREE.Vector3().copy(cam.e).addScaledVector(fwd, phone() ? 8 : 7.2).addScaledVector(right, wide() ? 0.8 : 0).addScaledVector(up, wide() ? 0.2 : phone() ? 1.5 : 0.7);
    const stageYaw = Math.atan2(cam.e.x - stage.x, cam.e.z - stage.z) - tower.rotation.y;
    // unrotate the stage into the tower's local frame
    const sl = stage.clone().applyAxisAngle(UP, -tower.rotation.y);
    for (let i = 0; i < N; i++) {
      const o = i * 5, d = seed[i] * 0.3, m = sm(cl((mix - d) / 0.7));
      let tx = lerp(A[o], B[o], m), ty = lerp(A[o + 1], B[o + 1], m), tz = lerp(A[o + 2], B[o + 2], m), tyaw = lerp(A[o + 3], B[o + 3], m), ts = lerp(A[o + 4], B[o + 4], m);
      const onA = i === fA ? 1 - mix : 0, onB = i === fB ? mix : 0, on = Math.max(onA, onB);
      if (on > 0) { const sc = phone() ? 1.4 : wide() ? 2.0 : 1.6; tx = lerp(tx, sl.x, on); ty = lerp(ty, sl.y, on); tz = lerp(tz, sl.z, on); tyaw = lerp(tyaw, stageYaw, on); ts = lerp(ts, sc, on); }
      if (introRun || i >= arrived) { if (i >= arrived) { ts = 0.001; } }
      now[o] = lerp(now[o], tx, ease); now[o + 1] = lerp(now[o + 1], ty, ease); now[o + 2] = lerp(now[o + 2], tz, ease); now[o + 3] = lerp(now[o + 3], tyaw, ease); now[o + 4] = lerp(now[o + 4], ts, ease);
      const a = ITEMS[i].a, kk = slot[i];
      P.set(now[o], now[o + 1] + (reduced ? 0 : Math.sin(time * 0.7 + seed[i] * 6.28) * 0.015), now[o + 2]);
      Q.setFromAxisAngle(UP, now[o + 3]); S.setScalar(now[o + 4]);
      M.compose(P, Q, S); meshes[a].setMatrixAt(kk, M); mirrors[a].setMatrixAt(kk, M);
      const litT = (fA >= 0 || fB >= 0) ? (on > 0 ? 1 : 0.42) : (stateOf(i0) === "tower" ? 0.75 : 1);
      lits[a][kk] = lerp(lits[a][kk], litT, ease); sels[a][kk] = lerp(sels[a][kk], on, ease);
    }
    for (let a = 0; a < atlasCount; a++) { meshes[a].instanceMatrix.needsUpdate = true; mirrors[a].instanceMatrix.needsUpdate = true; meshes[a].geometry.attributes.aLit.needsUpdate = true; meshes[a].geometry.attributes.aSel.needsUpdate = true; meshes[a].material.uniforms.uTime.value = time; mirrors[a].material.uniforms.uTime.value = time; }
    dust.material.uniforms.uTime.value = time;
    post.uniforms.uTime.value = time; post.uniforms.uAb.value = lerp(post.uniforms.uAb.value, Math.min(0.012, vel * 0.00025) + (introRun ? 0.006 : 0), 0.1);
    for (const c of counters) if (c && c.counts && c.t0) { const u = cl((t - c.t0) / 1400), e = easeOut(u); c.v.textContent = u < 1 ? (c.end * e).toFixed(c.dec) : c.final; }
    renderer.setRenderTarget(rt); renderer.render(scene, camera); renderer.setRenderTarget(null); renderer.render(postScene, postCam);
    if (++frames > 60 && dt > 0.024 && ++slow > 30 && dpr > 1) { dpr = 1; renderer.setPixelRatio(1); dust.material.uniforms.uDpr.value = 1; resize(); slow = -1e9; }
  };
  measure();
  requestAnimationFrame(tick);
})();
