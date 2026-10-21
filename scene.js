/* The corridor behind the portfolio: one persistent Three.js scene driven by native scroll.
   Every one of the project covers is a screen on the inside of a long tube (one instanced mesh, four texture atlases built
   from the real covers by tools/wall-atlas.cjs). The camera stands at the mouth in the hero, flies through the whole body
   of work in the corridor chapter, looks back at it behind the four flagships and sees it from outside as one object at
   the contact. Chapters are the elements carrying data-scene in document order. The page is complete without this file:
   a poster stands in when WebGL is unavailable. Colours come from theme.css (--c-wall-*). */
import * as THREE from "three";

const root = document.documentElement, $ = id => document.getElementById(id);
const canvas = $("scene");
const motionQuery = matchMedia("(prefers-reduced-motion: reduce)");
let reduced = motionQuery.matches, paused = root.classList.contains("motion-off");
const small = () => innerWidth < 900 || matchMedia("(pointer: coarse)").matches;
const col = name => { const d = document.createElement("div"); d.style.color = `var(${name})`; document.body.append(d); const c = getComputedStyle(d).color; d.remove(); return new THREE.Color(c); };
const DATA = JSON.parse($("projects-data").textContent);
const ATLAS = JSON.parse(canvas.dataset.atlas);                                  // {tile:[w,h], size, cols, atlases}
const chapters = [...document.querySelectorAll("[data-scene]")];
const LAST = chapters.length - 1;
const KIND = chapters.map(c => c.dataset.scene);
const paperWorld = document.querySelector(".reading-world");
const report = state => { root.classList.toggle("scene-live", state === "live"); root.classList.toggle("scene-static", state === "static"); dispatchEvent(new CustomEvent("portfolio:scene", { detail: { state } })); };
const progress = (loaded, total) => dispatchEvent(new CustomEvent("portfolio:load", { detail: { loaded, total } }));

/* ---- geometry of the corridor: FACETS screens around each ring, one ring every PITCH units, all facing the axis ---- */
const TW = 1.75, TH = 1, GAP = 0.22, FACETS = 12, PITCH = TH + GAP;
const R = (TW + GAP) / (2 * Math.sin(Math.PI / FACETS));
const N = DATA.length, RINGS = Math.ceil(N / FACETS), DEPTH = RINGS * PITCH;    // the tube runs from z = 0 to z = -DEPTH

/* ---- scroll -> chapter progress (t: chapter index + fraction) ---- */
let tops = [], target = 0, t = 0, paperTop = Infinity, paperBottom = -Infinity, corrTop = 0, corrSpan = 1, corrP = 0;
const CORR = KIND.indexOf("corridor");
function measure() {
  tops = chapters.map((c, k) => {
    const r = c.getBoundingClientRect(), h = innerHeight;
    const at = k === LAST ? Math.min(r.height / 2, h / 2) : KIND[k] === "corridor" ? 0 : Math.min(r.height / 2, h * 0.5);
    return r.top + scrollY + at;
  });
  if (paperWorld) { const r = paperWorld.getBoundingClientRect(); paperTop = r.top + scrollY; paperBottom = r.bottom + scrollY; }
  if (CORR >= 0) { const r = chapters[CORR].getBoundingClientRect(); corrTop = r.top + scrollY; corrSpan = Math.max(1, r.height - innerHeight); }
}
function onScroll() {
  if (!tops.length) return;
  const s = scrollY + innerHeight * 0.5;
  let i = 0;
  while (i < LAST && s >= tops[i + 1]) i++;
  const span = Math.max(1, (tops[i + 1] ?? tops[i] + innerHeight) - tops[i]);
  target = Math.min(LAST, Math.max(0, i + (s - tops[i]) / span));
  corrP = CORR >= 0 ? Math.min(1, Math.max(0, (scrollY - corrTop) / corrSpan)) : 1;    // the pinned chapter's own progress drives the flight
  wake();
}
const covered = () => scrollY >= paperTop - 8 && scrollY + innerHeight <= paperBottom + 8;
const smooth = (a, b, x) => { const k = Math.min(1, Math.max(0, (x - a) / (b - a))); return k * k * (3 - 2 * k); };
const lerp = (a, b, s) => a + (b - a) * s;

/* ---- the scene ---- */
let renderer, scene, camera, wall, mat, raf = 0, lastFrame = 0, clock = 0, lost = 0, drift = 0, spin = 0, hovered = -1, ready = false;
const palette = {};
const v3 = new THREE.Vector3(), look = new THREE.Vector3(), dummy = new THREE.Object3D();
const keep = new URLSearchParams(location.search).get("scene") === "keep";

