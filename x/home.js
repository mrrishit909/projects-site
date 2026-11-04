// ATELIER X home film, shot for shot after the owner's reference: a server cube on a mountain under a storm sky, a flash,
// a blue glass tunnel, the cube exploded with HUD tags, a swarm of code panels (real code from the public repos), the
// project screens, and an eye that grows until it fills the frame. Every object is procedural; the sky is a generated plate.
import * as THREE from "three";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { ShaderPass } from "three/addons/postprocessing/ShaderPass.js";
import { RGBShiftShader } from "three/addons/shaders/RGBShiftShader.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";

const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
const phone = innerWidth < 768;
const $ = (s) => document.querySelector(s);
const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const smooth = (a, b, x) => { const t = clamp((x - a) / (b - a)); return t * t * (3 - 2 * t); };
const lerp = (a, b, t) => a + (b - a) * t;
const rand = ((s) => () => ((s = Math.imul(s ^ (s >>> 15), 1 | s) + 0x6d2b79f5 | 0) >>> 0) / 4294967296)(20261104);
const A = 1.614;

// ---------- renderer and post ----------
const canvas = $("#gl");
let renderer;
try { renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: "high-performance" }); }
catch (e) { document.documentElement.classList.add("nogl"); throw e; }
renderer.setClearColor(0x000000, 1); renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.05;
const scene = new THREE.Scene(); scene.fog = new THREE.FogExp2(0x000000, 0.02);
const cam = new THREE.PerspectiveCamera(phone ? 60 : 40, 1, 0.1, 600); scene.add(cam);
const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, cam));
const bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), 0.7, 0.55, 0.82); composer.addPass(bloom);
const zoom = new ShaderPass({
  uniforms: { tDiffuse: { value: null }, strength: { value: 0 } },
  vertexShader: "varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }",
  fragmentShader: `uniform sampler2D tDiffuse; uniform float strength; varying vec2 vUv;
    void main(){ vec2 d = vUv - 0.5; vec4 c = vec4(0.0); const int N = ${phone ? 8 : 14};
      for (int i = 0; i < N; i++) { float s = 1.0 - strength * float(i) / float(N); c += texture2D(tDiffuse, 0.5 + d * s); }
      gl_FragColor = c / float(N); }`,
}); composer.addPass(zoom);
const shift = new ShaderPass(RGBShiftShader); composer.addPass(shift);
composer.addPass(new OutputPass());
canvas.addEventListener("webglcontextlost", (e) => { e.preventDefault(); document.documentElement.classList.add("nogl"); });

// ---------- shared helpers ----------
const Q = phone ? 2 : 3, ANI = renderer.capabilities.getMaxAnisotropy();
function canvasTex(w, h, draw, srgb = true, q = Q) { const c = document.createElement("canvas"); c.width = Math.round(w * q); c.height = Math.round(h * q); const g = c.getContext("2d"); g.scale(q, q); draw(g, w, h); const t = new THREE.CanvasTexture(c); if (srgb) t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = ANI; return t; }
const glowTex = canvasTex(256, 256, (g) => { const r = g.createRadialGradient(128, 128, 0, 128, 128, 128); r.addColorStop(0, "rgba(255,255,255,1)"); r.addColorStop(0.18, "rgba(190,225,255,.75)"); r.addColorStop(0.5, "rgba(60,140,255,.22)"); r.addColorStop(1, "rgba(30,90,255,0)"); g.fillStyle = r; g.fillRect(0, 0, 256, 256); });
const sprite = (scale, color = 0xffffff, opacity = 1) => { const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTex, color, transparent: true, opacity, depthWrite: false, blending: THREE.AdditiveBlending, fog: false, toneMapped: false })); s.scale.setScalar(scale); return s; };

// ---------- the sky plate (also the environment for the metal) ----------
const skyTex = new THREE.TextureLoader().load(phone ? "img/sky-m.jpg" : "img/sky-d.jpg", (t) => { envFrom(t); });
skyTex.colorSpace = THREE.SRGBColorSpace;
const sky = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), new THREE.MeshBasicMaterial({ map: skyTex, fog: false, depthWrite: false, toneMapped: false, transparent: true, color: 0xb9c9e0 }));
sky.renderOrder = -1; cam.add(sky);
const pmrem = new THREE.PMREMGenerator(renderer);
let envMap = null; const metals = [];
function envFrom(t) { const e = t.clone(); e.mapping = THREE.EquirectangularReflectionMapping; e.needsUpdate = true; envMap = pmrem.fromEquirectangular(e).texture; metals.forEach((m) => { m.envMap = envMap; m.needsUpdate = true; }); }

scene.add(new THREE.AmbientLight(0x6f88b0, 0.5));
const moon = new THREE.DirectionalLight(0xbcd2ff, 1.4); moon.position.set(-6, 10, 8); scene.add(moon);

