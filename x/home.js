// ATELIER X home film. One camera dives through the work: the stacked wall, a flash, a tunnel lined with projects,
// four chapters in a field of running screens, and a sphere made of every project. Every screen is a real project.
import * as THREE from "three";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { ShaderPass } from "three/addons/postprocessing/ShaderPass.js";
import { RGBShiftShader } from "three/addons/shaders/RGBShiftShader.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";

const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
const phone = innerWidth < 760;
const $ = (s) => document.querySelector(s);
const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const smooth = (a, b, x) => { const t = clamp((x - a) / (b - a)); return t * t * (3 - 2 * t); };
const rand = ((s) => () => ((s = Math.imul(s ^ (s >>> 15), 1 | s) + 0x6d2b79f5 | 0) >>> 0) / 4294967296)(20261104);
const A = 1.614;

// ---------- camera path: scroll progress to depth ----------
const KEYS = [[0, 9.5], [0.08, 9.5], [0.2, -2], [0.32, -74], [0.9, -182], [1, -206]];
function camZ(p) {
  for (let i = 1; i < KEYS.length; i++) if (p <= KEYS[i][0]) { const [a, za] = KEYS[i - 1], [b, zb] = KEYS[i]; const t = (p - a) / (b - a || 1); const e = i === 2 || i === 5 ? t * t * (3 - 2 * t) : t; return za + (zb - za) * e; }
  return KEYS[KEYS.length - 1][1];
}
const HERO_Z = phone ? 14 : 9.5; KEYS[0][1] = KEYS[1][1] = HERO_Z;

// ---------- renderer and post ----------
const canvas = $("#gl");
let renderer;
try { renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: "high-performance" }); }
catch (e) { document.documentElement.classList.add("nogl"); throw e; }
renderer.setClearColor(0x000000, 1); renderer.outputColorSpace = THREE.SRGBColorSpace;
const scene = new THREE.Scene(); scene.fog = new THREE.FogExp2(0x000000, 0.024);
const cam = new THREE.PerspectiveCamera(phone ? 62 : 42, 1, 0.1, 400);
const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, cam));
const bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), 0.55, 0.5, 0.88); composer.addPass(bloom);
const shift = new ShaderPass(RGBShiftShader); composer.addPass(shift);
composer.addPass(new OutputPass());
canvas.addEventListener("webglcontextlost", (e) => { e.preventDefault(); document.documentElement.classList.add("nogl"); });

// ---------- starfield ----------
{
  const n = phone ? 2800 : 6000, pos = new Float32Array(n * 3), col = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) {
    pos[i * 3] = (rand() - 0.5) * 140; pos[i * 3 + 1] = (rand() - 0.5) * 90; pos[i * 3 + 2] = 30 - rand() * 270;
    const k = 0.45 + rand() * 0.55, b = rand() < 0.18; col[i * 3] = b ? k * 0.7 : k; col[i * 3 + 1] = b ? k * 0.85 : k; col[i * 3 + 2] = k;
  }
  const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.BufferAttribute(pos, 3)); g.setAttribute("color", new THREE.BufferAttribute(col, 3));
  const dot = document.createElement("canvas"); dot.width = dot.height = 32; const dg = dot.getContext("2d"), rg = dg.createRadialGradient(16, 16, 0, 16, 16, 16);
  rg.addColorStop(0, "#fff"); rg.addColorStop(0.25, "rgba(255,255,255,.55)"); rg.addColorStop(1, "rgba(255,255,255,0)"); dg.fillStyle = rg; dg.fillRect(0, 0, 32, 32);
  scene.add(new THREE.Points(g, new THREE.PointsMaterial({ size: 0.16, map: new THREE.CanvasTexture(dot), vertexColors: true, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, fog: false })));
}

