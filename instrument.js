/* THE INSTRUMENT (Precision Atelier): one bespoke register of brushed champagne brass, racing-green lacquer and
   marble, built from 41 individually addressable parts in five assemblies (see PARTS and design/journey.md) plus 31 test
   pins. Head: the thick brass head block with its tick scale, the lacquer cap, a brass lip and the top door frame. Core:
   the engraved plate, two lacquer back plates, the inner frame, and the DIAL (a brass drum with an hour ring between two
   cheeks under an index needle) with four screws: the mechanism. Sides: the two marble slabs and their brackets.
   Connectors: four pins. Base: the shelf, the plinth, the lower frame, the slotted base bar, two feet.
   Every part has an assembled position and an exploded offset authored per assembly (the head rises most, the base drops
   half as far, the sides open a little, the core steps apart); every STATE writes a target transform (position, euler,
   scale, tone) per part and the frame loop lerps toward it, so any two states blend by scroll and interruptions stay
   smooth. States: closed, open (the hero), network (the star schema: the core as the fact block, four dimension panels
   joined by the connectors; the dial turns to the departure hour and the Time panel lights by that hour's lateness),
   pipeline(n), timeline, documents(u 0..2), rest. The opening: introD turns the dial to its index, introK seats the core
   stack (the click), then the closed-to-open blend propagates by assembly (lead order) while home.js pulls the camera
   back. Materials are MeshPhysicalMaterial with procedural canvas textures under an authored environment baked by
   PMREMGenerator: no downloaded assets. Transparent canvas: the page's CSS ground is the scene's ground. */
import * as THREE from "three";

const CL = v => Math.max(0, Math.min(1, v)), L = (a, b, t) => a + (b - a) * t, SM = t => t * t * (3 - 2 * t);

/* ---- the parts: [name, family, [w, h, d], material, [x, y, z] assembled, [dx, dy, dz] exploded, yaw, stack]
   family decides the geometry kind (pin and dial are cylinders along y and x, screw along z), the arrival lead and the
   explode lead; stack = 1 marks the front core stack that stands out of its seat at the start of the opening ---- */
export const PARTS = [
  // head
  ["rail", "head", [3.4, 0.44, 0.92], "rail", [0, 2.02, 0], [0, 1.12, 0], 0, 0],
  ["cap", "head", [3.0, 0.16, 0.72], "lacquer", [0, 2.33, 0], [0, 1.42, 0], 0, 0],
  ["lip", "head", [3.5, 0.07, 1.02], "brass", [0, 1.76, 0], [0, 0.88, 0], 0, 0],
  ["frameTopF", "frame", [3.3, 0.12, 0.12], "brass", [0, 1.56, 0.5], [0, 0.66, 0.22], 0, 0],
  ["frameTopB", "frame", [3.3, 0.12, 0.12], "brass", [0, 1.56, -0.5], [0, 0.7, -0.22], 0, 0],
  ["frameTopL", "frame", [0.12, 0.12, 1.0], "brass", [-1.6, 1.56, 0], [-0.22, 0.64, 0], 0, 0],
  ["frameTopR", "frame", [0.12, 0.12, 1.0], "brass", [1.6, 1.56, 0], [0.22, 0.64, 0], 0, 0],
  // core
  ["backB", "core", [1.8, 2.4, 0.1], "lacquer", [0, 0.05, -0.34], [-0.04, -0.06, -0.5], 0, 0],
  ["backA", "core", [1.8, 2.4, 0.1], "lacquer", [0, 0.05, -0.1], [0.04, 0.04, -0.22], 0, 0],
  ["plate", "core", [1.7, 2.3, 0.14], "plate", [0, 0.1, 0.22], [0, 0, 0.3], 0, 1],
  ["innerT", "inner", [1.9, 0.09, 0.09], "brass", [0, 1.3, 0.34], [0, 0.14, 0.5], 0, 1],
  ["innerB", "inner", [1.9, 0.09, 0.09], "brass", [0, -1.1, 0.34], [0, -0.14, 0.5], 0, 1],
  ["innerL", "inner", [0.09, 2.5, 0.09], "brass", [-0.92, 0.1, 0.34], [-0.14, 0, 0.5], 0, 1],
  ["innerR", "inner", [0.09, 2.5, 0.09], "brass", [0.92, 0.1, 0.34], [0.14, 0, 0.5], 0, 1],
  ["dial", "dial", [0.28, 1.1, 0.28], "dial", [0, -0.7, 0.5], [0, 0, 0.75], 0, 1],
  ["cheekL", "core", [0.14, 0.72, 0.5], "brass", [-0.68, -0.7, 0.42], [-0.06, 0, 0.68], 0, 1],
  ["cheekR", "core", [0.14, 0.72, 0.5], "brass", [0.68, -0.7, 0.42], [0.06, 0, 0.68], 0, 1],
  ["needle", "core", [0.035, 0.36, 0.035], "brass", [0, -0.3, 0.62], [0, 0.1, 0.78], 0, 1],
  ["screwTL", "screw", [0.05, 0.05, 0.05], "brass", [-0.74, 1.14, 0.31], [-0.1, 0.1, 0.62], 0, 1],
  ["screwTR", "screw", [0.05, 0.05, 0.05], "brass", [0.74, 1.14, 0.31], [0.1, 0.1, 0.62], 0, 1],
  ["screwBL", "screw", [0.05, 0.05, 0.05], "brass", [-0.74, -0.94, 0.31], [-0.1, -0.1, 0.62], 0, 1],
  ["screwBR", "screw", [0.05, 0.05, 0.05], "brass", [0.74, -0.94, 0.31], [0.1, -0.1, 0.62], 0, 1],
  // sides
  ["marbleL", "slab", [0.6, 2.5, 0.95], "green", [-1.3, 0.05, 0], [-0.52, 0.12, 0], 0, 0],
  ["marbleR", "slab", [0.6, 2.5, 0.95], "ivory", [1.3, 0.05, 0], [0.52, -0.1, 0], 0, 0],
  ["bracketL", "bracket", [0.1, 2.7, 0.1], "brass", [-1.75, 0.05, 0.3], [-0.82, 0, 0.22], 0, 0],
  ["bracketR", "bracket", [0.1, 2.7, 0.1], "brass", [1.75, 0.05, 0.3], [0.82, 0, 0.22], 0, 0],
  // connectors
  ["pinFL", "pin", [0.035, 2.9, 0], "pin", [-1.95, 0.05, 0.4], [-0.72, 0.2, 0.16], 0, 0],
  ["pinFR", "pin", [0.035, 2.9, 0], "pin", [1.95, 0.05, 0.4], [0.72, -0.2, 0.16], 0, 0],
  ["pinBL", "pin", [0.035, 2.9, 0], "pin", [-1.95, 0.05, -0.4], [-0.64, -0.14, -0.16], 0, 0],
  ["pinBR", "pin", [0.035, 2.9, 0], "pin", [1.95, 0.05, -0.4], [0.64, 0.14, -0.16], 0, 0],
  // base
  ["shelf", "lower", [3.0, 0.08, 0.86], "brass", [0, -1.3, 0], [0, -0.42, 0], 0, 0],
  ["lower", "lower", [3.3, 0.5, 1.0], "lacquer", [0, -1.62, 0], [0, -0.68, 0], 0, 0],
  ["frameLowF", "frame", [3.5, 0.12, 0.12], "brass", [0, -1.95, 0.56], [0, -0.78, 0.2], 0, 0],
  ["frameLowB", "frame", [3.5, 0.12, 0.12], "brass", [0, -1.95, -0.56], [0, -0.82, -0.2], 0, 0],
  ["frameLowL", "frame", [0.12, 0.12, 1.12], "brass", [-1.7, -1.95, 0], [-0.2, -0.76, 0], 0, 0],
  ["frameLowR", "frame", [0.12, 0.12, 1.12], "brass", [1.7, -1.95, 0], [0.2, -0.76, 0], 0, 0],
  ["base", "lower", [3.2, 0.26, 0.72], "slot", [0, -2.2, 0], [0.06, -1.08, 0], -0.03, 0],
  ["slotL", "lower", [1.3, 0.12, 0.5], "slot", [-0.75, -2.42, 0], [-0.14, -1.3, 0], 0.03, 0],
  ["slotR", "lower", [1.3, 0.12, 0.5], "slot", [0.75, -2.42, 0], [0.14, -1.36, 0], -0.03, 0],
  ["pad", "pad", [0.9, 0.08, 0.6], "brass", [-0.9, -2.55, 0.15], [-0.6, -1.62, 0.3], 0.1, 0],
  ["foot", "pad", [0.6, 0.06, 0.4], "brass", [1.2, -2.55, 0.2], [0.8, -1.68, 0.36], 0.16, 0],
];
export const N_TESTS = 31;