// ---------- 1. the server cube ----------
const rackTex = canvasTex(256, 256, (g, w, h) => {
  g.fillStyle = "#59636f"; g.fillRect(0, 0, w, h);
  g.strokeStyle = "#a9b4c2"; g.lineWidth = 10; g.strokeRect(5, 5, w - 10, h - 10);
  g.fillStyle = "#3a434f"; g.fillRect(18, 18, w - 36, h - 36);
  for (let i = 0; i < 4; i++) {
    const y = 30 + i * 52;
    g.fillStyle = "#1a2029"; g.fillRect(28, y, w - 56, 40);
    g.fillStyle = "#cfe8ff"; g.fillRect(28, y, w - 56, 3);
    g.fillStyle = "#3d5f8c"; g.fillRect(28, y + 37, w - 56, 2);
  }
  g.fillStyle = "#8fe1ff"; g.fillRect(14, 22, 4, h - 44); g.fillRect(w - 18, 22, 4, h - 44);
});
const rackGlow = canvasTex(256, 256, (g, w, h) => {
  g.fillStyle = "#000"; g.fillRect(0, 0, w, h);
  for (let i = 0; i < 4; i++) { g.fillStyle = "#9fd4ff"; g.fillRect(28, 30 + i * 52, w - 56, 3); }
  g.fillStyle = "#6fd0ff"; g.fillRect(14, 22, 4, h - 44); g.fillRect(w - 18, 22, 4, h - 44);
});
const cube = new THREE.Group(); scene.add(cube);
const rackMat = new THREE.MeshStandardMaterial({ map: rackTex, emissiveMap: rackGlow, emissive: 0x7fb8ff, emissiveIntensity: 0.7, metalness: 0.8, roughness: 0.4, color: 0xd8e0ea });
metals.push(rackMat);
const modGeo = new THREE.BoxGeometry(1, 1, 1);
for (let x = -1; x <= 1; x++) for (let y = -1; y <= 1; y++) for (let z = -1; z <= 1; z++) {
  if (!x && !y && (!z || z === 1)) continue;
  const m = new THREE.Mesh(modGeo, rackMat); m.position.set(x * 1.24, y * 1.24, z * 1.24); m.userData.home = m.position.clone(); cube.add(m);
}
const coreMat = new THREE.MeshBasicMaterial({ color: new THREE.Color(3, 3.3, 3.6), toneMapped: false });
const core = new THREE.Mesh(modGeo, coreMat); core.scale.setScalar(0.9); cube.add(core);
const coreLight = new THREE.PointLight(0x8fd0ff, 30, 9, 1.6); cube.add(coreLight);
const coreGlow = sprite(2.2, 0x9fd8ff, 0.5); cube.add(coreGlow);
const beam = new THREE.Mesh(new THREE.PlaneGeometry(0.5, 30), new THREE.MeshBasicMaterial({ map: canvasTex(64, 512, (g, w, h) => { const r = g.createLinearGradient(0, 0, w, 0); r.addColorStop(0, "rgba(120,190,255,0)"); r.addColorStop(0.5, "rgba(230,245,255,.9)"); r.addColorStop(1, "rgba(120,190,255,0)"); g.fillStyle = r; g.fillRect(0, 0, w, h); const f = g.createLinearGradient(0, 0, 0, h); f.addColorStop(0, "rgba(0,0,0,1)"); f.addColorStop(1, "rgba(0,0,0,0)"); g.globalCompositeOperation = "destination-out"; g.fillStyle = f; g.fillRect(0, 0, w, h); }), transparent: true, blending: THREE.AdditiveBlending, depthWrite: false, fog: false, toneMapped: false }));
beam.position.set(0, 16.5, 0); cube.add(beam);
const beamLow = beam.clone(); beamLow.rotation.z = Math.PI; beamLow.position.set(0, -16.5, 0); cube.add(beamLow);
cube.position.y = 0.55;

{
  const rock = new THREE.MeshStandardMaterial({ color: 0xa3b0c4, roughness: 0.8, metalness: 0.15, flatShading: true });
  const crag = () => { const g = new THREE.IcosahedronGeometry(1, 2), p = g.attributes.position; for (let i = 0; i < p.count; i++) { const k = 0.72 + rand() * 0.5; p.setXYZ(i, p.getX(i) * k, p.getY(i) * k * (p.getY(i) > 0 ? 1.4 : 1), p.getZ(i) * k); } g.computeVertexNormals(); return g; };
  [[-8.5, -5, -3, 5, 3.6, 3.5], [-11.5, -4.4, -9, 6, 5, 4], [8.8, -5.2, -2, 5, 3.4, 3.5], [12, -4, -9, 6, 5.5, 4], [0, -7.4, -5, 8, 2.2, 3]].forEach(([x, y, z, sx, sy, sz], i) => {
    const m = new THREE.Mesh(crag(), rock); metals.push(rock); m.position.set(phone ? x * 0.6 : x, y, z); m.scale.set(sx, sy, sz); m.rotation.set(i * 0.7, i * 1.3, i * 0.4); cube.add(m);
  });
}