// ---------- textures: covers downscaled once, shared everywhere ----------
const manifest = await (await fetch("home.json")).json();
const NC = 64, covers = new Map();
function coverTex(slug) {
  if (covers.has(slug)) return covers.get(slug);
  const c = document.createElement("canvas"); c.width = 640; c.height = Math.round(640 / A);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4;
  let go; const started = new Promise((r) => (go = r));
  t.userData.load = () => { go(); return t.userData.ready; };
  t.userData.ready = started.then(() => new Promise((res) => {
    const img = new Image(); img.decoding = "async";
    img.onload = () => { const g = c.getContext("2d"); const s = Math.max(c.width / img.width, c.height / img.height); g.drawImage(img, (c.width - img.width * s) / 2, (c.height - img.height * s) / 2, img.width * s, img.height * s); t.needsUpdate = true; res(true); };
    img.onerror = () => res(false); img.src = `c/${slug}.jpg`;
  }));
  covers.set(slug, t); return t;
}
const slugs = manifest.slice(0, NC).map((m) => m.slug);

// ---------- screens ----------
const panelGeo = new THREE.PlaneGeometry(A, 1);
const edgeGeo = new THREE.EdgesGeometry(new THREE.PlaneGeometry(A * 1.035, 1.055));
const glowGeo = new THREE.PlaneGeometry(A * 1.2, 1.2);
const glowTex = (() => { const c = document.createElement("canvas"); c.width = 256; c.height = 160; const g = c.getContext("2d"), r = g.createRadialGradient(128, 80, 10, 128, 80, 128); r.addColorStop(0, "rgba(70,150,255,.55)"); r.addColorStop(1, "rgba(70,150,255,0)"); g.fillStyle = r; g.fillRect(0, 0, 256, 160); return new THREE.CanvasTexture(c); })();
const edgeMat = new THREE.LineBasicMaterial({ color: 0x9fd0ff, transparent: true, opacity: 0.5 });
function screen(slug, { glow = true, edge = true, tint = 0xe9edf2 } = {}) {
  const mat = new THREE.MeshBasicMaterial({ map: coverTex(slug), color: tint, toneMapped: false });
  const g = new THREE.Group(), mesh = new THREE.Mesh(panelGeo, mat); g.add(mesh);
  let gl = null, ed = null;
  if (glow) { gl = new THREE.Mesh(glowGeo, new THREE.MeshBasicMaterial({ map: glowTex, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, opacity: 0.2 })); gl.position.z = -0.02; g.add(gl); }
  if (edge) { ed = new THREE.LineSegments(edgeGeo, edgeMat); g.add(ed); }
  return { g, mesh, mat, glow: gl, slug, cover: mat.map, video: null };
}

// set A: the wall (hero), explodes outward as the camera passes through it
const WALL = phone ? 16 : 32, COLS = 4;
const wall = slugs.slice(0, WALL).map((slug, i) => {
  const s = screen(slug); scene.add(s.g);
  const L = Math.floor(i / 16), r = Math.floor((i % 16) / COLS), c = i % COLS;
  s.stacked = new THREE.Vector3((c - (COLS - 1) / 2) * (A + 0.16) + (phone ? 0 : 1.9), (1.5 - r) * 1.16 + (phone ? 1.4 + Math.max(0, 2.2 - innerHeight / innerWidth) * 4.2 : 0.25), -L * 0.62);
  const a = Math.atan2(s.stacked.y - 0.3, s.stacked.x - (phone ? 0 : 1.9)) + (rand() - 0.5) * 0.6, rad = 7 + rand() * 9;
  s.out = new THREE.Vector3(Math.cos(a) * rad * 1.3, Math.sin(a) * rad * 0.8, -4 - rand() * 14);
  s.spin = (rand() - 0.5) * 0.9; s.bob = rand() * 6.28; s.scale = 1;
  return s;
});

// set B: the field, four chapters with their flagship near the camera
const CH = [["florida-flight-delays", 0.39, 1], ["retail-dbt", 0.53, 1], ["us-retail-forecast", 0.67, -1], ["sec-10k-rag", 0.81, 1]];
const fieldSlugs = [...new Set([...CH.map((c) => c[0]), ...slugs.slice(WALL)])].slice(0, phone ? 28 : 44);
const field = fieldSlugs.map((slug, i) => {
  const s = screen(slug); scene.add(s.g);
  const ch = CH.find((c) => c[0] === slug);
  if (ch) { s.pos = new THREE.Vector3(ch[2] * (phone ? 0.9 : 2.25), phone ? -1.35 : -1.15, camZ(ch[1]) - (phone ? 5.4 : 6.4)); s.scale = phone ? 1.55 : 1.85; s.feature = true; }
  else { const a = rand() * Math.PI * 2, rad = 2.8 + rand() * (phone ? 4 : 8); s.pos = new THREE.Vector3(Math.cos(a) * rad * 1.25, Math.sin(a) * rad * 0.62, -78 - (i / fieldSlugs.length) * 104 - rand() * 4); s.scale = 0.8 + rand() * 1.5; }
  s.spin = (rand() - 0.5) * 0.5; s.bob = rand() * 6.28;
  return s;
});