/* ---- procedural textures: value-noise fbm, brushed streaks, marble veins, the engraved plate, the rails, the dial ---- */
const fbm = (W, oct, seed) => { const out = new Float32Array(W * W); let s = seed; const rnd = () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
  let amp = 1, freq = 3, norm = 0;
  for (let o = 0; o < oct; o++) { const G = freq + 2, g = new Float32Array(G * G); for (let i = 0; i < G * G; i++) g[i] = rnd();
    for (let y = 0; y < W; y++) { const fy = y / W * freq, y0 = fy | 0, ty = fy - y0, yy = ty * ty * (3 - 2 * ty);
      for (let x = 0; x < W; x++) { const fx = x / W * freq, x0 = fx | 0, tx = fx - x0, xx = tx * tx * (3 - 2 * tx);
        const a = g[y0 * G + x0], b = g[y0 * G + x0 + 1], c = g[(y0 + 1) * G + x0], d = g[(y0 + 1) * G + x0 + 1];
        out[y * W + x] += amp * ((a + (b - a) * xx) * (1 - yy) + (c + (d - c) * xx) * yy); } }
    norm += amp; amp *= 0.55; freq *= 2; }
  for (let i = 0; i < W * W; i++) out[i] /= norm; return out; };
const canvas = (w, h) => { const c = document.createElement("canvas"); c.width = w; c.height = h; return c; };
const tex = (c, color) => { const t = new THREE.CanvasTexture(c); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.anisotropy = 4; if (color) t.colorSpace = THREE.SRGBColorSpace; return t; };
const marble = (W, base, vein, mottle, seed, scale, sharp) => { const c = canvas(W, W), g = c.getContext("2d"), img = g.createImageData(W, W), d = img.data, n = fbm(W, 6, seed), m = fbm(W, 3, seed + 7);
  for (let y = 0; y < W; y++) for (let x = 0; x < W; x++) { const i = y * W + x, t = (x / W * 0.7 + y / W * 1.1) * scale + n[i] * 4.2, v = Math.pow(1 - Math.abs(Math.sin(t * Math.PI)), sharp) * 0.9 + Math.pow(1 - Math.abs(Math.sin(t * Math.PI * 2.3 + 1.1)), sharp * 2.5) * 0.4, k = CL(v), q = (m[i] - 0.5) * mottle;
    d[i * 4] = CL(L(base[0], vein[0], k) + q) * 255; d[i * 4 + 1] = CL(L(base[1], vein[1], k) + q) * 255; d[i * 4 + 2] = CL(L(base[2], vein[2], k) + q) * 255; d[i * 4 + 3] = 255; }
  g.putImageData(img, 0, 0); return c; };
const brushed = (W, seed) => { const c = canvas(W, W), g = c.getContext("2d"), img = g.createImageData(W, W), d = img.data; let s = seed; const rnd = () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
  for (let y = 0; y < W; y++) { const row = 0.5 + (rnd() - 0.5) * 0.5; for (let x = 0; x < W; x++) { const i = (y * W + x) * 4, v = CL(row + (rnd() - 0.5) * 0.12) * 255; d[i] = d[i + 1] = d[i + 2] = v; d[i + 3] = 255; } }
  g.putImageData(img, 0, 0); return c; };