// ---------- 2. the glass tunnel ----------
const TZ0 = -12, TZ1 = -140, TW = phone ? 2.4 : 3.3;
const tunnel = new THREE.Group(); scene.add(tunnel);
{
  const face = canvasTex(128, 128, (g, w, h) => { g.fillStyle = "#081c4a"; g.fillRect(0, 0, w, h); const r = g.createLinearGradient(0, 0, w, h); r.addColorStop(0, "rgba(90,150,255,.18)"); r.addColorStop(1, "rgba(4,12,40,.3)"); g.fillStyle = r; g.fillRect(0, 0, w, h); g.strokeStyle = "#bfe6ff"; g.lineWidth = 5; g.strokeRect(2, 2, w - 4, h - 4); });
  const edge = canvasTex(128, 128, (g, w, h) => { g.fillStyle = "#000"; g.fillRect(0, 0, w, h); g.strokeStyle = "#7fe0ff"; g.lineWidth = 4; g.strokeRect(2, 2, w - 4, h - 4); });
  const mat = new THREE.MeshStandardMaterial({ map: face, emissiveMap: edge, emissive: 0xffffff, emissiveIntensity: 0.6, metalness: 0.5, roughness: 0.18, transparent: true, opacity: 0.92 });
  metals.push(mat);
  const per = phone ? 7 : 9, n = Math.round(((TZ0 - TZ1) / 1.1) * per * 4);
  const inst = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), mat, n);
  const o = new THREE.Object3D(), col = new THREE.Color(); let k = 0;
  for (let z = TZ0; z > TZ1 && k < n; z -= 1.1) for (let side = 0; side < 4; side++) for (let j = 0; j < per && k < n; j++) {
    const along = (j / (per - 1) - 0.5) * TW * 2 * (1 + rand() * 0.08), depth = 0.25 + rand() * 1.6, sz = 0.35 + rand() * 0.9;
    const inward = TW + 0.5 - depth / 2;
    o.position.set(side < 2 ? along : (side === 2 ? -inward : inward), side < 2 ? (side === 0 ? inward : -inward) : along, z - rand() * 0.6);
    o.scale.set(side < 2 ? sz : depth, side < 2 ? depth : sz, 0.4 + rand() * 1.1); o.rotation.set(0, 0, 0); o.updateMatrix(); inst.setMatrixAt(k, o.matrix);
    col.setHSL(0.6 + rand() * 0.03, 0.95, 0.07 + rand() * 0.18); inst.setColorAt(k++, col);
  }
  inst.count = k; tunnel.add(inst);
  const frameMat = new THREE.MeshBasicMaterial({ color: new THREE.Color(0.4, 1.5, 1.9), toneMapped: false, fog: false });
  for (let z = TZ0 - 20; z > TZ1 + 10; z -= 34) {
    const f = new THREE.Group(), s = TW * 0.66, t = 0.03;
    [[0, s, 2 * s, t], [0, -s, 2 * s, t], [s, 0, t, 2 * s], [-s, 0, t, 2 * s]].forEach(([x, y, w, h]) => { const b = new THREE.Mesh(new THREE.PlaneGeometry(w, h), frameMat); b.position.set(x, y, 0); f.add(b); });
    f.position.z = z; tunnel.add(f);
  }
  const end = sprite(phone ? 9 : 12, 0xcfeaff, 1); end.position.z = TZ1 - 4; tunnel.add(end);
  const lamp = new THREE.PointLight(0x3f7fff, 14, 22, 1.4); lamp.name = "lamp"; tunnel.add(lamp);
}

// ---------- 3. the exploded cube (real code on the slabs) ----------
const snips = await (await fetch("snips.json")).json();
await Promise.race([document.fonts.load("400 20px 'Geist Mono'"), new Promise((r) => setTimeout(r, 2500))]);
// each snippet is drawn once per style and shared; 2x on desktop keeps the code crisp without filling the GPU
const codeCache = new Map();
function codeTex(sn, { w = 512, h = 300, panel = true } = {}) {
  const key = sn.f + sn.l[0] + panel; if (codeCache.has(key)) return codeCache.get(key);
  const t = canvasTex(w, h, (g) => {
    g.fillStyle = panel ? "rgba(6,14,42,.92)" : "#04102e"; g.fillRect(0, 0, w, h);
    if (panel) { g.strokeStyle = "rgba(140,190,255,.85)"; g.lineWidth = 3; g.strokeRect(1.5, 1.5, w - 3, h - 3); }
    g.font = "500 15px 'Geist Mono', monospace"; g.fillStyle = "#ff8f7a"; g.fillText("// " + sn.f, 22, 34);
    g.font = "400 16px 'Geist Mono', monospace";
    sn.l.forEach((l, i) => { g.fillStyle = i % 3 === 0 ? "#e8f3ff" : "#8fbaff"; g.fillText(l, 22, 64 + i * 22); });
  }, true, phone ? 1.5 : 2);
  codeCache.set(key, t); return t;
}
const shards = new THREE.Group(); const SHZ = -200; shards.position.z = SHZ; scene.add(shards);
const slabs = [];
{
  const glass = (sn) => { const t = codeTex(sn, { panel: false }); const m = new THREE.MeshStandardMaterial({ color: 0x24407a, emissive: 0xffffff, emissiveMap: t, emissiveIntensity: 1.2, metalness: 0.7, roughness: 0.12, transparent: true, opacity: 0.94 }); metals.push(m); return m; };
  const edgeMat = new THREE.LineBasicMaterial({ color: 0x9fd0ff, transparent: true, opacity: 0.8 });
  // three layers, each cut into slabs of different proportions, so the cube reads whole before it opens
  const cuts = [[[-1.5, -0.4], [-0.4, 0.5], [0.5, 1.5]], [[-1.5, 0.1], [0.1, 1.5]], [[-1.5, -0.8], [-0.8, 0.2], [0.2, 0.9], [0.9, 1.5]]];
  let k = 0;
  cuts.forEach((row, L) => row.forEach(([a, b], i) => {
    const alongX = L !== 1, y = (L - 1) * 1.04, w = b - a - 0.06, c = (a + b) / 2;
    const geo = new THREE.BoxGeometry(alongX ? w : 2.94, 0.98, alongX ? 2.94 : w);
    const mesh = new THREE.Mesh(geo, glass(snips[(k * 7) % snips.length]));
    mesh.add(new THREE.LineSegments(new THREE.EdgesGeometry(geo), edgeMat));
    mesh.position.set(alongX ? c : 0, y, alongX ? 0 : c);
    const dir = mesh.position.clone().add(new THREE.Vector3((rand() - 0.5) * 0.6, (rand() - 0.5) * 0.6, (rand() - 0.5) * 0.6)).normalize();
    slabs.push({ mesh, home: mesh.position.clone(), dir, spin: new THREE.Vector3(rand() - 0.5, rand() - 0.5, rand() - 0.5).multiplyScalar(0.7) });
    shards.add(mesh); k++;
  }));
  // debris: thin glowing sticks drifting around the cube
  const stick = new THREE.MeshBasicMaterial({ color: 0x24305a, transparent: true, opacity: 0.8 });
  for (let i = 0; i < (phone ? 14 : 26); i++) { const d = new THREE.Mesh(new THREE.BoxGeometry(0.04, 0.14, 0.5 + rand() * 0.8), stick); const a = rand() * 6.28, r = 4 + rand() * 7; d.position.set(Math.cos(a) * r, (rand() - 0.5) * 7, Math.sin(a) * r); d.rotation.set(rand() * 3, rand() * 3, 0); shards.add(d); }
}

