/* The home: the gate (loading, Enter with or without sound), the opening flight into the hall, and the walk. Scroll drives
   a camera through poses per section (GSAP ScrollTrigger scrub over Lenis); title cards split into characters and rise;
   rooms reveal their number, word and copy; the method beats take turns; the end wall assembles; the lights go down for
   contact. A cursor ring, a pick label for any screen under the pointer, a WebAudio bed and chapter pings, and the HUD.
   Reduced motion: Enter, no flight, poses without easing. No WebGL: the copy and the still covers. */
import { createWorld } from "./world.js";

(async () => {
  "use strict";
  const root = document.documentElement, $ = id => document.getElementById(id);
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const fine = matchMedia("(hover: hover) and (pointer: fine)").matches;
  const phone = () => innerWidth <= 720, wide = () => innerWidth > 1100;
  const cl = v => Math.max(0, Math.min(1, v)), lerp = (a, b, t) => a + (b - a) * t, sm = t => t * t * (3 - 2 * t);
  const scenes = [...document.querySelectorAll(".scene")];
  if (fine) root.classList.add("fine");

  /* ---- into a case study and back (cross-document View Transitions), registered first ---- */
  const slugOf = url => { try { const path = new URL(url, location.href).pathname; return scenes.map(s => s.dataset.slug).filter(Boolean).find(s => path.endsWith("/" + s + "/")); } catch (_) { return null; } };
  const nameFor = (slug, on) => { const s = scenes.find(s => s.dataset.slug === slug); if (s) s.querySelector("h3 a").style.viewTransitionName = on ? "title" : ""; };
  addEventListener("pageswap", e => { if (!e.viewTransition) return; const to = e.activation && e.activation.entry && e.activation.entry.url, s = to && slugOf(to); if (!s) { e.viewTransition.skipTransition(); return; } nameFor(s, true); try { sessionStorage.setItem("vt", s); } catch (_) {} });
  addEventListener("pagereveal", e => { let s = null; try { s = sessionStorage.getItem("vt"); sessionStorage.removeItem("vt"); } catch (_) {} if (!e.viewTransition) return; if (!s) { e.viewTransition.skipTransition(); return; } nameFor(s, true); e.viewTransition.finished.then(() => nameFor(s, false)); });

  /* ---- HUD: clock, push date, copy button ---- */
  const fmt = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" });
  const tickClock = () => { const t = fmt.format(new Date()) + " Tampa"; for (const id of ["clock", "clock2"]) { const el = $(id); if (el) el.textContent = t; } };
  tickClock(); setInterval(tickClock, 30000);
  const pushed = $("pushed");
  if (pushed) { const m = pushed.textContent.match(/(\d{4}-\d{2}-\d{2})/); if (m) { const d = Math.round((Date.now() - new Date(m[1])) / 864e5); pushed.textContent = d <= 0 ? "pushed today" : `last push ${d}d ago`; } }
  const copyBtn = $("copy-mail");
  if (navigator.clipboard && copyBtn) {
    copyBtn.hidden = false;
    copyBtn.addEventListener("click", async () => { const label = copyBtn.querySelector(".copy-text");
      try { await navigator.clipboard.writeText(copyBtn.dataset.mail); label.textContent = "Copied"; $("copy-status").textContent = "E-mail address copied"; }
      catch (_) { label.textContent = "Copy failed"; $("copy-status").textContent = "Could not copy; the address is the link above"; }
      setTimeout(() => { label.textContent = "Copy e-mail"; }, 2200); });
  }

  /* ---- the cursor ring (fine pointers only; never required) ---- */
  const cursor = $("cursor"), ptr = { x: innerWidth / 2, y: innerHeight / 2, tx: innerWidth / 2, ty: innerHeight / 2, nx: 0, ny: 0 };
  if (fine) {
    addEventListener("pointermove", e => { ptr.tx = e.clientX; ptr.ty = e.clientY; ptr.nx = (e.clientX / innerWidth) * 2 - 1; ptr.ny = -((e.clientY / innerHeight) * 2 - 1); const link = e.target.closest("a, button, input, [role=button]"); cursor.classList.toggle("is-link", !!link); }, { passive: true });
  }

  /* ---- sound: a low bed, a riser for the flight, a ping per chapter; off until asked ---- */
  const sound = { ctx: null, on: false, master: null, drone: null,
    start() { if (this.ctx) return; const C = this.ctx = new (window.AudioContext || window.webkitAudioContext)(); const g = this.master = C.createGain(); g.gain.value = 0; g.connect(C.destination);
      const lp = C.createBiquadFilter(); lp.type = "lowpass"; lp.frequency.value = 170; lp.Q.value = 0.8; lp.connect(g);
      [55, 55.5, 110.3].forEach((f, i) => { const o = C.createOscillator(); o.type = i === 2 ? "sine" : "sawtooth"; o.frequency.value = f; const og = C.createGain(); og.gain.value = i === 2 ? 0.05 : 0.09; o.connect(og).connect(lp); o.start(); });
      const lfo = C.createOscillator(); lfo.frequency.value = 0.07; const lg = C.createGain(); lg.gain.value = 60; lfo.connect(lg).connect(lp.frequency); lfo.start();
      const nb = C.createBuffer(1, C.sampleRate * 2, C.sampleRate), d = nb.getChannelData(0); for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
      const n = C.createBufferSource(); n.buffer = nb; n.loop = true; const bp = C.createBiquadFilter(); bp.type = "bandpass"; bp.frequency.value = 500; bp.Q.value = 0.5; const ng = C.createGain(); ng.gain.value = 0.012; n.connect(bp).connect(ng).connect(g); n.start(); this.noise = { bp, ng }; },
    set(on) { this.on = on; const b = $("sound"); b.setAttribute("aria-pressed", on ? "true" : "false"); b.querySelector(".sound-label").textContent = on ? "Sound on" : "Sound off"; try { sessionStorage.setItem("sound", on ? "1" : "0"); } catch (_) {}
      if (on) { this.start(); if (this.ctx.state === "suspended") this.ctx.resume(); this.master.gain.setTargetAtTime(0.9, this.ctx.currentTime, 0.4); } else if (this.ctx) this.master.gain.setTargetAtTime(0, this.ctx.currentTime, 0.2); },
    ping(k) { if (!this.on || !this.ctx) return; const C = this.ctx, t = C.currentTime, o = C.createOscillator(), g = C.createGain(); o.type = "sine"; o.frequency.setValueAtTime(660 + k * 40, t); o.frequency.exponentialRampToValueAtTime(330, t + 0.5); g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.12, t + 0.02); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.7); o.connect(g).connect(this.master); o.start(t); o.stop(t + 0.8); },
    riser(sec) { if (!this.on || !this.ctx) return; const C = this.ctx, t = C.currentTime; this.noise.bp.frequency.setValueAtTime(200, t); this.noise.bp.frequency.exponentialRampToValueAtTime(2400, t + sec); this.noise.ng.gain.setValueAtTime(0.02, t); this.noise.ng.gain.linearRampToValueAtTime(0.11, t + sec * 0.8); this.noise.ng.gain.linearRampToValueAtTime(0.012, t + sec + 0.6); this.noise.bp.frequency.exponentialRampToValueAtTime(500, t + sec + 0.6); } };
  $("sound").addEventListener("click", () => sound.set(!sound.on));

  /* ---- the world ---- */
  const ATLAS = JSON.parse($("atlas-data").textContent), ITEMS = ATLAS.items;
  const roomEls = scenes.filter(s => s.dataset.cam === "room");
  const flagships = roomEls.map((s, i) => ({ slug: s.dataset.slug, side: s.dataset.side === "right" ? -1 : 1, stage: s.dataset.stage, z: -9 - i * 12, el: s, frac: +s.dataset.frac || 1, evidence: s.dataset.evidence || "", min: s.dataset.min, max: s.dataset.max, unit: s.dataset.unit || "" }));
  const gated = root.classList.contains("gated");
  const gateN = $("gate-n"), ring = $("ring"), gateLabel = $("gate-label");
  const RING = 351.86;
  const setLoad = f => { gateN.textContent = String(Math.round(f * ITEMS.length)).padStart(3, "0"); ring.style.strokeDashoffset = String(RING * (1 - f)); };

  // load the atlases with a real byte count so the gate's counter means something; the world then reads them from cache
  const urls = [0, 1].map(a => `assets/atlas/atlas-${a}${phone() ? "-2k" : ""}.webp`);
  const loadAll = async () => { const got = urls.map(() => 0), tot = urls.map(() => 0);
    await Promise.all(urls.map(async (u, k) => { try { const r = await fetch(u); tot[k] = +r.headers.get("content-length") || 600000; const rd = r.body.getReader(); for (;;) { const { done, value } = await rd.read(); if (done) break; got[k] += value.length; setLoad(cl(got.reduce((a, b) => a + b) / tot.reduce((a, b) => a + b))); } } catch (_) {} }));
    setLoad(1); };
  if (gated) await loadAll();
  let world = null; try { world = createWorld({ canvas: $("world"), ATLAS, ITEMS, flagships, phone, reduced }); } catch (e) { console.error(e); }
  if (world) root.classList.add("gl-on");

  /* ---- scroll: Lenis under GSAP's ticker; ScrollTrigger scrubs a progress proxy ---- */
  let lenis = null;
  const hasGsap = typeof gsap !== "undefined" && typeof ScrollTrigger !== "undefined";
  if (hasGsap) gsap.registerPlugin(ScrollTrigger);
  if (typeof Lenis !== "undefined" && !reduced && hasGsap) { lenis = new Lenis({ lerp: 0.1, autoRaf: false, anchors: true, wheelMultiplier: 0.9 }); root.classList.add("lenis-on"); lenis.on("scroll", ScrollTrigger.update); gsap.ticker.add(t => lenis.raf(t * 1000)); gsap.ticker.lagSmoothing(0); }
  const prog = { v: 0 };
  const main = $("main");
  if (hasGsap) gsap.to(prog, { v: 1, ease: "none", scrollTrigger: { trigger: main, start: "top top", end: "bottom bottom", scrub: reduced ? false : 0.55 } });

  /* ---- poses ---- */
  const V = (x, y, z) => ({ x, y, z });
  /* each room is staged differently, and the camera keeps moving inside it as the visitor scrolls (u is 0..1 through the room) */
  const roomPose = (f, u) => { const ph = phone(), z = f.z, s = f.side, e = sm(cl(u));
    if (f.stage === "floor") return ph ? { eye: V(0, 5.6 - e * 0.6, z + 6.2 - e * 1.5), aim: V(0, 0, z + 1.5), fov: 72 } : { eye: V(-1.6, 6.4 - e * 1.0, z + 4.8 - e * 2.2), aim: V(0.6, 0.2, z - 0.6), fov: 56 };
    if (f.stage === "ahead") return ph ? { eye: V(0, 3.2, z + 10 - e * 4.5), aim: V(0, 1.2, z - 4), fov: 70 } : { eye: V(1.4, 3.5, z + 10 - e * 6), aim: V(-0.6, 3.6, z - 4), fov: 50 };
    if (f.stage === "float") { const a = -0.7 + e * 1.4, r = ph ? 7.6 : 5.4; return { eye: V(Math.sin(a) * r, (ph ? 3.6 : 3.9) + e * 0.5, z + Math.cos(a) * r), aim: V(0, ph ? 1.6 : 3.9, z), fov: ph ? 74 : 52, spin: -a * 0.35 }; }
    return ph ? { eye: V(-s * 0.3, 4.6, z + 5.6 - e * 1.2), aim: V(s * 5.2, 1.8, z - 0.4), fov: 72 } : { eye: V(-s * 1.2, 3.3, z + 4.2 - e * 1.5), aim: V(s * 5.2, 3.5, z - 0.1 - e * 0.6), fov: wide() ? 50 : 58 }; };
  const POSE = () => { const ph = phone(), H = world ? world.HALL : { w: 11 };
    const R = flagships.map(f => roomPose(f, 0)), RE = flagships.map(f => roomPose(f, 1));
    return { RE, H0: ph ? { eye: V(0, 3.3, 8), aim: V(0, 3.6, -40), fov: 64 } : { eye: V(0, 3.3, 7), aim: V(0, 3.4, -40), fov: 50 }, R,
      M: ph ? { eye: V(0, 2.4, -50), aim: V(0, 6.4, -64), fov: 72 } : { eye: V(0, 2.4, -50), aim: V(0, 6.2, -64), fov: 56 },
      A: ph ? { eye: V(0, 3.4, -55), aim: V(0, 3.4, -75), fov: 60 } : { eye: V(0, 3.4, -55), aim: V(0, 3.4, -75), fov: 46 },
      I: ph ? { eye: V(0, 8.8, -24), aim: V(0, 9.4, -70), fov: 66 } : { eye: V(0, 8.5, -34), aim: V(0, 9.2, -70), fov: 50 },
      C: ph ? { eye: V(0, 2.6, -6), aim: V(0.5, 5, -70), fov: 58 } : { eye: V(-2.5, 2.4, -14), aim: V(0.5, 4.5, -70), fov: 42 },
      START: ph ? { eye: V(0, 20, 42), aim: V(0, 2, -40), fov: 80 } : { eye: V(0, 18, 40), aim: V(0, 2, -40), fov: 72 } }; };
  let poses = POSE(); addEventListener("resize", () => { poses = POSE(); });
  const keysFor = (s, i) => { const k = s.dataset.cam, n = +s.dataset.n - 1; const prev = i ? lastPose(scenes[i - 1]) : "H0";
    if (k === "hero") return [[0, "H0"], [1, "H0"]]; if (k === "card") return [[0, prev], [1, "R" + n]]; if (k === "room") return [[0, "R" + n], [1, "R" + n]];
    if (k === "method") return [[0, prev], [0.62, "M"], [1, "A"]]; if (k === "about") return [[0, "A"], [1, "A"]]; if (k === "index") return [[0, "A"], [0.55, "I"], [1, "I"]]; return [[0, "I"], [0.55, "C"], [1, "C"]]; };
  const lastPose = s => { const k = s.dataset.cam, n = +s.dataset.n - 1; return k === "hero" ? "H0" : k === "card" ? "R" + n : k === "room" ? "E" + n : k === "method" ? "A" : k === "about" ? "A" : k === "index" ? "I" : "C"; };
  const P = name => name[0] === "R" ? poses.R[+name.slice(1)] : name[0] === "E" ? poses.RE[+name.slice(1)] : poses[name];
  const blend = (a, b, t) => ({ eye: V(lerp(a.eye.x, b.eye.x, t), lerp(a.eye.y, b.eye.y, t), lerp(a.eye.z, b.eye.z, t)), aim: V(lerp(a.aim.x, b.aim.x, t), lerp(a.aim.y, b.aim.y, t), lerp(a.aim.z, b.aim.z, t)), fov: lerp(a.fov, b.fov, t) });

  /* where in the walk the scroll is: section index and 0..1 within its sticky span */
  const where = () => { const y = scrollY; let i = 0, u = 0;
    for (let k = 0; k < scenes.length; k++) { const s = scenes[k]; if (s.offsetTop <= y + 1) { i = k; u = cl((y - s.offsetTop) / Math.max(1, s.offsetHeight - innerHeight)); } }
    return { i, u }; };
  const poseAt = (i, u) => { if (scenes[i].dataset.cam === "room") return roomPose(flagships[+scenes[i].dataset.n - 1], u); const ks = keysFor(scenes[i], i); let seg = 0; while (seg < ks.length - 2 && u > ks[seg + 1][0]) seg++; const [u0, a] = ks[seg], [u1, b] = ks[seg + 1]; const t = u1 > u0 ? sm(cl((u - u0) / (u1 - u0))) : 1; return a === b ? P(a) : blend(P(a), P(b), t); };

  /* ---- chapters, cards, rooms, beats ---- */
  const chapterN = $("chapter-n"), chapterName = $("chapter-name"), hint = $("hint"), nav = $("nav");
  const chapterOf = s => { const k = s.dataset.cam; if (k === "hero") return ["00", "Entrance"]; if (k === "card" || k === "room") return [s.dataset.n.padStart(2, "0"), k === "card" ? "Next" : s.dataset.title]; return { method: ["05", "Method"], about: ["06", "About"], index: ["07", "Index"], contact: ["08", "Contact"] }[k]; };
  let curChapter = -1;
  const setChapter = i => { if (i === curChapter) return; const [n, name] = chapterOf(scenes[i]); chapterN.textContent = n; chapterName.textContent = name; const tk = document.querySelector("#chapter .tick"); if (tk) { tk.style.transform = "scaleX(0)"; requestAnimationFrame(() => { tk.style.transform = "scaleX(" + (0.25 + 0.75 * (i / (scenes.length - 1))) + ")"; }); } if (curChapter >= 0 && scenes[i].dataset.cam !== "card") sound.ping(i); curChapter = i; };
  // title cards: characters rise as the camera walks, then fall away before the room
  document.querySelectorAll(".card .card-line").forEach(el => { const words = el.textContent.split(" "); el.textContent = ""; words.forEach((w, wi) => { const ws = document.createElement("span"); ws.style.whiteSpace = "nowrap"; [...w].forEach(c => { const cs = document.createElement("span"); cs.className = "ch"; cs.textContent = c; ws.appendChild(cs); }); el.appendChild(ws); if (wi < words.length - 1) el.appendChild(document.createTextNode(" ")); }); });
  if (hasGsap && !reduced) scenes.filter(s => s.dataset.cam === "card").forEach(card => {
    const chars = card.querySelectorAll(".ch"), meta = card.querySelector(".meta");
    const tl = gsap.timeline({ scrollTrigger: { trigger: card, start: "top top", end: "bottom bottom", scrub: 0.4 } });
    tl.fromTo(chars, { y: "0.7em", opacity: 0, rotateX: -40 }, { y: 0, opacity: 1, rotateX: 0, stagger: 0.012, duration: 0.35, ease: "power3.out" }, 0)
      .fromTo(meta, { opacity: 0 }, { opacity: 1, duration: 0.2 }, 0.1)
      .to(chars, { y: "-0.5em", opacity: 0, stagger: 0.008, duration: 0.25, ease: "power2.in" }, 0.72).to(meta, { opacity: 0, duration: 0.15 }, 0.75);
  });
  if (hasGsap) roomEls.forEach(r => ScrollTrigger.create({ trigger: r, start: "top 55%", end: "bottom 45%", onToggle: self => r.classList.toggle("is-in", self.isActive) }));
  const beats = [...document.querySelectorAll(".beat")], methodEl = scenes.find(s => s.dataset.cam === "method");
  const counters = roomEls.map(s => { const v = s.querySelector(".num-v"); return { v, end: +s.dataset.value, dec: (String(s.dataset.value).split(".")[1] || "").length, final: v.textContent, counts: !/\bof\b/.test(s.dataset.unit), t0: 0, done: false }; });

  /* ---- picking: the screen under the pointer gets a label; a click on empty space opens it ---- */
  const pickEl = $("pick"); let picked = -1, pickT = 0;
  if (world && fine) {
    addEventListener("pointermove", e => { const t = performance.now(); if (t - pickT < 60) return; pickT = t; const target = e.target.closest("a, button, input, .scene-in > *"); picked = target ? -1 : world.pick(e.clientX, e.clientY);
      if (picked >= 0) { pickEl.textContent = ITEMS[picked].title; pickEl.style.transform = `translate(${e.clientX + 16}px, ${e.clientY + 16}px)`; pickEl.classList.add("is-on"); } else pickEl.classList.remove("is-on"); }, { passive: true });
    addEventListener("click", e => { if (picked >= 0 && !e.target.closest("a, button, input, .scene-in > *")) location.href = ITEMS[picked].slug + "/"; });
  }

  /* ---- the gate and the opening flight ---- */
  const intro = { k: gated && world && !reduced ? 0 : 1, lightZ: gated && world && !reduced ? 14 : -999, fade: gated && world && !reduced ? 0 : 1, running: false };
  const enter = withSound => { if (withSound) sound.set(true); else { let s = null; try { s = sessionStorage.getItem("sound"); } catch (_) {} if (s === "1") sound.set(true); }
    root.classList.add("entered"); setTimeout(() => root.classList.remove("gated"), 1000);
    if (!world || reduced || !hasGsap) { intro.k = 1; intro.lightZ = -999; intro.fade = 1; root.classList.add("quick"); if (lenis) lenis.start(); return; }
    intro.running = true; if (lenis) lenis.stop(); scrollTo(0, 0); sound.riser(3.2);
    const tl = gsap.timeline({ onComplete: () => { intro.running = false; if (lenis) lenis.start(); } });
    tl.to(intro, { fade: 1, duration: 1.4, ease: "power2.out" }, 0).to(intro, { k: 1, duration: 4.6, ease: "power3.inOut" }, 0).to(intro, { lightZ: -120, duration: 3.8, ease: "power1.in" }, 0.5);
    const skip = () => { if (!intro.running) return; tl.progress(1); };
    for (const ev of ["wheel", "touchstart", "keydown"]) addEventListener(ev, skip, { passive: true, once: true }); };
  if (gated) {
    if (world) await Promise.race([world.atlasReady, new Promise(r => setTimeout(r, 4000))]);
    gateLabel.textContent = world ? `${ITEMS.length} screens ready` : "The hall needs WebGL; the copy is below"; root.classList.add("ready");
    $("enter-sound").addEventListener("click", () => enter(true)); $("enter-quiet").addEventListener("click", () => enter(false));
    if (lenis) lenis.stop();
  } else { root.classList.add("entered", "quick"); setTimeout(() => root.classList.remove("gated"), 10); }
  if (!world) { root.classList.add("entered", "quick"); return; }

  /* ---- the loop ---- */
  let lastY = scrollY, vel = 0, cur = -1;
  const tick = t => {
    requestAnimationFrame(tick);
    const { i, u } = where(); const s = scenes[i], k = s.dataset.cam;
    if (i !== cur) { cur = i; setChapter(i); if (k === "room") { const c = counters[roomEls.indexOf(s)]; if (c && !c.t0) c.t0 = t; } }
    const y = scrollY; vel = lerp(vel, Math.abs(y - lastY), 0.3); if (Math.abs(y - lastY) > 6) { nav.classList.toggle("is-away", y > lastY && y > innerHeight * 0.6); lastY = y; }
    hint.style.opacity = y > 60 ? "0" : "";
    let pose = poseAt(i, u);
    if (intro.k < 1) pose = blend(poses.START, pose, intro.k);
    // pointer parallax on the eye, a little more in rooms
    const px = fine ? ptr.nx * (k === "room" ? 0.5 : 0.9) : 0, py = fine ? ptr.ny * 0.35 : 0;
    const eye = V(pose.eye.x + px, pose.eye.y + py, pose.eye.z), aim = pose.aim;
    const roomOn = k === "room" ? +s.dataset.n - 1 : k === "card" ? +s.dataset.n - 1 : -1;
    const gridMix = k === "index" ? sm(cl((u - 0.08) / 0.5)) : k === "contact" ? 1 : 0;
    const dim = k === "contact" ? sm(cl((u - 0.15) / 0.7)) : 0;
    const sweepZ = k === "method" ? -36 - u * 36 : 999;
    const gauge = counters.map(c => c.t0 ? cl((t - c.t0) / 1500) : 0);
    world.update(t, { eye, aim, fov: pose.fov, gridMix, wallLit: k === "room" ? 0.5 : 1, roomOn, dim, sweepZ, lightZ: intro.lightZ, sel: picked, ab: Math.min(0.012, vel * 0.0003) + (intro.running ? 0.008 : 0), fade: intro.fade, gauge, spin: pose.spin || 0 });
    if (k === "method") beats.forEach((b, bi) => b.classList.toggle("is-on", Math.min(2, Math.floor(u * 3)) === bi));
    if (k === "room") s.querySelectorAll(".fact").forEach(f => f.classList.toggle("is-on", u >= +f.dataset.at));
    for (const c of counters) if (c.t0 && !c.done) { const q = cl((t - c.t0) / 1500), e = 1 - Math.pow(1 - q, 3); if (c.counts) c.v.textContent = q < 1 ? (c.end * e).toFixed(c.dec) : c.final; if (q >= 1) c.done = true; }
    if (fine) { ptr.x = lerp(ptr.x, ptr.tx, 0.35); ptr.y = lerp(ptr.y, ptr.ty, 0.35); cursor.style.transform = `translate(${ptr.x}px, ${ptr.y}px)`; }
  };
  requestAnimationFrame(tick);
})();