const BRASS = "#cfb588", INK = "rgba(22, 32, 26, 0.8)", DISPLAY = "'Bricolage Grotesque', 'Archivo', sans-serif";
const streak = (g, w, h) => { const b = brushed(256, 11); g.globalAlpha = 0.16; g.fillStyle = g.createPattern(b, "repeat"); g.fillRect(0, 0, w, h); g.globalAlpha = 1; };
const engraved = words => { const c = canvas(768, 1024), g = c.getContext("2d"); g.fillStyle = BRASS; g.fillRect(0, 0, 768, 1024); streak(g, 768, 1024);
  g.fillStyle = INK; g.font = `800 96px ${DISPLAY}`; try { g.fontStretch = "condensed"; } catch (_) {}
  g.textBaseline = "top"; words.forEach((w, i) => g.fillText(w.toUpperCase(), 96, 210 + i * 112));
  g.fillStyle = "rgba(22, 32, 26, 0.6)"; for (let i = 0; i < 40; i++) { const y = 80 + i * 22; g.fillRect(40, y, i % 5 === 0 ? 26 : 12, 2); }
  g.fillRect(96, 180, 420, 3); g.fillRect(96, 672, 220, 3); return c; };
const railTicks = slot => { const c = canvas(1024, 160), g = c.getContext("2d"); g.fillStyle = BRASS; g.fillRect(0, 0, 1024, 160); streak(g, 1024, 160); g.fillStyle = INK;
  if (slot) { g.beginPath(); g.roundRect(300, 64, 424, 32, 16); g.fill(); }
  else { for (let i = 0; i < 128; i++) { const h = i % 8 === 0 ? 40 : i % 4 === 0 ? 24 : 12; g.fillRect(8 + i * 8, 130 - h, 2, h); }
    g.font = `700 26px ${DISPLAY}`; g.textBaseline = "top"; for (let i = 0; i < 16; i++) g.fillText(String(i * 8), 8 + i * 64 + 6, 40); }
  return c; };
/* the hour ring: 24 hours around the drum, a numeral every six, the index line at hour 0 */
const dialRing = () => { const c = canvas(1024, 256), g = c.getContext("2d"); g.fillStyle = BRASS; g.fillRect(0, 0, 1024, 256); streak(g, 1024, 256); g.fillStyle = INK;
  for (let i = 0; i < 96; i++) { const x = i / 96 * 1024, h = i % 24 === 0 ? 70 : i % 4 === 0 ? 40 : 18; g.fillRect(x, 20, i % 4 === 0 ? 3 : 2, h); g.fillRect(x, 236 - h * 0.5, i % 4 === 0 ? 3 : 2, h * 0.5); }
  g.font = `700 54px ${DISPLAY}`; g.textBaseline = "middle"; g.textAlign = "center"; for (let h = 0; h < 24; h += 6) g.fillText(String(h).padStart(2, "0"), h / 24 * 1024 + 24, 148);
  g.fillRect(0, 120, 1024, 2); return c; };

/* The procedural textures, drawn one per task (a yield between each) so no single main-thread task carries all of
   them; pass the result to createInstrument as `textures`. */
export async function prepareTextures({ texSize = 512, words = ["Data", "Security", "Intelligence", "Impact"] } = {}) {
  const yieldNow = () => new Promise(r => setTimeout(r, 0)); const T = {};
  T.rough = brushed(Math.min(512, texSize), 3); await yieldNow();
  T.rail = railTicks(false); T.slot = railTicks(true); T.plate = engraved(words); T.dial = dialRing(); await yieldNow();
  T.green = marble(texSize, [0.04, 0.16, 0.11], [0.6, 0.66, 0.58], 0.05, 5, 1.6, 16); await yieldNow();
  T.ivory = marble(texSize, [0.92, 0.88, 0.8], [0.58, 0.53, 0.47], 0.04, 9, 1.3, 11);
  return T;
}