// the tunnel: four walls of projects rushing past, tinted blue
const tunnel = new THREE.Group(); scene.add(tunnel);
{
  const W = phone ? 4.4 : 7, H = phone ? 6 : 4.4, step = 1.72, z0 = -8, z1 = -76; let k = 0;
  for (let z = z0; z > z1; z -= step) {
    const ring = [];
    for (let x = -W / 2 + 0.85; x <= W / 2 - 0.8; x += A + 0.12) { ring.push([x, H / 2, Math.PI / 2, 0]); ring.push([x, -H / 2, -Math.PI / 2, 0]); }
    for (let y = -H / 2 + 0.55; y <= H / 2 - 0.5; y += 1.1) { ring.push([-W / 2, y, 0, Math.PI / 2]); ring.push([W / 2, y, 0, -Math.PI / 2]); }
    ring.forEach(([x, y, rx, ry]) => {
      const m = new THREE.Mesh(panelGeo, new THREE.MeshBasicMaterial({ map: coverTex(slugs[k++ % NC]), color: 0x6fa8ff, toneMapped: false }));
      m.position.set(x, y, z - (rand() * 0.3)); m.rotation.set(rx, ry, 0); if (ry) m.rotation.order = "YXZ"; tunnel.add(m);
    });
  }
  const frameMat = new THREE.LineBasicMaterial({ color: 0x9fd0ff, transparent: true, opacity: 0.35 });
  for (let z = z0; z > z1; z -= step * 6) { const f = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.PlaneGeometry(W, H)), frameMat); f.position.z = z; tunnel.add(f); }
}

// the sphere: every project, facing out
const sphere = new THREE.Group(); scene.add(sphere);
const SPH_Z = -224, SPH_R = phone ? 6 : 8.2;
{
  const n = phone ? 120 : 200, gold = Math.PI * (3 - Math.sqrt(5));
  for (let i = 0; i < n; i++) {
    const y = 1 - (i / (n - 1)) * 2, r = Math.sqrt(1 - y * y), th = gold * i;
    const m = new THREE.Mesh(panelGeo, new THREE.MeshBasicMaterial({ map: coverTex(slugs[i % NC]), color: 0xc8d2e0, toneMapped: false, side: THREE.DoubleSide }));
    m.position.set(Math.cos(th) * r * SPH_R, y * SPH_R, Math.sin(th) * r * SPH_R); m.scale.setScalar(0.85);
    m.lookAt(m.position.clone().multiplyScalar(2)); sphere.add(m);
  }
  sphere.position.z = SPH_Z;
}

// ---------- preload: fonts + the wall's covers (real progress) ----------
const first = wall.slice(0, phone ? 8 : 16).map((s) => s.cover.userData.load());
wall.slice(phone ? 8 : 16).forEach((s) => s.cover.userData.load());
let loaded = 0; const total = first.length + 2;
const tick = () => { loaded++; const k = Math.round((loaded / total) * 100); $("#pct").textContent = k + "%"; $("#pre circle").style.strokeDashoffset = 100 - k; };
document.fonts.load("300 40px 'Inter Tight'").then(tick); document.fonts.load("400 12px 'Geist Mono'").then(tick);
first.forEach((pr) => pr.then(tick));