// ---------- 4. code panels ----------
const CZ0 = -212, CZ1 = -318;
const panels = new THREE.Group(); scene.add(panels);
{
  const n = phone ? 40 : 64;
  for (let i = 0; i < n; i++) {
    const t = codeTex(snips[(i * 5 + 3) % snips.length]);
    const m = new THREE.Mesh(new THREE.PlaneGeometry(1.7, 1), new THREE.MeshBasicMaterial({ map: t, transparent: true, toneMapped: false, side: THREE.DoubleSide, opacity: 0.95 }));
    const a = rand() * 6.28, r = (phone ? 2.2 : 2.6) + rand() * (phone ? 2.4 : 4.6);
    m.position.set(Math.cos(a) * r * 1.3, Math.sin(a) * r * 0.75, lerp(CZ0, CZ1, Math.pow(i / n, 2.4)) - rand() * 3);
    m.scale.setScalar((phone ? 0.6 + rand() * 0.6 : 0.6 + rand() * 0.7) * (i < n / 3 ? 1.5 : 1)); m.rotation.set((rand() - 0.5) * 0.3, (rand() - 0.5) * 0.7, (rand() - 0.5) * 0.15);
    m.userData.bob = rand() * 6.28; panels.add(m);
  }
}

// ---------- 5. project screens (covers, the nearest ones play their loop) ----------
const manifest = await (await fetch("home.json")).json();
const NC = 64, covers = new Map();
function coverTex(slug) {
  if (covers.has(slug)) return covers.get(slug);
  const W = phone ? 720 : 1024, c = document.createElement("canvas"); c.width = W; c.height = Math.round(W / A);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = ANI;
  t.userData.load = () => t.userData.ready || (t.userData.ready = new Promise((res) => {
    const img = new Image(); img.decoding = "async";
    img.onload = () => { const g = c.getContext("2d"); const s = Math.max(c.width / img.width, c.height / img.height); g.drawImage(img, (c.width - img.width * s) / 2, (c.height - img.height * s) / 2, img.width * s, img.height * s); t.needsUpdate = true; res(true); };
    img.onerror = () => res(false); img.src = `../${slug}/cover.jpg`;
  }));
  covers.set(slug, t); return t;
}
const PZ0 = -322, PZ1 = -408;
const cards = new THREE.Group(); scene.add(cards);
const panelGeo = new THREE.PlaneGeometry(A, 1), frameGeo = new THREE.PlaneGeometry(A + 0.04, 1.04);
const frameMat = new THREE.MeshBasicMaterial({ color: 0xb8ccff, transparent: true, opacity: 0.55 });
const bright = await (await fetch("bright.json")).json(), bySlug = new Map(manifest.map((m) => [m.slug, m]));
const live = bright.map((s) => bySlug.get(s)).filter(Boolean).slice(0, phone ? 24 : 40).map((m, i, all) => {
  const g = new THREE.Group(), mat = new THREE.MeshBasicMaterial({ map: coverTex(m.slug), color: new THREE.Color(0.9, 0.9, 0.95), toneMapped: true });
  const mesh = new THREE.Mesh(panelGeo, mat); mesh.position.z = 0.01; g.add(mesh); g.add(new THREE.Mesh(frameGeo, frameMat));
  const a = rand() * 6.28, r = (phone ? 1.5 : 2.4) + rand() * (phone ? 2.2 : 4.2);
  g.position.set(Math.cos(a) * r * 1.3, Math.sin(a) * r * 0.75, lerp(PZ0, PZ1, i / all.length) - rand() * 3);
  g.scale.setScalar(0.9 + rand() * 0.8); g.rotation.y = (rand() - 0.5) * 0.5; g.userData.bob = rand() * 6.28; cards.add(g);
  return { g, mat, slug: m.slug, cover: mat.map, video: null };
});