function build() {
  Object.assign(palette, { fog: col("--c-wall-fog"), rim: col("--c-wall-rim"), hover: col("--c-wall-hover") });
  renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, small() ? 1.5 : 2));
  renderer.setClearColor(0x000000, 0);
  scene = new THREE.Scene();
  camera = new THREE.PerspectiveCamera(62, 1, 0.1, 120);
  const geo = new THREE.PlaneGeometry(TW, TH);
  const tile = new Float32Array(N * 3), seed = new Float32Array(N), ids = new Float32Array(N);
  wall = new THREE.InstancedMesh(geo, null, N);
  DATA.forEach((p, i) => {
    const ring = Math.floor(i / FACETS), f = i % FACETS, a = (f + (ring % 2) * 0.5) * (Math.PI * 2 / FACETS) + Math.PI / 2;
    dummy.position.set(Math.cos(a) * R, Math.sin(a) * R, -ring * PITCH - PITCH / 2);
    dummy.up.set(0, 0, -1); dummy.lookAt(0, 0, dummy.position.z);                   // the screen faces the axis, its top points down the corridor
    dummy.updateMatrix(); wall.setMatrixAt(i, dummy.matrix);
    const w = p.w || [0, 0, 0]; tile[i * 3] = w[0]; tile[i * 3 + 1] = w[1]; tile[i * 3 + 2] = w[2]; seed[i] = (i * 0.618034) % 1; ids[i] = i;
  });
  geo.setAttribute("aTile", new THREE.InstancedBufferAttribute(tile, 3));
  geo.setAttribute("aSeed", new THREE.InstancedBufferAttribute(seed, 1));
  geo.setAttribute("aId", new THREE.InstancedBufferAttribute(ids, 1));
  const [tw, th] = ATLAS.tile, S = ATLAS.size;
  mat = new THREE.ShaderMaterial({
    uniforms: { uA0: { value: null }, uA1: { value: null }, uA2: { value: null }, uA3: { value: null }, uLoaded: { value: 0 },
      uTile: { value: new THREE.Vector2(tw / S, th / S) }, uFog: { value: palette.fog }, uRim: { value: palette.rim }, uHoverCol: { value: palette.hover },
      uHover: { value: -1 }, uTime: { value: 0 }, uLit: { value: 1 }, uFade: { value: 0.085 }, uNear: { value: 0.4 } },
    vertexShader: `attribute vec3 aTile; attribute float aSeed; attribute float aId; uniform float uHover; uniform float uTime;
      varying vec2 vUv; varying vec3 vTile; varying float vDist; varying float vHover; varying float vSeed;
      void main(){ vUv = uv; vTile = aTile; vSeed = aSeed;
        vHover = abs(uHover - aId) < 0.5 ? 1.0 : 0.0;
        vec3 p = position * (1.0 + vHover * 0.06);
        vec4 w = modelMatrix * instanceMatrix * vec4(p, 1.0);
        vec4 mv = viewMatrix * w; vDist = -mv.z;
        gl_Position = projectionMatrix * mv; }`,
    fragmentShader: `precision highp float;
      uniform sampler2D uA0, uA1, uA2, uA3; uniform float uLoaded; uniform vec2 uTile; uniform vec3 uFog, uRim, uHoverCol;
      uniform float uTime, uLit, uFade, uNear;
      varying vec2 vUv; varying vec3 vTile; varying float vDist; varying float vHover; varying float vSeed;
      void main(){
        vec2 uv = gl_FrontFacing ? vUv : vec2(1.0 - vUv.x, vUv.y);   // seen from outside the tube the covers must still read left to right
        vec2 auv = (vTile.yz + vec2(uv.x, 1.0 - uv.y)) * uTile; auv.y = 1.0 - auv.y;
        vec3 c = uFog * 1.35;
        float a = vTile.x;
        if (a < uLoaded) { c = a < 0.5 ? texture2D(uA0, auv).rgb : a < 1.5 ? texture2D(uA1, auv).rgb : a < 2.5 ? texture2D(uA2, auv).rgb : texture2D(uA3, auv).rgb; }
        // rounded corners and a hairline rim so the screens read as objects, not a texture
        vec2 q = abs(uv - 0.5) * vec2(1.75, 1.0) - vec2(0.875, 0.5) + 0.04;
        float r = length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - 0.04;      // signed distance to the rounded rectangle (negative inside)
        float corner = 1.0 - smoothstep(-0.004, 0.004, r);
        float border = 1.0 - smoothstep(0.0, 0.014, -r);
        vec3 rim = mix(uRim, uHoverCol, vHover);
        c = mix(c, rim, border * 0.8);
        c = mix(c, uHoverCol, vHover * 0.12);
        float lit = uLit * (0.18 + 0.82 * exp(-vDist * uFade)) * (1.0 + vHover * 0.35);
        lit *= smoothstep(0.0, uNear, vDist);                               // screens the camera is passing through fade rather than clip
        c = mix(uFog, c * lit + uFog * (1.0 - lit) * 0.6, 1.0);
        float fog = 1.0 - exp(-vDist * uFade * 0.55);
        c = mix(c, uFog, fog);
        gl_FragColor = vec4(c, corner * smoothstep(0.0, uNear, vDist)); }`,
    transparent: true, side: THREE.DoubleSide });
  wall.material = mat; wall.frustumCulled = false;
  scene.add(wall);
  load();
  resize();
  if (!reduced) renderer.compileAsync(scene, camera).then(wake).catch(wake); else wake();
  report("live");
}