// ---------- video pool: only the nearest screens decode ----------
const live = [...wall, ...field], POOL = phone ? 6 : 12, pool = [];
for (let k = 0; k < POOL; k++) { const v = document.createElement("video"); v.muted = true; v.loop = true; v.playsInline = true; v.preload = "auto"; v.setAttribute("muted", ""); v.crossOrigin = "anonymous"; pool.push({ v, tex: null, owner: null }); }
function assign(s, slot) {
  if (slot.owner) { const o = slot.owner; o.video = null; o.mat.map = o.cover; o.mat.needsUpdate = true; }
  slot.owner = s; s.video = slot; slot.v.src = `../${s.slug}/loop.webm`;
  slot.v.onplaying = () => { if (slot.owner !== s) return; if (!slot.tex) { slot.tex = new THREE.VideoTexture(slot.v); slot.tex.colorSpace = THREE.SRGBColorSpace; } s.mat.map = slot.tex; s.mat.needsUpdate = true; };
  slot.v.play().catch(() => {});
}
const fr = new THREE.Frustum(), pm = new THREE.Matrix4(), tmp = new THREE.Vector3();
function schedule() {
  pm.multiplyMatrices(cam.projectionMatrix, cam.matrixWorldInverse); fr.setFromProjectionMatrix(pm);
  const d = (s) => s.g.position.distanceTo(cam.position);
  const vis = live.filter((s) => s.g.visible && fr.containsPoint(s.g.position) && d(s) < 46).sort((a, b) => d(a) - d(b)).slice(0, POOL);
  const keep = new Set(vis), free = pool.filter((sl) => !sl.owner || !keep.has(sl.owner));
  vis.filter((s) => !s.video).forEach((s) => { const sl = free.shift(); if (sl) assign(s, sl); });
  pool.forEach((sl) => { if (sl.owner && !keep.has(sl.owner) && !sl.v.paused) sl.v.pause(); else if (sl.owner && keep.has(sl.owner) && sl.v.paused) sl.v.play().catch(() => {}); });
  $("#running").textContent = String(pool.filter((sl) => sl.owner && !sl.v.paused).length).padStart(2, "0");
}

// ---------- tags on the nearest screens ----------
const byslug = new Map(manifest.map((m, i) => [m.slug, { ...m, n: i + 1 }]));
const tags = Array.from({ length: phone ? 1 : 3 }, () => { const d = document.createElement("div"); d.className = "tag"; d.setAttribute("aria-hidden", "true"); document.body.appendChild(d); return d; });
function placeTags(on) {
  const cand = on ? live.filter((s) => { if (!s.g.visible) return false; tmp.copy(s.g.position).project(cam); return tmp.z < 1 && Math.abs(tmp.x) < 0.8 && Math.abs(tmp.y) < 0.78; }).sort((a, b) => a.g.position.distanceTo(cam.position) - b.g.position.distanceTo(cam.position)).slice(0, tags.length) : [];
  tags.forEach((t, k) => {
    const s = cand[k]; if (!s) { t.style.opacity = 0; return; }
    tmp.set(-A / 2, 0.62, 0).applyMatrix4(s.mesh.matrixWorld).project(cam);
    const m = byslug.get(s.slug), title = m.title.length > 34 ? m.title.slice(0, 33) + "…" : m.title;
    if (t.dataset.k !== s.slug) { t.dataset.k = s.slug; t.innerHTML = `<b>[${String(m.n).padStart(3, "0")}] ${title}</b>${m.kind.split(" · ").slice(0, 2).join(" / ")} / ${m.year}`; }
    t.style.transform = `translate(${Math.round((tmp.x * 0.5 + 0.5) * innerWidth + 14)}px, ${Math.round((-tmp.y * 0.5 + 0.5) * innerHeight - 30)}px)`; t.style.opacity = 1;
  });
}

// ---------- scroll ----------
let lenis = null, prog = 0, vel = 0;
if (!reduce && window.Lenis) { lenis = new Lenis({ autoRaf: true, lerp: 0.08, wheelMultiplier: 0.85 }); window.__lenis = lenis; lenis.on("scroll", (e) => { prog = e.progress || 0; vel = e.velocity || 0; }); }
else addEventListener("scroll", () => { prog = scrollY / Math.max(1, document.documentElement.scrollHeight - innerHeight); }, { passive: true });
document.addEventListener("focusin", (e) => { const el = e.target.closest(".line, .cta"); if (!el || reduce) return; const f = (+el.dataset.from + Math.min(1, +el.dataset.to)) / 2, h = document.documentElement.scrollHeight - innerHeight; lenis ? lenis.scrollTo(f * h, { immediate: true }) : scrollTo(0, f * h); });
addEventListener("keydown", (e) => { if (!lenis) return; const h = document.documentElement.scrollHeight - innerHeight; if (e.key === "End") lenis.scrollTo(h); if (e.key === "Home") lenis.scrollTo(0); });