// ---------- 6. the eye ----------
const EZ = -470, ER = 3;
const eyeMat = new THREE.ShaderMaterial({
  uniforms: { t: { value: 0 }, dil: { value: 0 } },
  vertexShader: `varying vec3 vObj; varying vec3 vN; varying vec3 vV;
    void main(){ vObj = position; vN = normalize(normalMatrix * normal); vec4 mv = modelViewMatrix * vec4(position, 1.0); vV = -mv.xyz; gl_Position = projectionMatrix * mv; }`,
  fragmentShader: `uniform float t; uniform float dil; varying vec3 vObj; varying vec3 vN; varying vec3 vV;
    float h(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
    float n(vec2 p){ vec2 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f); return mix(mix(h(i), h(i + vec2(1, 0)), f.x), mix(h(i + vec2(0, 1)), h(i + vec2(1, 1)), f.x), f.y); }
    float fbm(vec2 p){ float v = 0.0, a = 0.5; for (int i = 0; i < 5; i++) { v += a * n(p); p *= 2.03; a *= 0.5; } return v; }
    void main(){
      vec3 p = normalize(vObj), N = normalize(vN), V = normalize(vV);
      float th = acos(clamp(p.z, -1.0, 1.0)), ph = atan(p.y, p.x);
      float R = 0.66, P = 0.19 + dil * 0.03, r = th / R;
      // sclera: pale blue-white, shaded from the upper left, blue rim
      vec3 L = normalize(vec3(-0.5, 0.6, 0.65));
      vec3 col = vec3(0.82, 0.87, 1.0) * (0.55 + 0.5 * max(dot(N, L), 0.0));
      float ndv = max(dot(N, V), 0.0); col *= 0.55 + 0.45 * smoothstep(0.0, 0.7, ndv); col += vec3(0.3, 0.5, 1.1) * pow(1.0 - ndv, 3.0) * 0.8 + vec3(0.6, 0.3, 0.7) * pow(1.0 - ndv, 6.0) * 0.4;
      // iris: radial fibres, a bright zigzag collarette, a dark limbal ring
      float a = ph * 9.0, f = fbm(vec2(a, r * 4.0 - t * 0.03)) * 0.6 + n(vec2(ph * 70.0, r * 3.0)) * 0.4;
      float zig = smoothstep(0.08, 0.0, abs(r - 0.52 - 0.06 * sin(ph * 24.0 + fbm(vec2(a, 3.0)) * 4.0)));
      vec3 iris = mix(vec3(0.005, 0.025, 0.14), vec3(0.08, 0.34, 0.95), clamp(f * f * f * 3.2, 0.0, 1.0)) + vec3(0.3, 0.65, 1.0) * zig * 0.5;
      iris *= mix(1.0, 0.3, smoothstep(0.86, 1.0, r));
      col = mix(iris, col, smoothstep(0.98, 1.04, r));
      col = mix(vec3(0.0, 0.004, 0.02), col, smoothstep(P / R - 0.02, P / R + 0.02, r));
      // cornea: two window highlights
      vec3 Hh = normalize(L + V); float s = pow(max(dot(N, Hh), 0.0), 900.0) * 1.1;
      vec3 L2 = normalize(vec3(0.55, 0.35, 0.75)); s += pow(max(dot(N, normalize(L2 + V)), 0.0), 1200.0) * 0.8;
      gl_FragColor = vec4(col + s, 1.0);
      #include <colorspace_fragment>
    }`,
});
const eye = new THREE.Mesh(new THREE.SphereGeometry(ER, 192, 128), eyeMat); eye.position.z = EZ; scene.add(eye);
const eyeHalo = sprite(ER * 3.2, 0x2f6dff, 0.18); eyeHalo.position.z = EZ - 1; scene.add(eyeHalo);

// ---------- stars ----------
{
  const n = phone ? 1600 : 2800, pos = new Float32Array(n * 3), col = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) {
    pos[i * 3] = (rand() - 0.5) * 120; pos[i * 3 + 1] = (rand() - 0.5) * 80; pos[i * 3 + 2] = -150 - rand() * 420;
    const k = 0.5 + rand() * 0.5, tint = rand(); col[i * 3] = k * (tint < 0.06 ? 1 : tint < 0.12 ? 0.7 : 0.95); col[i * 3 + 1] = k * (tint < 0.06 ? 0.75 : 0.95); col[i * 3 + 2] = k * (tint < 0.06 ? 0.75 : 1);
  }
  const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.BufferAttribute(pos, 3)); g.setAttribute("color", new THREE.BufferAttribute(col, 3));
  scene.add(new THREE.Points(g, new THREE.PointsMaterial({ size: phone ? 3.2 : 3.4, sizeAttenuation: false, map: glowTex, vertexColors: true, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, fog: false, toneMapped: false })));
}

// ---------- compile every shader while the preloader runs (parallel where the driver allows), not on the first frame ----------

// ---------- preload: fonts, the sky, the first covers ----------
const first = live.slice(0, 8).map((s) => s.cover.userData.load());
const skyReady = new Promise((r) => { if (skyTex.image) r(); else { const i = setInterval(() => { if (skyTex.image) { clearInterval(i); r(); } }, 50); } });
// the env map lands with the sky and changes the metal shaders, so compile after it
skyReady.then(() => renderer.compileAsync(scene, cam)).catch(() => {});

// ---------- video pool for the project screens ----------
const POOL = phone ? 5 : 10, pool = [];
for (let k = 0; k < POOL; k++) { const v = document.createElement("video"); v.muted = true; v.loop = true; v.playsInline = true; v.preload = "auto"; v.setAttribute("muted", ""); v.crossOrigin = "anonymous"; pool.push({ v, tex: null, owner: null }); }
function assign(s, slot) {
  if (slot.owner) { const o = slot.owner; o.video = null; o.mat.map = o.cover; o.mat.needsUpdate = true; }
  slot.owner = s; s.video = slot; slot.v.src = `../${s.slug}/loop.webm`;
  slot.v.onplaying = () => { if (slot.owner !== s) return; if (!slot.tex) { slot.tex = new THREE.VideoTexture(slot.v); slot.tex.colorSpace = THREE.SRGBColorSpace; } s.mat.map = slot.tex; s.mat.needsUpdate = true; };
  slot.v.play().catch(() => {});
}
const wp = new THREE.Vector3();
function schedule() {
  const d = (s) => s.g.getWorldPosition(wp).distanceTo(cam.position);
  const vis = cards.visible ? live.filter((s) => { s.g.getWorldPosition(wp); return wp.z < cam.position.z && d(s) < 40; }).sort((a, b) => d(a) - d(b)).slice(0, POOL) : [];
  const keep = new Set(vis), free = pool.filter((sl) => !sl.owner || !keep.has(sl.owner));
  vis.filter((s) => !s.video).forEach((s) => { const sl = free.shift(); if (sl) assign(s, sl); });
  pool.forEach((sl) => { if (sl.owner && !keep.has(sl.owner) && !sl.v.paused) sl.v.pause(); else if (sl.owner && keep.has(sl.owner) && sl.v.paused) sl.v.play().catch(() => {}); });
}