/* ---- the atlases arrive one by one; the intro counts them ---- */
function load() {
  let done = 0; const n = ATLAS.atlases;
  progress(0, n);
  for (let a = 0; a < n; a++) {
    const img = new Image(); img.decoding = "async";
    img.onload = () => {
      const tex = new THREE.Texture(img); tex.colorSpace = THREE.SRGBColorSpace; tex.minFilter = THREE.LinearMipmapLinearFilter; tex.generateMipmaps = true; tex.anisotropy = Math.min(4, renderer.capabilities.getMaxAnisotropy()); tex.needsUpdate = true;
      mat.uniforms["uA" + a].value = tex; mat.uniforms.uLoaded.value = Math.max(mat.uniforms.uLoaded.value, a + 1);
      progress(++done, n); if (done === n) ready = true; wake();
    };
    img.onerror = () => progress(++done, n);
    img.src = `assets/wall/atlas-${a}.jpg`;
  }
}

/* ---- camera per chapter ---- */
const pointer = { x: 0, y: 0, tx: 0, ty: 0 };
function pose(ch, dt) {
  const k = Math.min(LAST, Math.max(0, Math.floor(ch))), s = ch - k, kind = KIND[k], next = KIND[Math.min(LAST, k + 1)];
  const phone = small();
  let z0 = 1.4, fov = phone ? 78 : 62, op = 1, lit = 1, fade = 0.085;
  // where the camera stands along the axis, by chapter kind
  const inside = z => { v3.set(0, 0, z); look.set(0, 0, z - 30); };
  if (kind === "hero") inside(z0 - drift);
  else if (kind === "corridor") { inside(lerp(z0, -DEPTH + 5, smooth(0, 0.86, corrP)) - drift * (1 - corrP)); op = 1 - smooth(0.86, 1, corrP); }   // the last rings, then a cut to black
  else if (kind === "work") { v3.set(0, 0, -DEPTH - 6); look.set(0, 0, 0); op = 0.4 * smooth(0, 0.35, s); fade = 0.05; }          // past the end: looking back down the corridor
  else if (kind === "feature") { v3.set(0, 0, -DEPTH - 6); look.set(0, 0, 0); op = 0.4; fade = 0.05; }
  else if (kind === "stage") {                                                                  // outside: the archive as one object, slowly turning
    const d = phone ? 34 : 26, a = 0.95 + Math.sin(spin) * 0.3; v3.set(Math.sin(a) * d, 5 + Math.cos(spin * 0.6) * 2, -DEPTH / 2 + Math.cos(a) * d); look.set(0, 0, -DEPTH / 2); fov = phone ? 62 : 46;
  }
  if (kind === "feature" && next === "stage") op = lerp(0.4, 1, smooth(0.6, 1, s));
  if (kind !== "stage" && !phone) { v3.x += pointer.x * 0.5; v3.y += pointer.y * 0.35; look.x += pointer.x * 2.2; look.y += pointer.y * 1.6; }
  camera.position.lerp(v3, Math.min(1, dt * (kind === "corridor" ? 14 : 5)));
  camera.fov += (fov - camera.fov) * Math.min(1, dt * 4); camera.updateProjectionMatrix();
  camera.lookAt(look);
  mat.uniforms.uLit.value += (lit - mat.uniforms.uLit.value) * Math.min(1, dt * 4);
  mat.uniforms.uFade.value += (fade - mat.uniforms.uFade.value) * Math.min(1, dt * 4);
  canvas.style.opacity = op.toFixed(3);
}

