/* THE BLOCK: one solid of record slips (an InstancedMesh, one draw call) that the page machines per chapter:
   BLOCK, SLICE (the star schema: one fact table and four dimensions step out), LAYER (dbt's three strata and 31 tests
   lighting), BEND (24 monthly columns with a fanned 12-month range), OPEN (the stack opens and one cited slip lifts out),
   HOUR (cut at the on-time rate for a departure hour), SHEET (a flat index of slips, 224 lit), REST. Every slip's position,
   rotation and tone is a target that the frame loop lerps toward, so any two states blend by scroll and any interruption
   is smooth. home.js owns what the state is; this file owns every instance matrix and colour.
   The opening (pose.introK 0..1): the slips loosen apart (anticipation), a plane of light passes down through them and
   collects each row as it passes (the check), and the block settles. Under reduced motion only the light passes.
   The count of slips (6 x 40 x 6 = 1,440; 6 x 28 x 6 on phones) is an artistic construction, not a record count.
   Lambert lighting, one shadow-casting key light with a shadow-only ground under the block, no post pass, transparent
   canvas: the CSS field is the ground. Starts at pixel ratio 1 and raises it to 1.5 only with measured headroom. */
import * as THREE from "three";

export function createBlock({ canvas, phone, reduced, series, fan }) {
  let gl = null;
  try { gl = canvas.getContext("webgl2", { antialias: true, alpha: true, premultipliedAlpha: true, powerPreference: "high-performance" }); } catch (_) {}
  if (!gl) return null;
  const renderer = new THREE.WebGLRenderer({ canvas, context: gl, antialias: true, alpha: true });
  let dpr = 1; renderer.setPixelRatio(dpr); renderer.setClearColor(0x000000, 0); renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(32, 1, 0.1, 100); camera.position.set(0, 0, 18);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x7a5a5a, 1.05));
  const key = new THREE.DirectionalLight(0xffffff, 1.7); key.position.set(-6, 10, 9); key.castShadow = true;
  key.shadow.mapSize.set(1024, 1024); key.shadow.camera.left = -14; key.shadow.camera.right = 14; key.shadow.camera.top = 14; key.shadow.camera.bottom = -14; key.shadow.camera.near = 1; key.shadow.camera.far = 50; key.shadow.bias = -0.0008; key.shadow.normalBias = 0.02;
  scene.add(key); scene.add(key.target);
  const fill = new THREE.DirectionalLight(0xffffff, 0.3); fill.position.set(7, -2, 5); scene.add(fill);

  /* ---- the slips ---- */
  const COLS = 6, ROWS = phone() ? 28 : 40, LAYERS = 6, N = COLS * ROWS * LAYERS;
  const PX = 1.0, PY = 0.1, PZ = 0.6, W = COLS * PX, H = ROWS * PY, D = LAYERS * PZ;
  const geo = new THREE.BoxGeometry(0.92, 0.07, 0.54);
  const mat = new THREE.MeshLambertMaterial({ color: 0xffffff });
  const mesh = new THREE.InstancedMesh(geo, mat, N); mesh.frustumCulled = false; mesh.castShadow = true; mesh.receiveShadow = true;
  mesh.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(N * 3), 3);
  const group = new THREE.Group(); group.add(mesh); scene.add(group);
  // the ground: it shows nothing but the block's shadow, so the block sits on the field instead of floating in it
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(40, 40), new THREE.ShadowMaterial({ opacity: 0.26 }));
  ground.rotation.x = -Math.PI / 2; ground.position.y = -H / 2 - 0.09; ground.receiveShadow = true; group.add(ground);
  const cl = v => Math.max(0, Math.min(1, v)), lerp = (a, b, t) => a + (b - a) * t, sm = t => t * t * (3 - 2 * t);
  const col = i => i % COLS, row = i => Math.floor(i / COLS) % ROWS, lay = i => Math.floor(i / (COLS * ROWS));
  // seeded noise so the loosening and the timing are reproducible
  let s = 7; const rnd = () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
  const seed = new Float32Array(N); for (let i = 0; i < N; i++) seed[i] = rnd();
  const sc = new Float32Array(N * 3); for (let i = 0; i < N * 3; i++) sc[i] = rnd() * 2 - 1;
  const grain = new Float32Array(N); for (let i = 0; i < N; i++) grain[i] = 1 - 0.035 * rnd();   // material variation per slip

  /* a state is 10 floats per slip: x y z, yaw pitch roll, sx sy sz, tone (0 base .. 1 lit) */
  const F = 10, mk = () => new Float32Array(N * F);
  const put = (T, i, x, y, z, yaw, pitch, roll, sx, sy, sz, tone) => { const o = i * F; T[o] = x; T[o + 1] = y; T[o + 2] = z; T[o + 3] = yaw; T[o + 4] = pitch; T[o + 5] = roll; T[o + 6] = sx; T[o + 7] = sy; T[o + 8] = sz; T[o + 9] = tone; };
  const base = i => [(col(i) - (COLS - 1) / 2) * PX, (row(i) - (ROWS - 1) / 2) * PY, (lay(i) - (LAYERS - 1) / 2) * PZ];
  // the forecast's columns: the last 24 months of the real series (passed in from the page), then 12 months that follow
  // last year's shape; the fan widens with the backtest's error at each horizon
  const months = (() => { const h = series && series.length === 24 ? series.slice() : Array.from({ length: 24 }, (_, k) => 1 + 0.07 * Math.sin((k % 12) / 12 * Math.PI * 2 - 1.9)); const mean = h.reduce((a, b) => a + b, 0) / h.length; const v = h.map(x => x / mean);
    for (let k = 0; k < 12; k++) v.push(v[12 + k] * 1.03); return v; })();
  const fanAt = h => (fan && fan[h] != null ? fan[h] : 2) / 2.6;
  const STATES = {
    block(T) { for (let i = 0; i < N; i++) { const [x, y, z] = base(i); put(T, i, x, y, z, 0, 0, 0, 1, 1, 1, 0); } },
    /* the star schema: the fact table stays, the four dimension blocks step out of its corners */
    slice(T) { for (let i = 0; i < N; i++) { let [x, y, z] = base(i); const c = col(i), r = row(i), up = r >= ROWS / 2 ? 1 : -1; let tone = 0, yaw = 0;
      if (c === 0 || c === COLS - 1) { const side = c === 0 ? -1 : 1; x += side * 1.6; y += up * 0.9; z += side * 0.6; yaw = side * 0.18; tone = 0.85; }
      put(T, i, x, y, z, yaw, 0, 0, 1, 1, 1, tone); } },
    /* dbt: staging, intermediate and marts lift apart; 31 slips light as the tests pass (home.js sets how many) */
    layer(T, tests) { for (let i = 0; i < N; i++) { let [x, y, z] = base(i); const r = row(i), stratum = r < ROWS / 3 ? 0 : r < (2 * ROWS) / 3 ? 1 : 2; y += stratum * 0.75 - 0.75; x += (stratum - 1) * 0.35;
      const isTest = i % 46 === 7, k = Math.floor(i / 46); put(T, i, x, y, z, 0, 0, 0, 1, 1, 1, isTest && k < tests ? 1 : 0); } },
    /* the forecast: 36 monthly columns of slips, 24 real months then 12 ahead that fan into the backtest's range */
    bend(T) { const MC = 36, per = Math.floor(N / MC), ZL = 3, rowsPer = Math.ceil(per / ZL); for (let i = 0; i < N; i++) { const m = Math.min(MC - 1, Math.floor(i / per)), k = i - m * per, zl = k % ZL, r = Math.floor(k / ZL), fut = m >= 24, v = months[m];
      const h = 1.0 + (v - 0.8) * 7.5, x = (m - (MC - 1) / 2) * 0.24, y0 = -2.0, step = h / rowsPer; let y = y0 + r * step, z = (zl - 1) * 0.55, pitch = 0, tone = fut ? 0.9 : 0;
      if (fut) { const t = fanAt(m - 24); y += (r / rowsPer - 0.5) * t * 2.2; z += (seed[i] - 0.5) * t * 0.9; pitch = (seed[i] - 0.5) * 0.5 * t; }
      put(T, i, x, y, z, 0, pitch, 0, 0.23, 1, 0.9, tone); } },
    /* retrieval: the stack opens, the halves turn apart, and one cited slip lifts out to face the visitor */
    open(T) { const cite = Math.floor(N * 0.62) - (Math.floor(N * 0.62) % COLS) + 4; for (let i = 0; i < N; i++) { let [x, y, z] = base(i); const left = col(i) < COLS / 2, s = left ? -1 : 1;
      if (i === cite) { put(T, i, 0, 2.6, 2.6, 0, 0.3, 0, 1.7, 1.7, 1.7, 1); continue; }
      x += s * 1.3; z += s * 0.4; put(T, i, x, y, z, s * 0.38, 0, 0, 1, 1, 1, 0); } },
    /* the check: cut at the on-time rate for the chosen hour; the late part slides aside and drops */
    hour(T, otp) { const cut = Math.round(otp * ROWS); for (let i = 0; i < N; i++) { let [x, y, z] = base(i); const r = row(i), late = r >= cut;
      if (late) { x += 2.2; y -= 0.5; z -= 0.4; } put(T, i, x, y, z, 0, 0, late ? 0.05 : 0, 1, 1, 1, late ? 0 : 1); } },
    /* the index: a flat sheet facing the visitor, 224 slips lit */
    sheet(T, lit) { const C = 32, R = Math.ceil(N / C); for (let i = 0; i < N; i++) { const c = i % C, r = Math.floor(i / C);
      put(T, i, (c - (C - 1) / 2) * 0.3, (r - (R - 1) / 2) * 0.19, 0, 0, Math.PI / 2, 0, 0.3, 1, 0.3, (i * 7) % Math.floor(N / lit) === 0 ? 1 : 0); } },
  };
  const cache = {}; const stateOf = (name, arg) => { const k = name + ":" + (arg == null ? "" : arg); if (!cache[k]) { const T = mk(); STATES[name](T, arg); cache[k] = T; } return cache[k]; };
  const now = mk(); now.set(stateOf("block")); const tgt = mk();
  const M = new THREE.Matrix4(), P = new THREE.Vector3(), Q = new THREE.Quaternion(), E = new THREE.Euler(), S = new THREE.Vector3();
  const C0 = new THREE.Color(), C1 = new THREE.Color(), CC = new THREE.Color();
  const PAL = { paper: [new THREE.Color(0xf0f0f0), new THREE.Color(0xffffff)], red: [new THREE.Color(0xcf2419), new THREE.Color(0xff6a52)] };

  /* ---- stage: where the block sits on screen, per viewport ---- */
  const resize = () => { const w = innerWidth, h = innerHeight; renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); };
  addEventListener("resize", resize); resize();
  const visH = () => 2 * camera.position.z * Math.tan((camera.fov / 2) * Math.PI / 180), visW = () => visH() * camera.aspect;
  const lost = { on: false, count: 0 };
  canvas.addEventListener("webglcontextlost", e => { e.preventDefault(); lost.on = true; lost.count++; document.documentElement.classList.remove("gl-on"); });
  canvas.addEventListener("webglcontextrestored", () => { lost.on = false; settledFrames = 0; document.documentElement.classList.add("gl-on"); });

  /* ---- the opening, per slip: how loose it is (0 tight .. 1 loosened) and the light band ---- */
  const TOP = H / 2 + 0.6, BOT = -H / 2 - 0.6;
  const introAt = (k, y, still) => {
    // k 0..0.3 loosen, 0.3..0.85 the plane passes from the top down and collects, 0.85..1 settle
    const planeY = lerp(TOP, BOT, sm(cl((k - 0.3) / 0.55)));
    const loose = still ? 0 : k < 0.3 ? sm(k / 0.3) : cl((planeY - y) / 0.5);
    const band = k > 0.28 && k < 0.9 ? Math.exp(-Math.abs(y - planeY) * 2.2) : 0;
    return [loose, band]; };

  /* ---- per frame ---- */
  const cur = { x: 0, y: 0, s: 1, rx: 0, ry: 0, pal: 0, tilt: { x: 0, y: 0 } };
  let lastT = performance.now(), frames = 0, fast = 0, slow = 0, lock = 0, settledFrames = 0;
  const update = (t, pose) => {
    if (lost.on) return;
    const dt = Math.min(0.05, (t - lastT) / 1000); lastT = t; frames++;
    const ease = reduced ? 1 : 1 - Math.pow(0.004, dt), quick = reduced ? 1 : 1 - Math.pow(0.0005, dt);
    const A = stateOf(pose.state, pose.arg), B = pose.next ? stateOf(pose.next, pose.nextArg) : A, u = sm(cl(pose.u || 0));
    const k = pose.introK == null ? 1 : pose.introK, opening = k < 1;
    let moved = 0;
    for (let i = 0; i < N; i++) { const o = i * F, d = seed[i] * 0.3, m = B === A ? 0 : sm(cl((u - d) / 0.7));
      for (let j = 0; j < F; j++) tgt[o + j] = lerp(A[o + j], B[o + j], m);
      if (opening) { const [loose] = introAt(k, A[o + 1], pose.introStill); if (loose > 0) { const q = i * 3, lift = loose * (0.6 + seed[i] * 0.5);
        tgt[o] += sc[q] * 1.4 * loose; tgt[o + 1] += sc[q + 1] * 0.8 * loose + lift; tgt[o + 2] += sc[q + 2] * 1.6 * loose;
        tgt[o + 3] += sc[q] * 0.5 * loose; tgt[o + 4] += sc[q + 1] * 0.35 * loose; tgt[o + 5] += sc[q + 2] * 0.4 * loose; } } }
    const immediate = opening && !reduced ? 1 - Math.pow(0.0002, dt) : ease;   // the opening answers its timeline tightly
    for (let i = 0; i < N; i++) { const o = i * F;
      for (let j = 0; j < F; j++) { const nv = lerp(now[o + j], tgt[o + j], j === 9 ? quick : immediate); moved = Math.max(moved, Math.abs(nv - now[o + j])); now[o + j] = nv; }
      P.set(now[o], now[o + 1], now[o + 2]); E.set(now[o + 4], now[o + 3], now[o + 5]); Q.setFromEuler(E); S.set(now[o + 6], now[o + 7], now[o + 8]); M.compose(P, Q, S); mesh.setMatrixAt(i, M);
      let tone = now[o + 9]; if (opening) { const [, band] = introAt(k, A[o + 1], pose.introStill); tone = Math.max(tone, band); }
      const pal = cur.pal < 0.5 ? PAL.paper : PAL.red; C0.copy(pal[0]); C1.copy(pal[1]); CC.copy(C0).lerp(C1, cl(tone));
      CC.multiplyScalar((1 - lay(i) * 0.02) * grain[i]); mesh.setColorAt(i, CC); }
    mesh.instanceMatrix.needsUpdate = true; mesh.instanceColor.needsUpdate = true;
    // the stage: pose.stage is {x, y, s} in viewport fractions (0..1 from the left, 0..1 from the top) and a scale
    const st = pose.stage || { x: 0.68, y: 0.55, s: 1 };
    const tx = (st.x - 0.5) * visW(), ty = (0.5 - st.y) * visH(), ts = st.s * (phone() ? 0.78 : 1) * (opening && !pose.introStill ? 0.94 + 0.06 * sm(cl((k - 0.5) / 0.5)) : 1);
    cur.x = lerp(cur.x, tx, ease); cur.y = lerp(cur.y, ty, ease); cur.s = lerp(cur.s, ts, ease);
    cur.pal = lerp(cur.pal, pose.pal || 0, quick);
    const tilt = pose.tilt || { x: 0, y: 0 }; cur.tilt.x = lerp(cur.tilt.x, tilt.x, ease); cur.tilt.y = lerp(cur.tilt.y, tilt.y, ease);
    const ry = (pose.ry || 0) + cur.tilt.x * 0.12 + (pose.spin || 0) - (opening && !pose.introStill ? 0.22 * (1 - sm(cl((k - 0.3) / 0.6))) : 0), rx = (pose.rx || 0) - cur.tilt.y * 0.08;
    cur.ry = lerp(cur.ry, ry, ease); cur.rx = lerp(cur.rx, rx, ease);
    moved = Math.max(moved, Math.abs(cur.x - tx), Math.abs(cur.y - ty), Math.abs(cur.ry - ry), Math.abs(cur.rx - rx), Math.abs(cur.pal - (pose.pal || 0)));
    group.position.set(cur.x, cur.y, 0); group.scale.setScalar(cur.s); group.rotation.set(cur.rx, cur.ry, 0);
    key.target.position.set(cur.x, cur.y, 0);
    settledFrames = moved < 0.0005 && !opening ? settledFrames + 1 : 0;
    if (settledFrames > 12 && !pose.force) return;   // nothing changed: skip the draw and let the GPU rest
    renderer.render(scene, camera);
    // adaptive pixel ratio: raise with headroom, step down under sustained strain, never oscillate
    const maxDpr = Math.min(1.5, devicePixelRatio || 1);
    if (t > lock) { if (dt < 0.0125) { fast++; slow = 0; } else if (dt > 0.024) { slow++; fast = 0; } else { fast = Math.max(0, fast - 1); slow = Math.max(0, slow - 1); }
      if (fast > 90 && dpr < maxDpr) { dpr = maxDpr; renderer.setPixelRatio(dpr); resize(); fast = 0; lock = t + 8000; }
      if (slow > 40 && dpr > 1) { dpr = 1; renderer.setPixelRatio(1); resize(); slow = 0; lock = t + 20000; } }
  };
  const dispose = () => { geo.dispose(); mat.dispose(); ground.geometry.dispose(); ground.material.dispose(); renderer.dispose(); };
  return { update, dispose, N, get dpr() { return dpr; }, get lost() { return lost; }, renderer, camera };
}
