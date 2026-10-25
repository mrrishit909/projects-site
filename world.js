/* The hall. Every case study is one screen on the walls of a long dark hall over a reflecting floor; the four showcased
   projects hang as large live screens (their motion-tile scenes drawn each frame into a canvas texture, with a CRT pass:
   curvature, scanlines, phosphor halo, a rolling bar) on alternating walls; at the far end the wall screens leave the walls
   and assemble into one grid. Light shafts, dust, fog, one post pass (grain, vignette, aberration by speed). The camera is
   driven by poses from home.js; this file only knows how to render and how to move things between layouts. */
import * as THREE from "three";

export function createWorld({ canvas, ATLAS, ITEMS, flagships, phone, reduced }) {
  const N = ITEMS.length, cl = v => Math.max(0, Math.min(1, v)), lerp = (a, b, t) => a + (b - a) * t, sm = t => t * t * (3 - 2 * t);
  let gl = null;
  try { gl = canvas.getContext("webgl2", { antialias: false, alpha: false, powerPreference: "high-performance" }); } catch (_) {}
  if (!gl) return null;
  const renderer = new THREE.WebGLRenderer({ canvas, context: gl, antialias: false, alpha: false });
  let dpr = Math.min(devicePixelRatio || 1, phone() ? 1.25 : 1.5);
  renderer.setPixelRatio(dpr); renderer.setClearColor(0x07070c, 1); renderer.outputColorSpace = THREE.SRGBColorSpace;
  const scene = new THREE.Scene(); const INK = new THREE.Color(0x07070c); scene.background = INK;
  const camera = new THREE.PerspectiveCamera(50, 1, 0.1, 400);
  const FOG = { color: INK, density: 0.017 };
  const FOG_GLSL = `uniform vec3 uFog; uniform float uFogD; float fogF(float d){ return 1.0 - exp(-uFogD * uFogD * d * d); }`;

  /* ---- the hall ---- */
  const HALL = { w: 11, rows: 4, y0: 1.25, py: 1.5, cols: 28, pz: 2.15, z0: 2, ceiling: 7.2 };
  const TILE_W = 2.0, TILE_H = TILE_W / 1.75;
  const END_Z = -70, GRID_COLS = 16, GRID_PX = 2.1, GRID_PY = 1.3;
  const uni = { lightZ: { value: 999 }, dim: { value: 0 }, sweepZ: { value: 999 }, wallLit: { value: 1 } };

  const atlasCount = Math.max(...ITEMS.map(it => it.a)) + 1, perAtlas = Array.from({ length: atlasCount }, () => []);
  ITEMS.forEach((it, i) => perAtlas[it.a].push(i));
  const slot = new Int32Array(N);
  const tileGeo = new THREE.PlaneGeometry(TILE_W, TILE_H, 1, 1);
  const makeMaterial = (map, mirror) => new THREE.ShaderMaterial({
    transparent: mirror, depthWrite: !mirror, side: THREE.DoubleSide,
    uniforms: { uMap: { value: map }, uCols: { value: ATLAS.cols }, uRows: { value: ATLAS.rows }, uFog: { value: FOG.color }, uFogD: { value: FOG.density }, uTime: { value: 0 }, uMirror: { value: mirror ? 1 : 0 },
      uLightZ: uni.lightZ, uDim: uni.dim, uSweepZ: uni.sweepZ, uWallLit: uni.wallLit },
    vertexShader: `attribute vec2 aCell; attribute float aLit; attribute float aSel; uniform float uCols; uniform float uRows;
      varying vec2 vUv; varying float vLit; varying float vSel; varying float vDist; varying float vY; varying float vZ; varying float vFace;
      void main() { vUv = (aCell + vec2(uv.x, 1.0 - uv.y)) / vec2(uCols, uRows); vLit = aLit; vSel = aSel;
        vec4 wp = instanceMatrix * vec4(position, 1.0); vec4 mvp = modelViewMatrix * wp; vec4 w = modelMatrix * wp; vY = w.y; vZ = w.z; vDist = -mvp.z;
        vec3 n = normalize((modelViewMatrix * instanceMatrix * vec4(0.0, 0.0, 1.0, 0.0)).xyz); vFace = n.z;
        gl_Position = projectionMatrix * mvp; }`,
    fragmentShader: `precision highp float; uniform sampler2D uMap; uniform float uTime; uniform float uMirror; uniform float uLightZ; uniform float uDim; uniform float uSweepZ; uniform float uWallLit; ${FOG_GLSL}
      varying vec2 vUv; varying float vLit; varying float vSel; varying float vDist; varying float vY; varying float vZ; varying float vFace;
      float hash(vec2 p) { return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }
      void main() { vec3 c = texture2D(uMap, vUv).rgb;
        vec2 e = abs(fract(vUv * vec2(${ATLAS.cols}.0, ${ATLAS.rows}.0)) - 0.5); float frame = smoothstep(0.5, 0.47, max(e.x, e.y));
        float back = step(vFace, 0.0); c = mix(c, vec3(0.06, 0.06, 0.08), back * 0.92);
        // the intro: screens past the light front are still dark, with a flicker as they come on
        float on = smoothstep(uLightZ - 4.0, uLightZ + 2.0, vZ); on *= mix(1.0, step(0.35, hash(vec2(floor(uTime * 24.0), vZ))), (1.0 - on) * 0.5 + step(on, 0.999) * 0.35);
        float sweep = exp(-abs(vZ - uSweepZ) * 0.35) * 0.9;
        float lit = (mix(0.3, 1.0, vLit) * uWallLit + vSel * 0.35 + sweep) * on * (1.0 - uDim);
        c = c * lit * frame + vec3(0.02, 0.02, 0.03) * (1.0 - frame);
        float scan = 0.96 + 0.04 * sin(vUv.y * 900.0 + uTime * 2.0); c *= mix(1.0, scan, 0.5 * vLit);
        float a = 1.0; if (uMirror > 0.5) { a = clamp(1.0 + vY / 7.0, 0.0, 1.0) * 0.3; }
        c = mix(c, uFog, fogF(vDist));
        gl_FragColor = vec4(c, a); }`,
  });
  const meshes = [], mirrors = [], cells = [], lits = [], sels = [], tex = [];
  const bitmaps = new THREE.ImageBitmapLoader().setOptions({ imageOrientation: "from-image", premultiplyAlpha: "none" });
  const atlasReady = [];
  for (let a = 0; a < atlasCount; a++) {
    const t = new THREE.Texture(); t.flipY = false; t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4; t.generateMipmaps = true; t.minFilter = THREE.LinearMipmapLinearFilter;
    atlasReady.push(new Promise(res => bitmaps.load(`assets/atlas/atlas-${a}${phone() ? "-2k" : ""}.webp`, bm => { t.image = bm; t.needsUpdate = true; res(); }, undefined, () => res())));
    tex.push(t);
    const n = perAtlas[a].length, geo = tileGeo.clone();
    const cell = new Float32Array(n * 2), lit = new Float32Array(n), sel = new Float32Array(n);
    perAtlas[a].forEach((idx, k) => { cell[k * 2] = ITEMS[idx].c; cell[k * 2 + 1] = ITEMS[idx].r; lit[k] = 1; slot[idx] = k; });
    geo.setAttribute("aCell", new THREE.InstancedBufferAttribute(cell, 2)); geo.setAttribute("aLit", new THREE.InstancedBufferAttribute(lit, 1)); geo.setAttribute("aSel", new THREE.InstancedBufferAttribute(sel, 1));
    const m = new THREE.InstancedMesh(geo, makeMaterial(t, false), n); m.frustumCulled = false; m.userData.atlas = a;
    const mm = new THREE.InstancedMesh(geo, makeMaterial(t, true), n); mm.frustumCulled = false; mm.renderOrder = -1;
    meshes.push(m); mirrors.push(mm); cells.push(cell); lits.push(lit); sels.push(sel);
  }
  const walls = new THREE.Group(), mirrorGroup = new THREE.Group();
  meshes.forEach(m => walls.add(m)); mirrors.forEach(m => mirrorGroup.add(m)); mirrorGroup.scale.y = -1;
  scene.add(walls, mirrorGroup);

  /* floor: ink, a faint grid, a glow lane down the middle; it does not write depth so the mirrored screens show through */
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(400, 400), new THREE.ShaderMaterial({
    depthWrite: false, uniforms: { uFog: { value: FOG.color }, uFogD: { value: FOG.density }, uDim: uni.dim },
    vertexShader: `varying vec2 vP; varying float vDist; void main() { vP = position.xy; vec4 mvp = modelViewMatrix * vec4(position, 1.0); vDist = -mvp.z; gl_Position = projectionMatrix * mvp; }`,
    fragmentShader: `precision highp float; uniform float uDim; ${FOG_GLSL} varying vec2 vP; varying float vDist;
      void main() { vec2 g = abs(fract(vP / 2.0) - 0.5); float line = 1.0 - smoothstep(0.0, 0.03, min(g.x, g.y));
        float lane = exp(-vP.x * vP.x / 6.0) * 0.08;
        vec3 c = vec3(0.03, 0.03, 0.05) + line * 0.04 + vec3(0.14, 0.11, 0.18) * lane * (1.0 - uDim);
        c = mix(c, uFog, fogF(vDist)); gl_FragColor = vec4(c, 1.0); }`,
  }));
  floor.rotation.x = -Math.PI / 2; floor.position.y = -0.02; scene.add(floor);
  /* ceiling: a dark slab with a hot hairline down the middle */
  const ceiling = new THREE.Mesh(new THREE.PlaneGeometry(HALL.w + 2, 120), new THREE.ShaderMaterial({
    uniforms: { uFog: { value: FOG.color }, uFogD: { value: FOG.density }, uDim: uni.dim },
    vertexShader: `varying vec2 vP; varying float vDist; void main() { vP = position.xy; vec4 mvp = modelViewMatrix * vec4(position, 1.0); vDist = -mvp.z; gl_Position = projectionMatrix * mvp; }`,
    fragmentShader: `precision highp float; uniform float uDim; ${FOG_GLSL} varying vec2 vP; varying float vDist;
      void main() { float rail = exp(-vP.x * vP.x * 40.0) * (1.0 - uDim); vec3 c = vec3(0.035, 0.035, 0.05) + vec3(1.0, 0.3, 0.0) * rail * 0.5;
        c = mix(c, uFog, fogF(vDist)); gl_FragColor = vec4(c, 1.0); }`,
  }));
  ceiling.rotation.x = Math.PI / 2; ceiling.position.set(0, HALL.ceiling, -40); scene.add(ceiling);

  /* light shafts: tall additive planes hanging from the ceiling along the hall */
  const shaftMat = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
    uniforms: { uTime: { value: 0 }, uDim: uni.dim },
    vertexShader: `varying vec2 vUv; void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
    fragmentShader: `precision highp float; uniform float uTime; uniform float uDim; varying vec2 vUv;
      void main() { float x = smoothstep(0.0, 0.5, vUv.x) * smoothstep(1.0, 0.5, vUv.x); float y = pow(vUv.y, 1.6);
        float a = x * y * (0.05 + 0.02 * sin(uTime * 0.7 + vUv.y * 6.0)) * (1.0 - uDim);
        gl_FragColor = vec4(0.75, 0.72, 0.9, a); }`,
  });
  for (let i = 0; i < 9; i++) { const s = new THREE.Mesh(new THREE.PlaneGeometry(3.4, HALL.ceiling), shaftMat); s.position.set((i % 2 ? 1.8 : -1.8), HALL.ceiling / 2, -2 - i * 7.2); s.rotation.y = (i % 2 ? -1 : 1) * 0.35; scene.add(s); }

  /* dust */
  const DUST = phone() ? 300 : 800, dustGeo = new THREE.BufferGeometry(), dp = new Float32Array(DUST * 3), ds = new Float32Array(DUST);
  for (let i = 0; i < DUST; i++) { dp[i * 3] = (Math.random() - 0.5) * 12; dp[i * 3 + 1] = Math.random() * 7; dp[i * 3 + 2] = 6 - Math.random() * 80; ds[i] = Math.random(); }
  dustGeo.setAttribute("position", new THREE.BufferAttribute(dp, 3)); dustGeo.setAttribute("aSeed", new THREE.BufferAttribute(ds, 1));
  const dust = new THREE.Points(dustGeo, new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    uniforms: { uTime: { value: 0 }, uDpr: { value: dpr }, uFog: { value: FOG.color }, uFogD: { value: FOG.density }, uDim: uni.dim },
    vertexShader: `attribute float aSeed; uniform float uTime; uniform float uDpr; varying float vA; varying float vDist;
      void main() { vec3 p = position; p.y = mod(p.y + uTime * (0.1 + aSeed * 0.2), 7.0); p.x += sin(uTime * 0.3 + aSeed * 20.0) * 0.5;
        vec4 mvp = modelViewMatrix * vec4(p, 1.0); vDist = -mvp.z; vA = 0.25 + 0.75 * aSeed; gl_Position = projectionMatrix * mvp; gl_PointSize = (1.2 + aSeed * 2.0) * uDpr * 80.0 / max(1.0, -mvp.z); }`,
    fragmentShader: `precision highp float; uniform float uDim; ${FOG_GLSL} varying float vA; varying float vDist; void main() { float d = length(gl_PointCoord - 0.5); if (d > 0.5) discard; float a = (1.0 - d * 2.0) * vA * 0.5 * (1.0 - fogF(vDist)) * (1.0 - uDim * 0.7); gl_FragColor = vec4(0.85, 0.82, 0.9, a); }`,
  }));
  scene.add(dust);

  /* ---- the four showcased screens: live canvases with a CRT pass ---- */
  const CRT = new THREE.ShaderMaterial({
    uniforms: { uMap: { value: null }, uTime: { value: 0 }, uFog: { value: FOG.color }, uFogD: { value: FOG.density }, uOn: { value: 1 }, uDim: uni.dim },
    vertexShader: `varying vec2 vUv; varying float vDist; void main() { vUv = uv; vec4 mvp = modelViewMatrix * vec4(position, 1.0); vDist = -mvp.z; gl_Position = projectionMatrix * mvp; }`,
    fragmentShader: `precision highp float; uniform sampler2D uMap; uniform float uTime; uniform float uOn; uniform float uDim; ${FOG_GLSL} varying vec2 vUv; varying float vDist;
      float hash(vec2 p) { p = fract(p * vec2(123.34, 456.21)); p += dot(p, p + 45.32); return fract(p.x * p.y); }
      void main() { vec2 uv = vUv * 2.0 - 1.0; vec2 o = uv.yx * uv.yx; uv += uv * o * 0.035; uv = uv * 0.5 + 0.5;
        vec2 inb = step(vec2(0.0), uv) * step(uv, vec2(1.0)); float inside = inb.x * inb.y; vec2 ed = min(uv, 1.0 - uv); inside *= smoothstep(0.0, 0.012, min(ed.x, ed.y));
        vec2 dir = uv - 0.5; vec2 ao = dir * 0.0025;
        vec3 c; c.r = texture2D(uMap, uv + ao).r; c.g = texture2D(uMap, uv).g; c.b = texture2D(uMap, uv - ao).b;
        float s = 0.0035; vec3 wide = texture2D(uMap, uv + vec2(s, 0.0)).rgb + texture2D(uMap, uv - vec2(s, 0.0)).rgb + texture2D(uMap, uv + vec2(0.0, s)).rgb + texture2D(uMap, uv - vec2(0.0, s)).rgb; c += wide * 0.07;
        float sl = sin(uv.y * 3.14159 * 420.0 + uTime * 4.0); c *= mix(0.9, 1.0, sl * sl);
        float bar = fract(uv.y * 0.5 - uTime * 0.06); bar = smoothstep(0.0, 0.05, bar) * smoothstep(0.18, 0.05, bar); c += bar * 0.035;
        c *= 1.0 - 0.02 * sin(uTime * 8.0);
        c += (hash(vUv + fract(uTime * 0.37)) - 0.5) * 0.03;
        c = mix(vec3(0.02, 0.02, 0.03), c, inside) * uOn * (1.0 - uDim * 0.6);
        c = mix(c, uFog, fogF(vDist)); gl_FragColor = vec4(c, 1.0); }`,
  });
  const glowMat = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, uniforms: { uOn: { value: 1 }, uDim: uni.dim },
    vertexShader: `varying vec2 vUv; void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
    fragmentShader: `precision highp float; uniform float uOn; uniform float uDim; varying vec2 vUv; void main() { vec2 d = abs(vUv - 0.5) * 2.0; float a = (1.0 - smoothstep(0.55, 1.0, max(d.x, d.y))) * 0.16 * uOn * (1.0 - uDim); gl_FragColor = vec4(0.6, 0.6, 0.8, a); }`,
  });
  /* the gauge: the source line made physical. A long orange bar from min to max, ticks, a white marker that rides to the
     project's figure, and a plate naming the evidence. Built from primitives (the img2threejs way), one per room. */
  const HOT = new THREE.Color(0xff4d00);
  const makeGauge = (f, len) => {
    const g = new THREE.Group();
    const bar = new THREE.Mesh(new THREE.BoxGeometry(len, 0.05, 0.05), new THREE.MeshBasicMaterial({ color: 0x2a2a33 })); g.add(bar);
    const lit = new THREE.Mesh(new THREE.BoxGeometry(len, 0.07, 0.07), new THREE.MeshBasicMaterial({ color: HOT })); lit.position.x = -len / 2; lit.scale.x = 0.001; g.add(lit);
    for (let k = 0; k <= 10; k++) { const t = new THREE.Mesh(new THREE.BoxGeometry(0.02, k % 5 ? 0.14 : 0.26, 0.02), new THREE.MeshBasicMaterial({ color: 0x8a8a95 })); t.position.set(-len / 2 + (k / 10) * len, -0.16, 0); g.add(t); }
    const marker = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.34, 0.08), new THREE.MeshBasicMaterial({ color: 0xffffff })); marker.position.x = -len / 2; g.add(marker);
    const cv = document.createElement("canvas"); cv.width = 1024; cv.height = 128; const c2 = cv.getContext("2d");
    c2.fillStyle = "#0a0a10"; c2.fillRect(0, 0, 1024, 128); c2.fillStyle = "#ff4d00"; c2.fillRect(0, 0, 10, 128);
    c2.font = "500 44px Geist, Helvetica, Arial, sans-serif"; c2.fillStyle = "#ffffff"; c2.fillText(f.evidence, 40, 58);
    c2.font = "400 34px Geist, Helvetica, Arial, sans-serif"; c2.fillStyle = "#9d9da6"; c2.fillText(`${f.min} to ${f.max}${f.unit.trim().startsWith("of") ? "" : f.unit}, checked`, 40, 104);
    const pt = new THREE.CanvasTexture(cv); pt.colorSpace = THREE.SRGBColorSpace;
    const plate = new THREE.Mesh(new THREE.PlaneGeometry(2.4, 0.3), new THREE.MeshBasicMaterial({ map: pt })); plate.position.set(-len / 2 + 1.2, -0.62, 0); g.add(plate);
    g.userData = { lit, marker, len }; return g;
  };
  const rooms = flagships.map((f, i) => {
    const def = (window.SCENES || {})[f.slug] || null, aspect = def ? def.aspect : 1.614;
    const W = phone() ? 1024 : 1536, H = Math.round(W / aspect);
    const cv = document.createElement("canvas"); cv.width = W; cv.height = H; const g = cv.getContext("2d");
    const texC = new THREE.CanvasTexture(cv); texC.colorSpace = THREE.SRGBColorSpace; texC.anisotropy = 8; texC.generateMipmaps = false; texC.minFilter = THREE.LinearFilter;
    const mat = CRT.clone(); mat.uniforms.uMap.value = texC; mat.uniforms.uDim = uni.dim;
    const stage = f.stage || "wall", sw = stage === "ahead" ? (phone() ? 7.6 : 9.2) : stage === "floor" ? (phone() ? 5.6 : 7.8) : (phone() ? 6.0 : 7.4), sh = sw / aspect;
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(sw, sh), mat);
    const back = new THREE.Mesh(new THREE.PlaneGeometry(sw + 1.4, sh + 1.4), new THREE.MeshBasicMaterial({ color: 0x0a0a10 }));
    const glow = new THREE.Mesh(new THREE.PlaneGeometry(sw * 1.5, sh * 1.6), glowMat.clone()); glow.material.uniforms.uDim = uni.dim;
    const grp = new THREE.Group(); grp.add(back, glow, mesh); back.position.z = -0.05; glow.position.z = -0.03;
    const gauge = makeGauge(f, sw); gauge.position.set(0, -sh / 2 - 0.55, 0.02); grp.add(gauge);
    const side = f.side, z = f.z;
    if (stage === "wall") { grp.position.set(side < 0 ? -HALL.w / 2 + 0.3 : HALL.w / 2 - 0.3, 3.6, z); grp.rotation.y = side < 0 ? Math.PI / 2 : -Math.PI / 2; }
    else if (stage === "floor") { grp.position.set(0, 0.06, z - 0.5); grp.rotation.x = -Math.PI / 2; back.visible = false; }
    else if (stage === "ahead") { grp.position.set(0, 3.6, z - 4); }
    else { grp.position.set(0, 3.9, z); mesh.material.side = THREE.DoubleSide; back.material.side = THREE.DoubleSide; }
    scene.add(grp);
    // the drop: the ceiling's hot line comes down to this room's gauge
    const gw = new THREE.Vector3(); grp.updateMatrixWorld(true); gauge.getWorldPosition(gw);
    const dropH = stage === "floor" ? HALL.ceiling : HALL.ceiling - gw.y, drop = new THREE.Mesh(new THREE.BoxGeometry(0.035, dropH, 0.035), new THREE.MeshBasicMaterial({ color: HOT }));
    // the drop hangs beside the screen's edge, never through it
    const edge = stage === "wall" ? { x: gw.x - side * 0.05, z: gw.z + sw / 2 + 0.45 } : stage === "floor" ? { x: gw.x - sw / 2 - 0.5, z: gw.z } : stage === "ahead" ? { x: gw.x - sw / 2 - 0.5, z: gw.z + 0.1 } : { x: gw.x - sw / 2 - 0.6, z: gw.z };
    drop.position.set(edge.x, HALL.ceiling - dropH / 2, edge.z); drop.scale.y = 0.001; scene.add(drop);
    const r = { slug: f.slug, def, g, cv, W, H, texC, mesh, mat, glow, grp, gauge, drop, stage, z, S: null, ready: false, last: -1, t0: 0, frac: f.frac, spin0: grp.rotation.y };
    if (def) Promise.all([document.fonts.load("500 20px Geist"), document.fonts.load("400 20px Geist"), document.fonts.load('400 20px "Geist Mono"')]).catch(() => 0)
      .then(() => def.init ? def.init(W, H, window.T) : {}).then(S => { r.S = S || {}; r.ready = true; });
    return r;
  });
  const drawRoom = (r, time, on) => {
    if (!r.ready || !r.def) return;
    if (on && !r.t0) r.t0 = time; if (!on) r.t0 = 0;
    const u = r.t0 ? Math.min(0.92, (time - r.t0) / (r.def.seconds || 6)) : 0.92, g = r.g, W = r.W, H = r.H;
    if (u === r.last && !on) return; r.last = u;
    const grad = g.createRadialGradient(W / 2, H / 2, 0, W / 2, H / 2, Math.max(W, H) * 0.75); grad.addColorStop(0, r.def.bg[0]); grad.addColorStop(1, r.def.bg[1]);
    g.setTransform(1, 0, 0, 1, 0, 0); g.globalAlpha = 1; g.fillStyle = grad; g.fillRect(0, 0, W, H);
    r.def.draw(g, u, W, H, r.S, window.T); r.texC.needsUpdate = true;
  };

  /* ---- post pass ---- */
  const rt = new THREE.WebGLRenderTarget(1, 1, { minFilter: THREE.LinearFilter, magFilter: THREE.LinearFilter, depthBuffer: true });
  const postScene = new THREE.Scene(), postCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
  const post = new THREE.ShaderMaterial({
    uniforms: { tDiffuse: { value: rt.texture }, uTime: { value: 0 }, uAb: { value: 0 }, uRes: { value: new THREE.Vector2(1, 1) }, uFade: { value: 1 } },
    vertexShader: `varying vec2 vUv; void main() { vUv = uv; gl_Position = vec4(position, 1.0); }`,
    fragmentShader: `precision highp float; uniform sampler2D tDiffuse; uniform float uTime; uniform float uAb; uniform vec2 uRes; uniform float uFade; varying vec2 vUv;
      float hash(vec2 p) { return fract(sin(dot(p, vec2(12.9898, 78.233)) + uTime) * 43758.5453); }
      void main() { vec2 d = (vUv - 0.5) * uAb;
        float r = texture2D(tDiffuse, vUv + d).r, g = texture2D(tDiffuse, vUv).g, b = texture2D(tDiffuse, vUv - d).b; vec3 c = vec3(r, g, b);
        float v = smoothstep(1.25, 0.35, length((vUv - 0.5) * vec2(1.0, uRes.y / uRes.x) * 1.2)); c *= mix(0.7, 1.0, v);
        c += (hash(gl_FragCoord.xy) - 0.5) * 0.05; c *= uFade;
        gl_FragColor = vec4(c, 1.0); }`,
  });
  postScene.add(new THREE.Mesh(new THREE.PlaneGeometry(2, 2), post));
  const resize = () => { const w = innerWidth, h = innerHeight; renderer.setSize(w, h, false); rt.setSize(Math.round(w * dpr), Math.round(h * dpr)); camera.aspect = w / h; camera.updateProjectionMatrix(); post.uniforms.uRes.value.set(w, h); };
  addEventListener("resize", resize); resize();

  /* ---- layouts: hall walls, and the end-wall grid ---- */
  const T = new Float32Array(N * 5), put = (i, x, y, z, yaw, s) => { T[i * 5] = x; T[i * 5 + 1] = y; T[i * 5 + 2] = z; T[i * 5 + 3] = yaw; T[i * 5 + 4] = s; };
  const LAYOUT = {
    hall() { for (let i = 0; i < N; i++) { const wall = i % 2 ? 1 : -1, k = Math.floor(i / 2), col = Math.floor(k / HALL.rows), row = k % HALL.rows;
      put(i, wall * (HALL.w / 2 - 0.02), HALL.y0 + row * HALL.py, HALL.z0 - col * HALL.pz, wall * -Math.PI / 2, 1); } },
    grid() { const cols = phone() ? 12 : GRID_COLS, rows = Math.ceil(N / cols), px = phone() ? 2.1 : GRID_PX;
      for (let i = 0; i < N; i++) { const c = i % cols, r = Math.floor(i / cols); put(i, (c - (cols - 1) / 2) * px, 1.2 + (rows - 1 - r) * GRID_PY + TILE_H / 2, END_Z, 0, 1); } },
  };
  const layouts = {}; const layoutFor = n => { if (!layouts[n]) { LAYOUT[n](); layouts[n] = Float32Array.from(T); } return layouts[n]; };
  addEventListener("resize", () => { layouts.hall = null; layouts.grid = null; });
  const now = new Float32Array(N * 5), seed = new Float32Array(N);
  { const A = layoutFor("hall"); for (let i = 0; i < N; i++) { seed[i] = Math.random(); for (let j = 0; j < 5; j++) now[i * 5 + j] = A[i * 5 + j]; } }

  /* ---- picking: which screen is under the pointer ---- */
  const ray = new THREE.Raycaster(), ndc = new THREE.Vector2();
  const pick = (x, y) => { ndc.set((x / innerWidth) * 2 - 1, -((y / innerHeight) * 2 - 1)); ray.setFromCamera(ndc, camera); const hits = ray.intersectObjects(meshes, false); if (!hits.length || hits[0].distance > 40) return -1; return perAtlas[hits[0].object.userData.atlas][hits[0].instanceId]; };

  /* ---- per frame ---- */
  const M = new THREE.Matrix4(), Q = new THREE.Quaternion(), P = new THREE.Vector3(), S = new THREE.Vector3(), UP = new THREE.Vector3(0, 1, 0), AIM = new THREE.Vector3();
  const state = { eye: new THREE.Vector3(0, 3.3, 7), aim: new THREE.Vector3(0, 3.4, -40), fov: 50, gridMix: 0, lit: 1, sel: -1, roomOn: -1, ab: 0, fade: 1 };
  let frames = 0, slow = 0, lastT = performance.now();
  const update = (t, pose) => {
    const dt = Math.min(0.05, (t - lastT) / 1000); lastT = t; const time = t / 1000;
    const ease = reduced ? 1 : 1 - Math.pow(0.004, dt);
    camera.position.set(pose.eye.x, pose.eye.y, pose.eye.z); AIM.set(pose.aim.x, pose.aim.y, pose.aim.z); camera.lookAt(AIM); if (Math.abs(camera.fov - pose.fov) > 0.01) { camera.fov = pose.fov; camera.updateProjectionMatrix(); }
    const A = layoutFor("hall"), B = layoutFor("grid"), mix = pose.gridMix;
    const cz = camera.position.z, cx = camera.position.x;
    for (let i = 0; i < N; i++) {
      const o = i * 5, d = seed[i] * 0.35, m = sm(cl((mix - d) / 0.65));
      for (let j = 0; j < 5; j++) if (j !== 3) now[o + j] = lerp(now[o + j], lerp(A[o + j], B[o + j], m), ease);
      // a wall screen turns to face the visitor as they pass, and settles back once they have gone by
      let yaw = lerp(A[o + 3], B[o + 3], m);
      if (m < 0.5) { const dz = now[o + 2] - cz, near = 1 - cl((Math.abs(dz + 2.5) - 1.5) / 5); if (near > 0) yaw = lerp(yaw, Math.atan2(cx - now[o], cz - now[o + 2]), near * 0.55); }
      now[o + 3] = lerp(now[o + 3], yaw, ease);
      const a = ITEMS[i].a, kk = slot[i];
      P.set(now[o], now[o + 1] + (reduced ? 0 : Math.sin(time * 0.7 + seed[i] * 6.28) * 0.01 * mix), now[o + 2]);
      Q.setFromAxisAngle(UP, now[o + 3]); S.setScalar(now[o + 4]); M.compose(P, Q, S); meshes[a].setMatrixAt(kk, M); mirrors[a].setMatrixAt(kk, M);
      sels[a][kk] = lerp(sels[a][kk], i === pose.sel ? 1 : 0, ease);
    }
    for (let a = 0; a < atlasCount; a++) { meshes[a].instanceMatrix.needsUpdate = true; mirrors[a].instanceMatrix.needsUpdate = true; meshes[a].geometry.attributes.aSel.needsUpdate = true; meshes[a].material.uniforms.uTime.value = time; mirrors[a].material.uniforms.uTime.value = time; }
    uni.wallLit.value = lerp(uni.wallLit.value, pose.wallLit, ease); uni.dim.value = lerp(uni.dim.value, pose.dim, ease); uni.sweepZ.value = pose.sweepZ === 999 ? cz - 4 : pose.sweepZ; uni.lightZ.value = pose.lightZ;
    rooms.forEach((r, i) => { const near = Math.abs(camera.position.z - r.z) < 26 && mix < 0.9; r.grp.visible = r.drop.visible = near; if (near && (frames % 2 === i % 2)) drawRoom(r, time, pose.roomOn === i); r.mat.uniforms.uTime.value = time; r.mat.uniforms.uOn.value = lerp(r.mat.uniforms.uOn.value, pose.roomOn === i ? 1 : 0.55, ease); r.glow.material.uniforms.uOn.value = r.mat.uniforms.uOn.value;
      const gp = pose.gauge && pose.gauge[i] != null ? pose.gauge[i] : 0, u = r.gauge.userData, x = u.len * gp * r.frac;
      u.lit.scale.x = lerp(u.lit.scale.x, Math.max(0.001, x / u.len), ease); u.lit.position.x = -u.len / 2 + (u.lit.scale.x * u.len) / 2; u.marker.position.x = lerp(u.marker.position.x, -u.len / 2 + x, ease);
      r.drop.scale.y = lerp(r.drop.scale.y, pose.roomOn === i ? 1 : 0.001, ease);
      if (r.stage === "float") r.grp.rotation.y = lerp(r.grp.rotation.y, (pose.spin || 0), ease); });
    dust.material.uniforms.uTime.value = time; shaftMat.uniforms.uTime.value = time;
    post.uniforms.uTime.value = time; post.uniforms.uAb.value = lerp(post.uniforms.uAb.value, pose.ab, 0.1); post.uniforms.uFade.value = pose.fade;
    renderer.setRenderTarget(rt); renderer.render(scene, camera); renderer.setRenderTarget(null); renderer.render(postScene, postCam);
    if (++frames > 90 && dt > 0.026 && ++slow > 40 && dpr > 1) { dpr = 1; renderer.setPixelRatio(1); dust.material.uniforms.uDpr.value = 1; resize(); slow = -1e9; }
  };
  return { update, pick, atlasReady: Promise.all(atlasReady), rooms, HALL, END_Z, ITEMS, camera, renderer };
}