/* ---- frames: only while something moves; suspended when covered or hidden ---- */
let idleTimer = 0;
function frame(now) {
  raf = 0;
  const dt = lastFrame ? Math.min(0.05, (now - lastFrame) / 1000) : 0.016; lastFrame = now;
  clock += dt;
  if (!reduced && !paused) { drift = (drift + dt * 0.35) % PITCH; spin += dt * 0.08; }
  pointer.x += (pointer.tx - pointer.x) * Math.min(1, dt * 4); pointer.y += (pointer.ty - pointer.y) * Math.min(1, dt * 4);
  t += (target - t) * Math.min(1, dt * 8); if (Math.abs(target - t) < 0.0005) t = target;
  if (reduced) t = target;
  mat.uniforms.uTime.value = clock; mat.uniforms.uHover.value = hovered;
  pose(t, dt);
  if (!covered() && !document.hidden) renderer.render(scene, camera);
  const moving = (!reduced && !paused) || t !== target || Math.abs(pointer.tx - pointer.x) > 0.002 || Math.abs(pointer.ty - pointer.y) > 0.002 || ready === false;
  if (moving && !covered() && !document.hidden) raf = requestAnimationFrame(frame); else lastFrame = 0;
}
function wake() { if (!raf && renderer) raf = requestAnimationFrame(frame); }
function resize() { if (!renderer) return; renderer.setSize(innerWidth, innerHeight, false); camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix(); measure(); onScroll(); }

/* ---- pointer: yaw in the hero, name the screen under the cursor in the hero and the corridor, click opens it ---- */
const ray = new THREE.Raycaster(), ndc = new THREE.Vector2();
const label = document.createElement("div"); label.className = "wall-label"; label.hidden = true; document.body.append(label);
function pick(e) {
  if (!wall || !ready || !(KIND[Math.round(t)] === "hero" || KIND[Math.round(t)] === "corridor") || canvas.style.opacity === "0") return -1;
  const el = document.elementFromPoint(e.clientX, e.clientY);
  if (!el || el.closest("a, button, input, select, dialog, h1, h2, p, dl, ol, aside, nav, header, .marquee")) return -1;
  ndc.set((e.clientX / innerWidth) * 2 - 1, -(e.clientY / innerHeight) * 2 + 1);
  ray.setFromCamera(ndc, camera);
  const hit = ray.intersectObject(wall, false).find(h => h.distance > 0.8 && h.distance < 11);
  return hit ? hit.instanceId : -1;
}
let hoverTimer = 0;
if (!matchMedia("(pointer: coarse)").matches) {
  document.addEventListener("pointermove", e => {
    pointer.tx = (e.clientX / innerWidth - 0.5) * 2; pointer.ty = -(e.clientY / innerHeight - 0.5) * 2; wake();
    if (hoverTimer) return;
    hoverTimer = setTimeout(() => {
      hoverTimer = 0;
      const id = pick(e);
      if (id !== hovered) { hovered = id; document.body.classList.toggle("over-wall", id >= 0); wake(); }
      if (id >= 0) { const p = DATA[id]; label.innerHTML = `<b>${p.title}</b><span>${p.kind}</span>`; label.hidden = false; }
      else label.hidden = true;
      label.style.transform = `translate(${e.clientX + 18}px, ${e.clientY + 18}px)`;
    }, 40);
  });
  document.addEventListener("click", e => {
    if (hovered < 0 || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    if (pick(e) !== hovered) return;
    dispatchEvent(new CustomEvent("portfolio:open", { detail: { slug: DATA[hovered].slug } }));
  });
  document.addEventListener("scroll", () => { if (hovered >= 0) { hovered = -1; label.hidden = true; document.body.classList.remove("over-wall"); } }, { passive: true });
}

/* ---- lifecycle ---- */
addEventListener("scroll", onScroll, { passive: true });
addEventListener("resize", resize);
addEventListener("portfolio:motion", e => { paused = e.detail.paused; wake(); });
addEventListener("portfolio:layout", () => { measure(); onScroll(); });                // the page changed height (catalogue reveal, pin setup)
motionQuery.addEventListener("change", () => { reduced = motionQuery.matches; wake(); });
canvas.addEventListener("webglcontextlost", e => { e.preventDefault(); cancelAnimationFrame(raf); raf = 0; if (++lost > 1) report("static"); });
canvas.addEventListener("webglcontextrestored", () => { if (lost <= 1 && renderer) wake(); });
document.addEventListener("visibilitychange", () => { if (document.hidden) { cancelAnimationFrame(raf); raf = 0; lastFrame = 0; } else wake(); });
window.__scene = { get t() { return t; }, get target() { return target; }, get renderer() { return renderer; }, get ready() { return ready; }, get covered() { return covered(); }, get corridor() { return corrP; }, get z() { return camera ? camera.position.z : null; }, get hovered() { return hovered; }, pickAt: (x, y) => pick({ clientX: x, clientY: y }), DEPTH, N };

function supported() {
  try { const c = document.createElement("canvas"); return !!(c.getContext("webgl2") || c.getContext("webgl")); } catch (_) { return false; }
}
if (!supported()) { report("static"); progress(1, 1); }
else {
  const start = () => { try { build(); } catch (e) { console.warn("scene:", e); report("static"); progress(1, 1); } };
  if (document.readyState === "complete") requestAnimationFrame(start); else addEventListener("load", () => requestAnimationFrame(start), { once: true });
}