const lines = [...document.querySelectorAll(".line, .cta")], idx = [...document.querySelectorAll(".index span")];
const mods = [["00", "THE WORK, STACKED"], ["00", "THE TUNNEL"], ["01", "FLORIDA FLIGHT DELAYS"], ["02", "RETAIL PIPELINE IN DBT"], ["03", "US RETAIL SALES FORECAST"], ["04", "ASK THE 10-K"], ["05", "THE INDEX"]];
function resize() {
  const dpr = Math.min(devicePixelRatio, 2);
  renderer.setPixelRatio(dpr); renderer.setSize(innerWidth, innerHeight, false);
  composer.setPixelRatio(Math.min(dpr, phone ? 1.5 : 1.75)); composer.setSize(innerWidth, innerHeight);
  cam.aspect = innerWidth / innerHeight; cam.updateProjectionMatrix();
}
addEventListener("resize", resize); resize();
const ptr = { x: 0, y: 0 }; addEventListener("pointermove", (e) => { ptr.x = e.clientX / innerWidth - 0.5; ptr.y = e.clientY / innerHeight - 0.5; }, { passive: true });

// adaptive quality: if the first 90 frames run slow, drop the post resolution
let slow = 0, lastT = performance.now(), frame = 0, introK = 0, introStart = 0, hidden = false;
document.addEventListener("visibilitychange", () => { hidden = document.hidden; if (!hidden) { lastT = performance.now(); requestAnimationFrame(loop); } pool.forEach((sl) => hidden ? sl.v.pause() : null); });
const t0 = performance.now(), look = new THREE.Vector3();
function loop() {
  if (hidden) return;
  const now = performance.now(), dt = now - lastT; lastT = now;
  if (frame < 90) { if (dt > 24) slow++; if (frame === 89 && slow > 40) composer.setPixelRatio(1); }
  const t = (now - t0) / 1000;
  if (introStart && introK < 1) introK = reduce ? 1 : clamp((now - introStart) / 2600);
  const p = prog, ik = 1 - Math.pow(1 - introK, 3), z = camZ(p) + (1 - ik) * 26;
  const burst = smooth(0.08, 0.2, p), inTunnel = smooth(0.19, 0.22, p) * (1 - smooth(0.31, 0.34, p));
  cam.position.set(Math.sin(t * 0.13) * 0.5 * (1 - burst) + ptr.x * 0.8 * (1 - inTunnel), -0.5 + Math.cos(t * 0.11) * 0.25 - ptr.y * 0.5 * (1 - inTunnel) + (phone ? 0.6 : 0), z);
  look.set(ptr.x * 0.6 * burst * (1 - inTunnel), (phone ? 0.3 : 0) - ptr.y * 0.3 * burst, z - 12); cam.lookAt(look);
  cam.rotation.z = Math.sin(t * 0.09) * 0.012 + clamp(vel * -0.0009, -0.05, 0.05) + inTunnel * Math.sin(p * 40) * 0.02;
  // wall: stacked, then blown outward around the camera
  wall.forEach((s) => {
    s.g.visible = p < 0.3;
    s.g.position.lerpVectors(s.stacked, s.out, burst); s.g.position.y += Math.sin(t * 0.6 + s.bob) * 0.05 * burst;
    s.g.rotation.set(Math.sin(t * 0.4 + s.bob) * 0.03 * burst, s.spin * burst, 0);
  });
  field.forEach((s) => {
    s.g.visible = p > 0.26 && p < 0.95;
    s.g.position.copy(s.pos); s.g.position.y += Math.sin(t * 0.6 + s.bob) * 0.06; s.g.scale.setScalar(s.scale);
    s.g.rotation.set(Math.sin(t * 0.4 + s.bob) * 0.03, s.spin + Math.sin(t * 0.3 + s.bob) * 0.04, 0);
    const near = clamp(1 - (s.g.position.distanceTo(cam.position) - 6) / 30); if (s.glow) s.glow.material.opacity = 0.16 + near * 0.35;
  });
  tunnel.visible = p > 0.16 && p < 0.36;
  sphere.visible = p > 0.8; sphere.rotation.y = t * 0.05 + p * 2; sphere.rotation.x = Math.sin(t * 0.07) * 0.1;
  // flash where the wall stood
  const fl = Math.max(0, 1 - Math.abs(p - 0.2) / 0.035);
  $("#flash").style.opacity = reduce ? 0 : (fl * fl * 0.95).toFixed(3);
  bloom.strength = 0.55 + fl * 1.4 + inTunnel * 0.35;
  shift.uniforms.amount.value = reduce ? 0 : 0.0005 + inTunnel * 0.0025 + Math.min(0.004, Math.abs(vel) * 0.00006);
  // DOM: hero, HUD, counter, lines
  $(".hero").style.opacity = 1 - smooth(0.02, 0.08, p); $(".hero").style.visibility = p > 0.1 ? "hidden" : "visible";
  $(".scrollcue").style.opacity = introK >= 1 ? 1 - smooth(0.01, 0.05, p) : 0;
  $(".foot").style.opacity = smooth(0.05, 0.1, p) * (1 - smooth(0.9, 0.93, p));
  $(".index").style.opacity = smooth(0.32, 0.36, p) * (1 - smooth(0.87, 0.9, p));
  const c = $(".counter"); c.style.opacity = smooth(0.21, 0.23, p) * (1 - smooth(0.3, 0.32, p)); $("#cnt").textContent = String(tunnel.children.filter((m) => m.isMesh && m.position.z > cam.position.z).length).padStart(3, "0");
  lines.forEach((el) => { const a = +el.dataset.from, b = +el.dataset.to, o = smooth(a, a + 0.025, p) * (1 - smooth(b - 0.025, b, p)); el.style.opacity = o.toFixed(3); el.style.transform = `translate(-50%, calc(-50% + ${((1 - smooth(a, a + 0.035, p)) * 18).toFixed(1)}px))`; if (el.classList.contains("cta")) el.style.pointerEvents = o > 0.5 ? "auto" : "none"; });
  const m = p < 0.19 ? 0 : p < 0.33 ? 1 : p < 0.46 ? 2 : p < 0.6 ? 3 : p < 0.74 ? 4 : p < 0.9 ? 5 : 6;
  idx.forEach((s, k) => s.classList.toggle("on", k === m - 2));
  if ($("#modt").textContent !== mods[m][1]) { $("#modn").textContent = mods[m][0]; $("#modt").textContent = mods[m][1]; if (window.xSound) window.xSound.blip(660 + m * 70); }
  if (frame++ % 12 === 0 && videoOn) schedule();
  placeTags(p > 0.34 && p < 0.9 && !lines.some((el) => +el.style.opacity > 0.05));
  composer.render();
  if (!reduce) requestAnimationFrame(loop);
}
await Promise.race([phone ? document.fonts.ready.then(() => new Promise((r) => setTimeout(r, 1200))) : Promise.all(first), new Promise((r) => setTimeout(r, 6000))]);
$("#pct").textContent = "100%"; $("#pre circle").style.strokeDashoffset = 0;
let videoOn = false;
const later = () => { slugs.slice(WALL).forEach((s) => coverTex(s).userData.load()); if (!reduce) setTimeout(() => (videoOn = true), 1200); };
(window.requestIdleCallback || setTimeout)(later, { timeout: 2500 });
setTimeout(() => { $("#pre").classList.add("done"); introStart = performance.now(); document.body.classList.add("in"); }, reduce ? 0 : 450);
if (reduce) { introK = 1; prog = 0; const still = () => loop(); still(); Promise.all(first).then(still); setTimeout(still, 1500); addEventListener("resize", still); }
else requestAnimationFrame(loop);