export function createInstrument({ canvas: cv, phone, reduced, series, fan, words = ["Data", "Security", "Intelligence", "Impact"], quality = "full", startOut = false, texSize = 512, textures = null, onReady }) {
  const t0 = performance.now(), marks = {};
  const TX = textures || { rough: brushed(Math.min(512, texSize), 3), rail: railTicks(false), slot: railTicks(true), plate: engraved(words), dial: dialRing(), green: marble(texSize, [0.04, 0.16, 0.11], [0.6, 0.66, 0.58], 0.05, 5, 1.6, 16), ivory: marble(texSize, [0.92, 0.88, 0.8], [0.58, 0.53, 0.47], 0.04, 9, 1.3, 11) };
  let gl = null;
  try { gl = cv.getContext("webgl2", { antialias: true, alpha: true, premultipliedAlpha: true, powerPreference: "high-performance" }); } catch (_) {}
  if (!gl) return null;
  const renderer = new THREE.WebGLRenderer({ canvas: cv, context: gl, antialias: true, alpha: true });
  let dpr = 1; renderer.setPixelRatio(dpr); renderer.setClearColor(0x000000, 0); renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.1;
  const shadows = quality === "full"; renderer.shadowMap.enabled = shadows; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 100); camera.position.set(0, 0, 19);

  /* ---- the environment: an authored room (mid green-grey walls, a warm key panel left, a warm panel behind the
     camera so faces toward the visitor read champagne, a cool fill right, a skylight) baked by PMREM ---- */
  const env = (() => { const s = new THREE.Scene(); s.add(new THREE.Mesh(new THREE.BoxGeometry(20, 14, 20), new THREE.MeshStandardMaterial({ color: 0x3d5047, roughness: 1, side: THREE.BackSide })));
    const panel = (w, h, pos, rot, color, k) => { const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ color })); m.material.color.multiplyScalar(k); m.position.set(...pos); m.rotation.set(...rot); s.add(m); };
    panel(7, 9, [-9.5, 2, 2], [0, Math.PI / 2, 0], 0xfff1d6, 7);            // key panel, warm, left
    panel(12, 8, [0, 1, 9.6], [0, Math.PI, 0], 0xfff3e2, 2.6);               // behind the camera: the champagne face
    panel(5, 4, [9.5, -1, -3], [0, -Math.PI / 2, 0], 0xe8f4ff, 1.8);         // cool fill, right
    panel(10, 6, [0, 6.9, -2], [Math.PI / 2, 0, 0], 0xfff6e8, 3.0);          // skylight
    panel(14, 1.2, [0, -6.9, 3], [-Math.PI / 2, 0, 0], 0x1e4a38, 1.5);       // the green floor glow
    const pm = new THREE.PMREMGenerator(renderer); const t = pm.fromScene(s, 0.04).texture; pm.dispose(); return t; })();
  scene.environment = env; marks.env = Math.round(performance.now() - t0);
  const key = new THREE.DirectionalLight(0xfff0d8, 2.3); key.position.set(-7, 9, 8); key.castShadow = shadows;
  key.shadow.mapSize.set(1024, 1024); key.shadow.camera.left = -8; key.shadow.camera.right = 8; key.shadow.camera.top = 8; key.shadow.camera.bottom = -8; key.shadow.camera.near = 2; key.shadow.camera.far = 40; key.shadow.bias = -0.0006; key.shadow.normalBias = 0.02; key.shadow.radius = 3;
  scene.add(key); scene.add(key.target);
  const rim = new THREE.DirectionalLight(0xcfe6dc, 0.9); rim.position.set(8, 3, -6); scene.add(rim);
  scene.add(new THREE.AmbientLight(0x2a4a3c, 0.5));

  /* ---- materials: brass is brushed and never a mirror; lacquer and marble carry a clearcoat ---- */
  const rough = tex(TX.rough); rough.repeat.set(2, 2);
  const metal = (extra) => new THREE.MeshPhysicalMaterial({ metalness: 1, roughness: 0.56, roughnessMap: rough, anisotropy: 0.6, envMapIntensity: 0.95, emissive: 0x6a4f22, emissiveIntensity: 0, ...extra });
  const M = {
    brass: metal({ color: 0xc9b086 }),
    rail: metal({ map: tex(TX.rail, true), roughness: 0.52 }),
    slot: metal({ map: tex(TX.slot, true), roughness: 0.52 }),
    plate: metal({ map: tex(TX.plate, true), roughness: 0.5, anisotropy: 0.5 }),
    dial: metal({ map: tex(TX.dial, true), roughness: 0.48, anisotropy: 0.7 }),
    pin: metal({ color: 0xc9b086, roughness: 0.5 }),
    lacquer: new THREE.MeshPhysicalMaterial({ color: 0x0b3328, metalness: 0, roughness: 0.36, clearcoat: 0.6, clearcoatRoughness: 0.16, envMapIntensity: 0.7, emissive: 0x1a5a40, emissiveIntensity: 0 }),
    green: new THREE.MeshPhysicalMaterial({ map: tex(TX.green, true), metalness: 0, roughness: 0.26, clearcoat: 0.4, clearcoatRoughness: 0.14, envMapIntensity: 0.7, emissive: 0x1a5a40, emissiveIntensity: 0 }),
    ivory: new THREE.MeshPhysicalMaterial({ map: tex(TX.ivory, true), metalness: 0, roughness: 0.3, clearcoat: 0.35, clearcoatRoughness: 0.16, envMapIntensity: 0.65, emissive: 0x8a7a50, emissiveIntensity: 0 }),
  };
  marks.textures = Math.round(performance.now() - t0);
  const geos = {};
  const geoFor = ([w, h, d], fam) => { const k = fam + [w, h, d].join("x"); if (geos[k]) return geos[k];
    let g; if (fam === "pin") g = new THREE.CylinderGeometry(w, w, h, 18);
    else if (fam === "dial") { g = new THREE.CylinderGeometry(w, w, h, 56); g.rotateZ(Math.PI / 2); }            // the drum's axis is x; its spin is the pitch
    else if (fam === "screw") { g = new THREE.CylinderGeometry(w, w, 0.04, 16); g.rotateX(Math.PI / 2); }
    else g = new THREE.RoundedBoxGeometry(w, h, d, 4, Math.min(0.045, Math.min(w, h, d) * 0.3));
    return geos[k] = g; };

  /* ---- build the parts and the 31 test pins ---- */
  const group = new THREE.Group(); scene.add(group);
  const capGeo = new THREE.CylinderGeometry(0.07, 0.07, 0.06, 14);
  const parts = PARTS.map(([name, fam, size, mat, at, ex, yaw, stack]) => { const mesh = new THREE.Mesh(geoFor(size, fam), M[mat]); mesh.castShadow = shadows; mesh.receiveShadow = shadows; mesh.name = name;
    if (fam === "pin") for (const s of [-1, 1]) { const c = new THREE.Mesh(capGeo, M.brass); c.position.y = s * size[1] / 2; c.castShadow = shadows; mesh.add(c); }
    group.add(mesh); return { name, fam, size, mat, at, ex, yaw, stack, mesh }; });
  const pinGeo = new THREE.CylinderGeometry(0.03, 0.03, 0.42, 12), headGeo = new THREE.CylinderGeometry(0.06, 0.06, 0.05, 12);
  const tests = []; for (let i = 0; i < N_TESTS; i++) { const m = new THREE.Mesh(pinGeo, M.pin); const h = new THREE.Mesh(headGeo, M.pin); h.position.y = 0.22; m.add(h); m.castShadow = shadows; m.visible = false; group.add(m); tests.push(m); }
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(30, 30), new THREE.ShadowMaterial({ opacity: 0.3 })); ground.rotation.x = -Math.PI / 2; ground.position.y = -3.3; ground.receiveShadow = shadows; group.add(ground);
  const NP = parts.length, NT = N_TESTS, NALL = NP + NT, F = 10, mk = () => new Float32Array(NALL * F);
  const put = (T, i, x, y, z, yaw, pitch, roll, sx, sy, sz, tone) => { const o = i * F; T[o] = x; T[o + 1] = y; T[o + 2] = z; T[o + 3] = yaw; T[o + 4] = pitch; T[o + 5] = roll; T[o + 6] = sx; T[o + 7] = sy; T[o + 8] = sz; T[o + 9] = tone; };
  const hide = (T, i) => put(T, i, 0, -3, 0, 0, 0, 0, 0.001, 0.001, 0.001, 0);
  const hidePins = T => { for (let i = 0; i < NT; i++) hide(T, NP + i); };
  const idx = Object.fromEntries(parts.map((p, i) => [p.name, i]));
  const seat = (T, i, dx = 0, dy = 0, dz = 0, tone = 0, pitch = 0) => { const p = parts[i]; put(T, i, p.at[0] + dx, p.at[1] + dy, p.at[2] + dz, 0, pitch, 0, 1, 1, 1, tone); };
  /* stand a part as a column of width w, height h, depth d: its longest axis becomes vertical, the others scale gently */
  const column = (T, i, x, y, z, w, h, d, tone, roll = 0) => { const p = parts[i], [pw, ph, pd] = p.fam === "pin" ? [p.size[0] * 2, p.size[1], p.size[0] * 2] : p.size;
    if (ph >= pw && ph >= pd) put(T, i, x, y, z, 0, 0, roll, w / pw, h / ph, d / pd, tone);                 // already tall
    else if (pw >= pd) put(T, i, x, y, z, 0, 0, Math.PI / 2 + roll, h / pw, w / ph, d / pd, tone);          // long along x: roll it up
    else put(T, i, x, y, z, 0, Math.PI / 2, roll, w / pw, d / ph, h / pd, tone); };                        // long along z: pitch it up
  const months = (() => { const h = series && series.length === 24 ? series.slice() : Array.from({ length: 24 }, (_, k) => 1 + 0.07 * Math.sin((k % 12) / 12 * Math.PI * 2 - 1.9)); const mean = h.reduce((a, b) => a + b, 0) / h.length; return h.map(x => x / mean); })();
  const fanAt = h => (fan && fan[h] != null ? fan[h] : 2) / 2.6;
  const CORE = ["backB", "backA", "plate", "innerT", "innerB", "innerL", "innerR", "dial", "cheekL", "cheekR", "needle", "screwTL", "screwTR", "screwBL", "screwBR"];
  const hourAngle = h => (h == null ? 8 : h) / 24 * Math.PI * 2;

  /* ---- the states ---- */
  const STATES = {
    closed(T) { parts.forEach((p, i) => seat(T, i)); hidePins(T); },
    /* the exploded hero: each assembly lifts by its authored offset (the head most, the base less, the sides a little,
       the core in small steps); nothing is evenly spaced */
    open(T) { parts.forEach((p, i) => put(T, i, p.at[0] + p.ex[0], p.at[1] + p.ex[1], p.at[2] + p.ex[2], p.yaw, 0, 0, 1, 1, 1, 0)); hidePins(T); },
    /* the star schema: the core stays assembled as the fact block (the dial reads the departure hour); the four dimension
       panels stand at the corners turned a little toward the centre; the connectors join each panel to the block's
       corner; the head and base beams and the brackets frame it. hour: the dial's reading; late: 0..1 lights the Time
       panel (ivory) and thickens its connector, and steps both forward */
    network(T, hour = 8, late = 0) { const lateK = CL(late);
      parts.forEach((p, i) => hide(T, i));
      CORE.forEach(n => seat(T, idx[n], 0, -0.05, 0, n === "plate" ? 0.55 : 0, n === "dial" ? hourAngle(hour) : 0));
      const corners = [["marbleL", -2.75, 1.75, 0], ["marbleR", 2.75, 1.75, lateK], ["backA", 2.75, -1.75, 0], ["backB", -2.75, -1.75, 0]], pins = ["pinFL", "pinFR", "pinBR", "pinBL"];
      corners.forEach(([n, x, y, lit], k) => { const p = parts[idx[n]], tall = p.fam === "slab";
        put(T, idx[n], x + Math.sign(x) * lit * 0.3, y + lit * 0.1, lit * 0.8, -Math.sign(x) * 0.28, 0, 0, (tall ? 1 : 0.9) * (1 + lit * 0.14), (tall ? 0.82 : 0.74) * (1 + lit * 0.14), tall ? 0.9 : 1.6, lit * 0.9);
        const cx = Math.sign(x) * 0.9, cy = Math.sign(y) * 1.2, ex = x - Math.sign(x) * (tall ? 0.3 : 0.95), ey = y - Math.sign(y) * (tall ? 1.0 : 1.0), d = Math.hypot(ex - cx, ey - cy), ang = Math.atan2(ey - cy, ex - cx);
        put(T, idx[pins[k]], (cx + ex) / 2, (cy + ey) / 2, 0.2 + lit * 0.2, 0, 0, ang - Math.PI / 2, 1 + lit * 1.4, d / 2.9, 1 + lit * 1.4, lit); });
      put(T, idx.bracketL, -3.4, 0, 0, 0, 0, 0, 1, 1.5, 1, 0); put(T, idx.bracketR, 3.4, 0, 0, 0, 0, 0, 1, 1.5, 1, 0);
      put(T, idx.rail, 0, 3.15, 0, 0, 0, 0, 1.45, 0.8, 0.8, 0); put(T, idx.base, 0, -3.15, 0, 0, 0, 0, 1.55, 1, 1, 0);
      put(T, idx.cap, 0, 3.52, 0, 0, 0, 0, 1.45, 0.9, 0.7, 0); put(T, idx.shelf, 0, -2.95, 0, 0, 0, 0, 1.6, 1, 0.8, 0);
      hidePins(T); },
    /* dbt: four standing frames in a row (source, staging, intermediate, marts) on two long rails; the solid parts stand
       inside each frame as its tables; the 31 test pins slot into the frames' top bars as the tests pass */
    pipeline(T, n = 0) { const G = [-4.3, -1.45, 1.4, 4.25];
      parts.forEach((p, i) => hide(T, i));
      // the two long rails the row stands on (the dependency flow runs along them)
      put(T, idx.pinFL, 0, -1.95, 0.55, 0, 0, Math.PI / 2, 1, 4.1, 1, 0); put(T, idx.pinBL, 0, -1.95, -0.55, 0, 0, Math.PI / 2, 1, 4.1, 1, 0);
      put(T, idx.pinFR, G[1] + 1.4, -1.95, 0, 0, Math.PI / 2, 0, 1, 0.42, 1, 0); put(T, idx.pinBR, G[2] + 1.4, -1.95, 0, 0, Math.PI / 2, 0, 1, 0.42, 1, 0);
      // frames: staging and intermediate get the two real frames; source and marts get the inner frame and the brackets
      const frame = (gx, long1, long2, side1, side2, w, h) => { column(T, idx[long1], gx, h / 2, 0, w, 0.1, 0.08, 0, Math.PI / 2); column(T, idx[long2], gx, -h / 2, 0, w, 0.1, 0.08, 0, Math.PI / 2);
        column(T, idx[side1], gx - w / 2, 0, 0, 0.1, h, 0.08, 0); column(T, idx[side2], gx + w / 2, 0, 0, 0.1, h, 0.08, 0); };
      frame(G[0], "innerT", "innerB", "innerL", "innerR", 2.0, 2.6); frame(G[1], "frameTopF", "frameTopB", "frameTopL", "frameTopR", 2.3, 3.0); frame(G[2], "frameLowF", "frameLowB", "frameLowL", "frameLowR", 2.3, 3.0);
      column(T, idx.bracketL, G[3] - 1.0, 0, 0, 0.09, 2.6, 0.09, 0); column(T, idx.bracketR, G[3] + 1.0, 0, 0, 0.09, 2.6, 0.09, 0);
      // source: the raw rails stacked as a bundle of bars; staging: the two lacquer plates; intermediate: the slabs and the shelf; marts: the engraved plate, the pad and the foot
      ["rail", "cap", "base", "slotL", "slotR"].forEach((nm, k) => column(T, idx[nm], G[0], -0.95 + k * 0.48, 0, 1.7, 0.3, 0.45, 0, Math.PI / 2));
      put(T, idx.backA, G[1] - 0.35, 0.05, -0.1, 0, 0, 0, 1, 1.1, 1, 0); put(T, idx.backB, G[1] + 0.45, -0.05, 0.1, 0, 0, 0, 1, 1.1, 1, 0);
      put(T, idx.marbleL, G[2] - 0.5, 0, 0, 0, 0, 0, 1, 1.1, 0.7, 0); put(T, idx.marbleR, G[2] + 0.5, 0, 0, 0, 0, 0, 1, 1.1, 0.7, 0); column(T, idx.shelf, G[2], 0, 0.5, 2.0, 0.06, 2.6, 0, Math.PI / 2); column(T, idx.lower, G[2], 0, -0.6, 2.0, 0.46, 2.6, 0, Math.PI / 2);
      put(T, idx.plate, G[3], 0.05, 0, 0, 0, 0, 1, 1.05, 1, 0.5); put(T, idx.pad, G[3] - 0.55, -1.55, 0.6, 0, 0, 0, 1, 1, 1, 0); put(T, idx.foot, G[3] + 0.6, -1.6, 0.6, 0, 0, 0, 1, 1, 1, 0);
      for (let i = 0; i < NT; i++) { const g = i % 4, k = Math.floor(i / 4), on = i < n, x = G[g] + (k - 3.5) * 0.26, y = [1.3, 1.5, 1.5, 1.3][g]; put(T, NP + i, x, on ? y + 0.1 : y + 0.9, 0, 0, 0, 0, on ? 1 : 0.001, on ? 1 : 0.001, on ? 1 : 0.001, on ? 1 : 0); } },
    /* the forecast: twelve solid parts stand in time order at the real series' height (the last twelve observed
       months); twelve thin bars stand ahead at last year's shape and fan apart by the backtest's error at each horizon;
       the pins lie end to end as the axis (an illustrative shape, labelled on the page; the chart beside it is the data) */
    timeline(T) { const obs = ["base", "slotL", "slotR", "pad", "lower", "shelf", "cap", "rail", "backA", "backB", "plate", "marbleL"], fut = ["frameLowF", "frameLowB", "frameLowL", "frameLowR", "frameTopF", "frameTopB", "frameTopL", "frameTopR", "innerT", "innerB", "innerL", "innerR"];
      parts.forEach((p, i) => hide(T, i));
      const hOf = v => 0.5 + (v - 0.85) * 9;
      obs.forEach((n, k) => { const h = hOf(months[12 + k]); column(T, idx[n], -4.6 + k * 0.44, -1.7 + h / 2, 0, 0.34, h, 0.5, 0); });
      fut.forEach((n, k) => { const t = fanAt(k), h = hOf(months[12 + k] * 1.03), spread = ((k * 7) % 5 / 4 - 0.5) * t * 2.2; column(T, idx[n], 1.0 + k * 0.4, -1.7 + h / 2 + spread, ((k * 3) % 3 - 1) * 0.25 * t, 0.12, h, 0.12, 0.8); });
      put(T, idx.marbleR, 1.0 + 11 * 0.4 + 0.6, -1.7 + hOf(months[23] * 1.03) / 2, 0, 0, 0, 0, 0.5, hOf(months[23] * 1.03) / 2.3, 0.5, 0.5);
      put(T, idx.bracketL, -5.2, -1.7, 0, 0, 0, 0, 1, 0.05, 1, 0); put(T, idx.bracketR, 0.7, -0.2, 0, 0, 0, 0, 1, 1.4, 1, 0.9);   // the now line
      ["pinFL", "pinFR", "pinBL", "pinBR"].forEach((n, k) => put(T, idx[n], -3.5 + k * 2.65, -1.85, 0, 0, 0, Math.PI / 2, 1, 1, 1, 0));
      hidePins(T); },
    /* retrieval: a card index drawer (the rails and base as the drawer, the lacquer plates, the engraved plate and
       the shelf as cards leaning back from a shared bottom edge); u 0..1 lifts the ivory passage out and turns it to
       face the visitor; u 1..2 closes the drawer again (the refusal) */
    documents(T, u = 1) { const sel = SM(CL(u)), refuse = SM(CL(u - 1));
      parts.forEach((p, i) => hide(T, i));
      // the drawer
      put(T, idx.base, 0, -2.2, 0, 0, 0, 0, 1.5, 1, 1.9, 0); put(T, idx.rail, 0, -1.3, -1.25, 0, 0, 0, 1.2, 1.4, 0.5, 0);
      put(T, idx.slotL, -2.15, -1.5, 0, 0, Math.PI / 2, Math.PI / 2, 1.3, 1, 1.5, 0); put(T, idx.slotR, 2.15, -1.5, 0, 0, Math.PI / 2, Math.PI / 2, 1.3, 1, 1.5, 0);
      put(T, idx.cap, 0, -1.4, L(1.3, 0.9, refuse), 0, 0, 0, 1.4, 2.2, 0.6, 0);
      // the cards, fanned back from the bottom edge; the fan closes on the refusal
      const cards = ["backB", "backA", "plate", "lower", "shelf", "marbleL", "frameLowF", "frameTopF", "frameLowB", "frameTopB"];
      cards.forEach((n, k) => { const p = parts[idx[n]], a = L(0.5 - k * 0.09, 0.06, refuse), z = -0.9 + k * 0.22, h = p.fam === "core" ? 2.3 : 2.2, tall = p.fam === "core";
        const cy = -1.95 + Math.cos(a) * h / 2, cz = z + Math.sin(a) * h / 2;
        if (tall) put(T, idx[n], 0, cy, cz, 0, -a, 0, 1.1, 1, 1, n === "plate" ? 0.3 : 0);
        else if (p.fam === "lower") put(T, idx[n], 0, cy, cz, 0, Math.PI / 2 - a, 0, 0.7, 1, h / p.size[2], 0);
        else if (p.fam === "slab") put(T, idx[n], 0, cy, cz, 0, -a, 0, 3.2, h / p.size[1], 0.12, 0);
        else put(T, idx[n], 0, cy, cz, 0, -a, Math.PI / 2, h / p.size[0] * 0.95, 20, 1.2, 0); });
      // the passage: the ivory slab rises out of the index and turns to face the visitor; it sinks back on the refusal
      const lift = sel * (1 - refuse), a0 = 0.5 - 4 * 0.09, cy0 = -1.95 + Math.cos(a0) * 1.1, cz0 = -0.9 + 4 * 0.22 + Math.sin(a0) * 1.1;
      put(T, idx.marbleR, L(0, 1.2, lift), L(cy0, 1.3, lift), L(cz0, 2.2, lift), L(0, 0.35, lift), L(-a0, 0.08, lift), 0, L(3.2, 2.2, lift), L(1, 0.8, lift), L(0.12, 0.2, lift), lift);
      // the frame bars close over the drawer on the refusal
      put(T, idx.bracketL, L(-2.4, -0.6, refuse), L(-0.2, 0.3, refuse), 1.0, 0, 0, L(0, 0.55, refuse), 1, 1.1, 1, refuse); put(T, idx.bracketR, L(2.4, 0.6, refuse), L(-0.2, 0.3, refuse), 1.0, 0, 0, L(0, -0.55, refuse), 1, 1.1, 1, refuse);
      hidePins(T); },
    rest(T) { STATES.closed(T); },
  };
  const cache = {}; const keyOf = a => a == null ? "" : typeof a === "number" ? a.toFixed(2) : a;
  const stateOf = (name, arg, arg2) => { const k = name + ":" + keyOf(arg) + ":" + keyOf(arg2); if (!cache[k]) { const T = mk(); STATES[name](T, arg, arg2); cache[k] = T; } return cache[k]; };
  const now = mk(); now.set(stateOf("closed")); const tgt = mk();
  const Mx = new THREE.Matrix4(), P = new THREE.Vector3(), Q = new THREE.Quaternion(), E = new THREE.Euler(), S = new THREE.Vector3();
  const meshes = [...parts.map(p => p.mesh), ...tests];

  /* ---- the opening (design/journey.md, shots 1 to 3): introD 0..1 turns the dial from 2.4 rad off its index to the
     index; introK 0..1 seats the front core stack from 0.7 ahead; the closed-to-open blend then propagates by assembly
     in LEAD order (the head first, the base after it, the sides, then the core) ---- */
  const LEAD = { head: 0, frame: 0.08, lower: 0.2, slab: 0.36, bracket: 0.36, pin: 0.42, pad: 0.3, core: 0.52, inner: 0.52, dial: 0.58, screw: 0.62 };
  const blendOf = (p, u, lead) => SM(CL((u - (lead ? LEAD[p.fam] * 0.5 : LEAD[p.fam] * 0.16)) / (lead ? 0.5 : 0.84)));
  const DIAL = idx.dial;
  const applyIntro = (T, d, k) => { const out = 0.7 * (1 - SM(CL(k))); for (let i = 0; i < NP; i++) if (parts[i].stack) T[i * F + 2] += out; T[DIAL * F + 4] += (1 - d) * 2.4; };
  if (startOut && !reduced) applyIntro(now, 0, 0);

  /* ---- stage, resize, context loss ---- */
  const resize = () => { const w = cv.clientWidth || innerWidth, h = cv.clientHeight || innerHeight; renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); };
  addEventListener("resize", resize); resize();
  const visH = () => 2 * camera.position.z * Math.tan((camera.fov / 2) * Math.PI / 180), visW = () => visH() * camera.aspect;
  const lost = { on: false, count: 0 };
  cv.addEventListener("webglcontextlost", e => { e.preventDefault(); lost.on = true; lost.count++; document.documentElement.classList.remove("gl-on"); });
  cv.addEventListener("webglcontextrestored", () => { lost.on = false; settled = 0; document.documentElement.classList.add("gl-on"); });

  try { renderer.compile(scene, camera); } catch (_) {} marks.compile = Math.round(performance.now() - t0);
  const cur = { x: 0, y: 0, s: 1, rx: 0, ry: 0, tilt: { x: 0, y: 0 } };
  let lastT = performance.now(), fast = 0, slow = 0, lock = 0, settled = 0, paused = false, firstFrame = true;
  const EM = { brass: 0, rail: 0, slot: 0, plate: 0.8, dial: 0, pin: 1.0, lacquer: 0.5, green: 0.5, ivory: 1.4 };
  const update = (t, pose) => {
    if (lost.on || paused) return;
    const dt = Math.min(0.05, (t - lastT) / 1000); lastT = t;
    const ease = reduced ? 1 : 1 - Math.pow(0.004, dt), quick = reduced ? 1 : 1 - Math.pow(0.0005, dt);
    const A = stateOf(pose.state || "open", pose.arg, pose.arg2), B = pose.next ? stateOf(pose.next, pose.nextArg, pose.nextArg2) : A, u = SM(CL(pose.u || 0));
    const k = pose.introK == null ? 1 : pose.introK, d = pose.introD == null ? 1 : pose.introD, opening = k < 1 || d < 1;
    let moved = 0;
    for (let i = 0; i < NALL; i++) { const o = i * F, m = B === A ? 0 : i < NP ? blendOf(parts[i], u, pose.lead) : SM(CL((u - (i % 7) * 0.03) / 0.82));
      for (let j = 0; j < F; j++) tgt[o + j] = L(A[o + j], B[o + j], m); }
    if (opening && !pose.introStill) applyIntro(tgt, d, k);
    const rate = opening && !reduced ? 1 - Math.pow(0.00002, dt) : ease;
    for (let i = 0; i < NALL; i++) { const o = i * F, mesh = meshes[i];
      for (let j = 0; j < F; j++) { const nv = L(now[o + j], tgt[o + j], j === 9 ? quick : rate); moved = Math.max(moved, Math.abs(nv - now[o + j])); now[o + j] = nv; }
      P.set(now[o], now[o + 1], now[o + 2]); E.set(now[o + 4], now[o + 3], now[o + 5]); Q.setFromEuler(E); S.set(now[o + 6], now[o + 7], now[o + 8]); Mx.compose(P, Q, S); mesh.matrix.copy(Mx); mesh.matrixAutoUpdate = false; mesh.matrixWorldNeedsUpdate = true;
      mesh.visible = now[o + 6] > 0.01; }
    // tone: a per-material glow level is the max of its parts (materials are shared; parts that light do so together)
    const glow = {}; for (let i = 0; i < NALL; i++) { const mat = i < NP ? parts[i].mat : "pin"; glow[mat] = Math.max(glow[mat] || 0, now[i * F + 9]); }
    for (const m in M) M[m].emissiveIntensity = (glow[m] || 0) * EM[m];
    const st = pose.stage || { x: 0.68, y: 0.5, s: 1 };
    const tx = (st.x - 0.5) * visW(), ty = (0.5 - st.y) * visH(), ts = st.s * (phone() ? 0.7 : 1);
    if (firstFrame) { cur.x = tx; cur.y = ty; cur.s = ts; }
    cur.x = L(cur.x, tx, ease); cur.y = L(cur.y, ty, ease); cur.s = L(cur.s, ts, ease);
    const tilt = pose.tilt || { x: 0, y: 0 }; cur.tilt.x = L(cur.tilt.x, tilt.x, ease); cur.tilt.y = L(cur.tilt.y, tilt.y, ease);
    const ry = (pose.ry == null ? -0.5 : pose.ry) + cur.tilt.x * 0.14 + (pose.spin || 0), rx = (pose.rx == null ? 0.16 : pose.rx) - cur.tilt.y * 0.08;
    if (firstFrame) { cur.ry = ry; cur.rx = rx; }
    cur.ry = L(cur.ry, ry, ease); cur.rx = L(cur.rx, rx, ease);
    moved = Math.max(moved, Math.abs(cur.x - tx), Math.abs(cur.y - ty), Math.abs(cur.ry - ry), Math.abs(cur.rx - rx));
    group.position.set(cur.x, cur.y, 0); group.scale.setScalar(cur.s); group.rotation.set(cur.rx, cur.ry, 0);
    ground.rotation.set(-Math.PI / 2 - cur.rx, 0, 0); ground.position.y = (pose.ground == null ? -3.3 : pose.ground);
    key.target.position.set(cur.x, cur.y, 0);
    settled = moved < 0.0004 && !opening ? settled + 1 : 0;
    if (settled > 12 && !pose.force) return;
    renderer.render(scene, camera);
    if (firstFrame) { firstFrame = false; marks.firstFrame = Math.round(performance.now() - t0); if (onReady) onReady(); }
    const maxDpr = Math.min(quality === "full" ? 1.75 : 1.5, devicePixelRatio || 1);
    if (t > lock) { if (dt < 0.0125) { fast++; slow = 0; } else if (dt > 0.024) { slow++; fast = 0; } else { fast = Math.max(0, fast - 1); slow = Math.max(0, slow - 1); }
      if (fast > 90 && dpr < maxDpr) { dpr = maxDpr; renderer.setPixelRatio(dpr); resize(); fast = 0; lock = t + 8000; }
      if (slow > 40 && dpr > 1) { dpr = 1; renderer.setPixelRatio(1); resize(); slow = 0; lock = t + 20000; } }
  };
  const dispose = () => { Object.values(geos).forEach(g => g.dispose()); pinGeo.dispose(); headGeo.dispose(); capGeo.dispose(); Object.values(M).forEach(m => { if (m.map) m.map.dispose(); m.dispose(); }); rough.dispose(); env.dispose(); ground.geometry.dispose(); ground.material.dispose(); renderer.dispose(); };
  return { update, dispose, resize, parts, states: Object.keys(STATES), set paused(v) { paused = v; if (!v) { lastT = performance.now(); settled = 0; } }, get paused() { return paused; }, get dpr() { return dpr; }, get lost() { return lost; }, renderer, camera, scene,
    marks,
    info: () => ({ calls: renderer.info.render.calls, triangles: renderer.info.render.triangles, textures: renderer.info.memory.textures, geometries: renderer.info.memory.geometries, dpr }) };
}