// ---------- HUD tags on the exploded cube ----------
const tagEls = [...document.querySelectorAll(".xtag")], leader = $("#leaders"), TAG_SLAB = [1, 4, 7];
const tv = new THREE.Vector3();
function placeTags(o) {
  if (o < 0.02) { leader.style.opacity = 0; tagEls.forEach((t) => (t.style.opacity = 0)); return; }
  let d = "";
  tagEls.forEach((t, i) => {
    slabs[TAG_SLAB[i]].mesh.getWorldPosition(tv); tv.project(cam);
    const x = (tv.x * 0.5 + 0.5) * innerWidth, y = (-tv.y * 0.5 + 0.5) * innerHeight, left = i !== 1;
    const tw = t.offsetWidth, tx = left ? x - (phone ? 90 : 280) - tw : x + (phone ? 70 : 230), ty = y - (i === 2 ? -110 : 130);
    t.style.transform = `translate(${Math.round(tx)}px, ${Math.round(ty)}px)`; t.style.opacity = o;
    const ux = left ? tx + tw : tx, uy = ty + t.offsetHeight + 6;
    d += `M${left ? tx : tx + tw},${uy}H${ux}L${x},${y}`;
  });
  leader.firstElementChild.setAttribute("d", d); leader.style.opacity = o;
}

// ---------- scroll ----------
let lenis = null, prog = 0, vel = 0, ps = 0, snap = false;
const filmEl = $(".film"), filmEnd = () => Math.max(1, filmEl.offsetHeight - innerHeight);
if (!reduce && window.Lenis) { lenis = new Lenis({ autoRaf: true, lerp: 0.065, wheelMultiplier: 0.8, touchMultiplier: 1.4 }); window.__lenis = lenis; lenis.on("scroll", (e) => { prog = clamp(e.scroll / filmEnd()); vel = e.velocity || 0; }); }
else addEventListener("scroll", () => { prog = clamp(scrollY / filmEnd()); }, { passive: true });
document.addEventListener("focusin", (e) => { const el = e.target.closest(".beat"); if (!el || reduce) return; const f = unwarp((+el.dataset.from + Math.min(1, +el.dataset.to)) / 2), h = filmEnd(); lenis ? lenis.scrollTo(f * h, { immediate: true }) : scrollTo(0, f * h); snap = true; });
addEventListener("keydown", (e) => { if (!lenis) return; const h = document.documentElement.scrollHeight - innerHeight; if (e.key === "End") lenis.scrollTo(h); if (e.key === "Home") lenis.scrollTo(0); });

const unwarp = (q) => { if (!WARP) return q; for (let i = 1; i < WARP.length; i++) if (q <= WARP[i][1]) { const [a, x] = WARP[i - 1], [b, y] = WARP[i]; return a + (b - a) * (q - x) / (y - x); } return 1; };
const beats = [...document.querySelectorAll(".beat")], queue = $(".queue"), qItems = [...document.querySelectorAll(".queue li")];
function resize() {
  const dpr = Math.min(devicePixelRatio, 2);
  renderer.setPixelRatio(dpr); renderer.setSize(innerWidth, innerHeight, false);
  composer.setPixelRatio(dpr); composer.setSize(innerWidth, innerHeight);
  cam.aspect = innerWidth / innerHeight; cam.updateProjectionMatrix();
  // the sky plate always covers the frame, mountains low
  const D = 90, hh = 2 * D * Math.tan(THREE.MathUtils.degToRad(cam.fov / 2)) * 1.12, ia = phone ? 1024 / 1536 : 1536 / 1024;
  const w = Math.max(hh * ia, hh * cam.aspect * 1.12); sky.scale.set(w, w / ia, 1); sky.position.set(0, (w / ia - hh) * 0.18, -D);
  leader.setAttribute("viewBox", `0 0 ${innerWidth} ${innerHeight}`);
}
addEventListener("resize", resize); resize();
const ptr = { x: 0, y: 0 }, ptrT = { x: 0, y: 0 }; addEventListener("pointermove", (e) => { ptrT.x = e.clientX / innerWidth - 0.5; ptrT.y = e.clientY / innerHeight - 0.5; }, { passive: true });

// hero framing: the cube fills the frame on every screen shape
const heroD = () => { const vh = 2 * Math.tan(THREE.MathUtils.degToRad(cam.fov / 2)); return Math.max(3.6 / vh, (phone ? 2.8 : 3.3) / (vh * cam.aspect)) + 1.7; };

// phones run the same film on a shorter clock, as the reference does: its phone frames land on these desktop moments
const WARP = phone ? [[0, 0], [0.1, 0.143], [0.2, 0.214], [0.3, 0.286], [0.4, 0.43], [0.5, 0.5], [0.6, 0.57], [0.7, 0.64], [0.8, 0.77], [0.9, 0.885], [0.96, 0.935], [1, 1]] : null;
function warp(p) { if (!WARP) return p; for (let i = 1; i < WARP.length; i++) if (p <= WARP[i][0]) { const [a, x] = WARP[i - 1], [b, y] = WARP[i]; return x + (y - x) * (p - a) / (b - a); } return 1; }

// ---------- the film: one camera, seven shots ----------
let slow = 0, lastT = performance.now(), frame = 0, introK = 0, introStart = 0, hidden = false, videoOn = false, lastQ = -1;
document.addEventListener("visibilitychange", () => { hidden = document.hidden; if (!hidden) { lastT = performance.now(); requestAnimationFrame(loop); } pool.forEach((sl) => hidden ? sl.v.pause() : null); });
const t0 = performance.now(), look = new THREE.Vector3(), lamp = tunnel.getObjectByName("lamp"), fogBlue = new THREE.Color(0x06207a), fogBlack = new THREE.Color(0);
function loop() {
  if (hidden) return;
  const now = performance.now(), dt = now - lastT; lastT = now;
  if (frame < 90) { if (dt > 24) slow++; if (frame === 89 && slow > 40) composer.setPixelRatio(Math.max(1, Math.min(devicePixelRatio, 2) * 0.7)); }
  const t = (now - t0) / 1000;
  if (introStart && introK < 1) introK = reduce ? 1 : clamp((now - introStart) / 3200);
  const ease = 1 - Math.exp(-Math.min(dt, 64) / 110); ps += (prog - ps) * (reduce || snap ? 1 : ease); snap = false; if (Math.abs(prog - ps) < 1e-5) ps = prog;
  ptr.x += (ptrT.x - ptr.x) * ease * 0.6; ptr.y += (ptrT.y - ptr.y) * ease * 0.6;
  const p = warp(ps), ik = 1 - Math.pow(1 - introK, 3);
  const hd = heroD();
  let x = 0, y = 0, z = 0; look.set(0, 0, 0);
  // shot 1: the cube; the intro pulls in from far and turns it to face you, scroll pushes into the core
  if (p < 0.143) {
    const push = smooth(0, 0.07, p), dive = smooth(0.1, 0.143, p);
    z = lerp(hd + 5, hd - 0.2, push) + (1 - ik) * 14; z = lerp(z, 0.9, dive * dive);
    x = Math.sin(t * 0.12) * 0.25 * (1 - dive) + ptr.x * 0.6 * (1 - dive); y = lerp(-1.9, -0.25, push) + ptr.y * 0.3 - (1 - ik) * 1.5;
    look.set(0, lerp(0.9, 0.05, push) * (1 - dive), 0);
  } else if (p < 0.25) { // shot 2: the tunnel
    const k = (p - 0.143) / 0.107; z = lerp(TZ0 + 4, TZ1 + 8, k); x = Math.sin(t * 0.7) * 0.08; y = Math.cos(t * 0.6) * 0.06; look.set(0, 0, z - 10);
  } else if (p < 0.36) { // shot 3: orbit the exploded cube
    const k = smooth(0.25, 0.36, p), a = lerp(-0.9, 0.55, k), r = lerp(phone ? 15 : 11, phone ? 13 : 9.5, k);
    x = Math.sin(a) * r; z = SHZ + Math.cos(a) * r; y = lerp(4.2, 2.2, k); look.set(phone ? 0 : -0.8, phone ? 0.6 : 0, SHZ);
    const leave = smooth(0.34, 0.36, p); x = lerp(x, 0, leave); y = lerp(y, 0, leave); z = lerp(z, SHZ - 6, leave); look.lerp(new THREE.Vector3(0, 0, SHZ - 30), leave);
  } else if (p < 0.53) { // shot 4: through the code panels
    const k = (p - 0.36) / 0.17; z = lerp(SHZ - 6, CZ1 + 2, k); x = Math.sin(t * 0.1) * 0.3 + ptr.x * 0.5; y = Math.cos(t * 0.08) * 0.2 - ptr.y * 0.3; look.set(ptr.x, -ptr.y * 0.4, z - 12);
  } else if (p < 0.69) { // shot 5: the project screens
    const k = (p - 0.53) / 0.16; z = lerp(CZ1 + 2, PZ1 - 4, k); x = Math.sin(t * 0.1) * 0.3 + ptr.x * 0.5; y = Math.cos(t * 0.08) * 0.2 - ptr.y * 0.3; look.set(ptr.x, -ptr.y * 0.4, z - 12);
  } else { // shot 6: the eye grows until the iris fills the frame
    const k = smooth(0.69, 0.935, p); z = lerp(PZ1 - 4, EZ + ER + (phone ? 3.6 : 2.6), Math.pow(k, 0.6)); x = ptr.x * 0.3 * (1 - k); y = -ptr.y * 0.2 * (1 - k); look.set(0, 0, EZ);
  }
  cam.position.set(x, y, z); cam.lookAt(look);
  cam.rotation.z += Math.sin(t * 0.09) * 0.01 + clamp(vel * -0.0008, -0.04, 0.04);

  // visibility per shot
  const s1 = p < 0.15, s2 = p > 0.13 && p < 0.26, s3 = p > 0.24 && p < 0.38, s4 = p > 0.33 && p < 0.56, s5 = p > 0.5 && p < 0.72, s6 = p > 0.66;
  cube.visible = sky.visible = s1; tunnel.visible = s2; shards.visible = s3; panels.visible = s4; cards.visible = s5; eye.visible = eyeHalo.visible = s6;
  // the cube breathes; the core swells as the camera nears it
  cube.rotation.y = lerp(0.62, 0, smooth(0, 0.065, p)) + Math.sin(t * 0.15) * 0.05 + ptr.x * 0.05; cube.rotation.x = -0.05 + ptr.y * 0.03;
  const near = smooth(0.0, 0.14, p);
  coreGlow.material.opacity = 0.4 + near * 0.2 + Math.sin(t * 2) * 0.04; coreGlow.scale.setScalar(2.2 + near * 0.6); coreLight.intensity = 14 + near * 16;
  sky.material.opacity = 1 - smooth(0.11, 0.14, p);
  // the tunnel light travels ahead of the camera; far blocks fade into blue, not black
  const inT = smooth(0.135, 0.15, p) * (1 - smooth(0.24, 0.26, p));
  lamp.position.set(0, 0, cam.position.z - 6);
  scene.fog.color.copy(fogBlack).lerp(fogBlue, inT); scene.fog.density = lerp(0.02, 0.03, inT); bloom.threshold = lerp(0.82, 0.95, inT);
  renderer.setClearColor(scene.fog.color);
  // the cube opens
  const ex = smooth(0.262, 0.335, p);
  slabs.forEach((s, i) => { s.mesh.position.copy(s.home).addScaledVector(s.dir, ex * (phone ? 1.3 : 1.7)); s.mesh.rotation.set(s.spin.x * ex, s.spin.y * ex + Math.sin(t * 0.3 + i) * 0.02, s.spin.z * ex); });
  shards.rotation.y = t * 0.04;
  panels.children.forEach((m) => { m.position.y += Math.sin(t * 0.6 + m.userData.bob) * 0.0015; });
  cards.children.forEach((g) => { g.rotation.x = Math.sin(t * 0.4 + g.userData.bob) * 0.04; });
  eye.rotation.set(-ptr.y * 0.25, ptr.x * 0.35, 0); eyeMat.uniforms.t.value = t; eyeMat.uniforms.dil.value = Math.sin(t * 0.5) * 0.5 + 0.5;

  // flashes: into the core, and out of the tunnel's light
  const f1 = Math.max(0, 1 - Math.abs(p - 0.143) / 0.02), f2 = Math.max(0, 1 - Math.abs(p - 0.251) / 0.013);
  const fl = Math.max(f1, f2 * 0.9);
  $("#flash").style.opacity = reduce ? 0 : (fl * fl).toFixed(3);
  $("#fade").style.opacity = smooth(0.945, 0.975, p).toFixed(3);
  bloom.strength = 0.6 + fl * 1.2 + inT * 0.25 + (s1 ? near * 0.1 : 0) - (s6 ? 0.35 : 0);
  zoom.uniforms.strength.value = reduce ? 0 : clamp(inT * 0.1 + Math.abs(vel) * 0.0016 + 0, 0, 0.22);
  shift.uniforms.amount.value = reduce ? 0 : 0.0004 + inT * 0.0018 + Math.min(0.003, Math.abs(vel) * 0.00004);

  // DOM: hero, beats, queue, tags
  const hero = $(".hero"); hero.style.opacity = 1 - smooth(0.1, 0.13, p); hero.style.visibility = p > 0.135 ? "hidden" : "visible";
  beats.forEach((el) => { const a = +el.dataset.from, b = +el.dataset.to, o = smooth(a, a + 0.02, p) * (1 - smooth(b - 0.02, b, p)); el.style.opacity = o.toFixed(3); el.style.setProperty("--pe", o > 0.5 ? "auto" : "none"); el.style.setProperty("--k", (1 - smooth(a, a + 0.03, p)).toFixed(3)); });
  queue.style.opacity = (smooth(0.375, 0.395, p) * (1 - smooth(0.93, 0.95, p))).toFixed(3);
  const q = p < 0.53 ? 0 : p < 0.74 ? 1 : 2;
  if (q !== lastQ) { qItems.forEach((li, i) => li.classList.toggle("on", i === q)); if (lastQ >= 0 && window.xSound) window.xSound.blip(660 + q * 110); lastQ = q; }
  placeTags(smooth(0.275, 0.3, p) * (1 - smooth(0.335, 0.35, p)));
  if (frame++ % 12 === 0 && videoOn) schedule();
  document.body.classList.toggle("past", prog >= 0.999);
  if (p < 0.985 || frame % 30 === 0) composer.render(); // past the fade the film is black: keep the GPU idle under the résumé
  if (!reduce) requestAnimationFrame(loop);
}
const ready = Promise.race([Promise.all([skyReady, phone ? document.fonts.ready : Promise.all(first)]), new Promise((r) => setTimeout(r, 6000))]);
let realDone = false; ready.then(() => (realDone = true));
await new Promise((done) => {
  const start = performance.now(), dur = reduce ? 0 : phone ? 3000 : 5200;
  (function ring() {
    const k = Math.min(realDone ? 1 : 0.94, dur ? (performance.now() - start) / dur : 1), q = Math.round(k * 100);
    $("#pct").textContent = q + "%"; $("#pre circle").style.strokeDashoffset = 100 - q;
    if (k >= 1) done(); else requestAnimationFrame(ring);
  })();
});
const later = () => { live.forEach((s) => s.cover.userData.load()); if (!reduce) setTimeout(() => (videoOn = true), 1200); };
(window.requestIdleCallback || setTimeout)(later, { timeout: 2500 });
setTimeout(() => { $("#pre").classList.add("done"); introStart = performance.now(); document.body.classList.add("in"); }, reduce ? 0 : 500);
if (reduce) { introK = 1; prog = 0; const still = () => loop(); still(); skyReady.then(still); setTimeout(still, 1500); addEventListener("resize", still); }
else requestAnimationFrame(loop);
