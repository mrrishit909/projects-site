/* The home: Precision Atelier. Scroll decides the chapter; the chapter decides the instrument's arrangement, where it
   stands and the ground colour; instrument.js draws it. The opening (once per session, and on Replay): the parts arrive
   along their axes in a lead/follow order and lock into the assembled register (the click), the register unlocks into
   the exploded hero (the signature), the words settle; a scroll hands the same object to the first chapter. One owner
   per property: GSAP owns the opening's clock, scroll owns the chapters, the instrument lerps every matrix; CSS owns
   only the type. Sound is off by default and synthesised on demand (docs/AUDIO.md). */
import { createInstrument, prepareTextures } from "./instrument.js";

(async () => {
  "use strict";
  const root = document.documentElement, $ = id => document.getElementById(id);
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const fine = matchMedia("(hover: hover) and (pointer: fine)").matches;
  const phone = () => innerWidth <= 760;
  const cl = v => Math.max(0, Math.min(1, v)), lerp = (a, b, t) => a + (b - a) * t, sm = t => t * t * (3 - 2 * t);
  const hasGsap = typeof gsap !== "undefined";

  /* ---- into a case study and back (cross-document View Transitions): the clicked title travels ---- */
  const chapters = [...document.querySelectorAll("[data-chapter]")], flag = chapters.filter(c => c.dataset.slug);
  const slugOf = url => { try { const path = new URL(url, location.href).pathname; return flag.map(p => p.dataset.slug).find(s => path.endsWith("/" + s + "/")); } catch (_) { return null; } };
  const nameFor = (slug, on) => { const p = flag.find(p => p.dataset.slug === slug); if (!p) return; p.querySelector("h2").style.viewTransitionName = on ? "title" : ""; const m = p.querySelector(".marks"); if (m) m.style.viewTransitionName = on ? "marks" : ""; };
  addEventListener("pageswap", e => { const to = e.activation && e.activation.entry && e.activation.entry.url, s = to && slugOf(to); if (s) { try { sessionStorage.setItem("back", s); } catch (_) {} } if (!e.viewTransition) return; if (!s) { e.viewTransition.skipTransition(); return; } nameFor(s, true); try { sessionStorage.setItem("vt", s); } catch (_) {} });
  // returning from a case study: focus lands on the button that was clicked, without scrolling
  addEventListener("pageshow", () => { let s = null; try { s = sessionStorage.getItem("back"); sessionStorage.removeItem("back"); } catch (_) {} const btn = s && document.querySelector(`#feature-${s} .btns a.fill`); if (btn) btn.focus({ preventScroll: true }); });
  addEventListener("pagereveal", e => { let s = null; try { s = sessionStorage.getItem("vt"); sessionStorage.removeItem("vt"); } catch (_) {} if (!e.viewTransition) return; if (!s) { e.viewTransition.skipTransition(); return; } nameFor(s, true); e.viewTransition.finished.then(() => nameFor(s, false)); });

  /* ---- the audio manager: one context, a master gain, four voices, deduplication, envelopes, mute, cleanup ---- */
  const audio = { ctx: null, master: null, on: false, voices: 0, last: {}, MIN: { click: 90, texture: 400, cue: 600, tick: 70 },
    start() { if (this.ctx) return true; try { const C = this.ctx = new (window.AudioContext || window.webkitAudioContext)(); const g = this.master = C.createGain(); g.gain.value = 0; g.connect(C.destination); return true; } catch (_) { this.ctx = null; this.master = null; return false; } },
    /* the control reflects actual capability: the button only reads "Sound on" once the context exists and is running */
    ui(on, note) { const b = $("sound"); b.setAttribute("aria-pressed", on ? "true" : "false"); b.querySelector(".sound-label").textContent = on ? "Sound on" : "Sound off"; const s = $("copy-status"); if (s && note) s.textContent = note; },
    async set(on) { if (!on) { this.on = false; this.ui(false); try { sessionStorage.setItem("sound", "0"); } catch (_) {}
        if (this.ctx) { this.master.gain.cancelScheduledValues(this.ctx.currentTime); this.master.gain.setTargetAtTime(0, this.ctx.currentTime, 0.08); setTimeout(() => { if (!this.on && this.ctx && this.ctx.state === "running") this.ctx.suspend().catch(() => 0); }, 400); } return; }
      if (!this.start()) { this.on = false; this.ui(false, "Sound is not available in this browser"); return; }
      try { if (this.ctx.state !== "running") await this.ctx.resume(); } catch (_) {}
      if (this.ctx.state !== "running") { this.on = false; this.ui(false, "Sound could not start; it stays off"); return; }
      this.on = true; this.ui(true); try { sessionStorage.setItem("sound", "1"); } catch (_) {}
      this.master.gain.cancelScheduledValues(this.ctx.currentTime); this.master.gain.setTargetAtTime(0.5, this.ctx.currentTime, 0.15); },
    play(name) { if (!this.on || !this.ctx || this.ctx.state !== "running" || root.classList.contains("paused")) return; const now = performance.now(); if (now - (this.last[name] || 0) < this.MIN[name]) return; if (this.voices >= 4) return; this.last[name] = now; this.voices++;
      const C = this.ctx, t = C.currentTime, g = C.createGain(); g.connect(this.master); let src, dur = 0.3;
      if (name === "click" || name === "tick") { src = C.createOscillator(); src.type = "sine"; const f = name === "click" ? 1900 : 1300; src.frequency.setValueAtTime(f, t); src.frequency.exponentialRampToValueAtTime(f * 0.45, t + 0.05); g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(name === "click" ? 0.12 : 0.07, t + 0.004); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.08); dur = 0.1; }
      else if (name === "texture") { const n = C.sampleRate * 0.4, buf = C.createBuffer(1, n, C.sampleRate), d = buf.getChannelData(0); for (let i = 0; i < n; i++) d[i] = (Math.random() * 2 - 1) * (1 - i / n); src = C.createBufferSource(); src.buffer = buf; const bp = C.createBiquadFilter(); bp.type = "bandpass"; bp.frequency.value = 900; bp.Q.value = 1.2; src.connect(bp); bp.connect(g); g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.05, t + 0.03); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.38); dur = 0.4; src.start(t); src.stop(t + dur); src.onended = () => { this.voices--; }; return; }
      else { src = C.createOscillator(); src.type = "sine"; src.frequency.setValueAtTime(523, t); const o2 = C.createOscillator(); o2.type = "sine"; o2.frequency.setValueAtTime(784, t); const g2 = C.createGain(); g2.gain.value = 0.5; o2.connect(g2); g2.connect(g); o2.start(t + 0.06); o2.stop(t + 0.5); g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.06, t + 0.02); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.45); dur = 0.5; }
      src.connect(g); src.start(t); src.stop(t + dur); src.onended = () => { this.voices--; }; },
    suspend() { if (this.ctx && this.ctx.state === "running") this.ctx.suspend().catch(() => 0); },
    resume() { if (this.on && !root.classList.contains("paused") && this.ctx && this.ctx.state === "suspended") this.ctx.resume().catch(() => 0); } };
  $("sound").addEventListener("click", () => audio.set(!audio.on));
  try { if (sessionStorage.getItem("sound") === "1") addEventListener("pointerdown", () => audio.set(true), { once: true }); } catch (_) {}
  document.addEventListener("visibilitychange", () => { if (document.hidden) audio.suspend(); else audio.resume(); });

  /* ---- small things: clock, copy e-mail ---- */
  const fmt = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" });
  const tickClock = () => { const el = $("clock"); if (el) el.textContent = fmt.format(new Date()) + ","; }; tickClock(); setInterval(tickClock, 30000);
  const copyBtn = $("copy-mail");
  if (navigator.clipboard && copyBtn) { copyBtn.hidden = false; copyBtn.addEventListener("click", async () => { const label = copyBtn.querySelector(".copy-text");
    try { await navigator.clipboard.writeText(copyBtn.dataset.mail); label.textContent = "Copied"; $("copy-status").textContent = "E-mail address copied"; }
    catch (_) { label.textContent = "Copy failed"; $("copy-status").textContent = "Could not copy; the address is the link above"; }
    setTimeout(() => { label.textContent = "Copy e-mail"; }, 2200); }); }

  /* ---- the evidence fragments: each project's own interface, drawn at device resolution while on screen ---- */
  const frags = [...document.querySelectorAll(".evidence canvas")].map(cv => { const def = (window.SCENES || {})[cv.dataset.slug]; return { cv, def, g: cv.getContext("2d"), S: null, t0: 0, on: false, u: 0, w: 0 }; });
  const sizeFrag = f => { const w = Math.round(f.cv.clientWidth * Math.min(2, devicePixelRatio || 1)); if (!w || w === f.w) return; f.w = w; f.cv.width = w; f.cv.height = Math.round(w / (f.def ? f.def.aspect : 1.614)); };
  const drawFrag = (f, t) => { if (!f.def || !f.S) return; sizeFrag(f); if (f.on && !f.t0) f.t0 = t; const u = f.t0 ? Math.min(0.92, (t - f.t0) / 1000 / (f.def.seconds || 6)) : 0.92; if (u === f.u && u >= 0.92) return; f.u = u;
    const g = f.g, W = f.cv.width, H = f.cv.height, grad = g.createRadialGradient(W / 2, H / 2, 0, W / 2, H / 2, Math.max(W, H) * 0.75); grad.addColorStop(0, f.def.bg[0]); grad.addColorStop(1, f.def.bg[1]);
    g.setTransform(1, 0, 0, 1, 0, 0); g.globalAlpha = 1; g.fillStyle = grad; g.fillRect(0, 0, W, H); f.def.draw(g, reduced ? 0.92 : u, W, H, f.S, window.T); };
  Promise.all([document.fonts.load("500 20px Geist"), document.fonts.load("400 20px Geist"), document.fonts.load('400 20px "Geist Mono"')]).catch(() => 0).then(() => frags.forEach(f => { if (f.def) { sizeFrag(f); f.S = f.def.init ? f.def.init(f.cv.width, f.cv.height, window.T) : {}; } }));
  const fragIO = new IntersectionObserver(es => es.forEach(e => { const f = frags.find(f => f.cv === e.target); if (!f) return; f.on = e.isIntersecting; if (!f.on) { f.t0 = 0; f.u = 0; } }), { threshold: 0.2 });
  frags.forEach(f => fragIO.observe(f.cv));

  /* ---- the chapters ---- */
  const handoff = document.querySelector(".handoff"), names = { hero: "", orient: "Selected work", system: "The instrument", about: "About", archive: "Archive", contact: "Contact" };
  let curField = root.dataset.field, curChapter = "";
  const tops = new Map(), measure = () => { for (const el of [...chapters, handoff]) tops.set(el, el.getBoundingClientRect().top + scrollY); };
  measure(); addEventListener("resize", measure); addEventListener("load", measure); setInterval(measure, 2000);
  const where = () => { const y = scrollY + innerHeight * 0.5; let ch = chapters[0]; for (const c of chapters) if (tops.get(c) <= y) ch = c; return ch; };
  const inIO = new IntersectionObserver(es => es.forEach(e => e.target.classList.toggle("is-in", e.isIntersecting)), { rootMargin: "-20% 0px -20% 0px" });
  chapters.forEach(c => inIO.observe(c));

  /* ---- the Florida hour: the published hourly on-time rates from the case study's own data ---- */
  const HOURS = JSON.parse($("hours-data").textContent), hourIn = $("hour"), hourOut = $("hour-out"), hourV = $("hour-v"), hourN = $("hour-n");
  const h12 = h => `${(h + 11) % 12 + 1} ${h < 12 ? "a.m." : "p.m."}`;
  const hourOf = () => HOURS.find(x => x.h === +hourIn.value) || HOURS[0];
  const showHour = () => { if (!hourIn) return; const d = hourOf(); hourOut.textContent = h12(d.h); hourV.textContent = (d.otp * 100).toFixed(1); hourN.textContent = `${d.n.toLocaleString("en-US")} flights`; };
  // the hour's lateness, 0..1 across the published range (about 89% on time at 5 a.m. to 60% late evening): lights the Time panel
  const lateOf = () => cl((0.89 - hourOf().otp) / 0.3);
  if (hourIn) { hourIn.addEventListener("input", () => { showHour(); audio.play("tick"); }); showHour(); }

  /* ---- the instrument ---- */
  const seriesEl = flag.find(p => p.dataset.series), bend = (() => { try { return seriesEl ? JSON.parse(seriesEl.dataset.series) : {}; } catch (_) { return {}; } })();
  // phones get the lite quality (no shadow map, smaller marble textures, pixel ratio capped at 1.5); the decision is made once at load
  let inst = null; try { const textures = await prepareTextures({ texSize: phone() ? 320 : 512 }); inst = createInstrument({ canvas: $("instrument"), phone, reduced, series: bend.series, fan: bend.fan, quality: phone() ? "lite" : "full", texSize: phone() ? 320 : 512, textures, startOut: root.classList.contains("opening"), onReady: () => root.classList.add("gl-on") }); } catch (e) { console.error(e); }
  const intro = { k: 1, d: 1, cam: 1, u: 1, running: false, still: false, tl: null, abort: null, clicked: false };
  const enter = () => { root.classList.add("entered"); root.classList.remove("opening"); root.classList.remove("words"); try { sessionStorage.setItem("seen", "1"); } catch (_) {} };
  /* the opening timeline: 0 to 2.0 s the parts arrive and lock (the click at 1.9 s), 2.0 to 2.9 s the register unlocks
     into the exploded hero (the signature, with a texture), the words from 0.5 s, buttons at 2.4 s; 3.1 s total.
     Skip jumps every value to the end; Replay kills the previous timeline and its listeners before starting again. */
  const playOpening = () => {
    if (!inst || !hasGsap) { enter(); return; }
    if (intro.tl) intro.tl.kill(); if (intro.abort) intro.abort.abort();
    intro.abort = new AbortController(); const sig = intro.abort.signal;
    scrollTo({ top: 0, behavior: "instant" });
    root.classList.add("cut"); if (root.dataset.field !== "green") { curField = "green"; root.dataset.field = "green"; } setTimeout(() => root.classList.remove("cut"), 80);
    root.classList.add("opening"); root.classList.remove("entered", "words");
    try { sessionStorage.setItem("seen", "1"); } catch (_) {}   // leaving mid-sequence counts as seen: Back never replays it
    intro.u = 0; intro.running = true; intro.still = reduced; intro.clicked = false;
    intro.k = intro.d = intro.cam = reduced ? 1 : 0;
    const tl = intro.tl = gsap.timeline({ onComplete: () => { intro.running = false; intro.k = intro.d = intro.cam = 1; intro.u = 1; enter(); } });
    const click = () => { if (!intro.clicked) { intro.clicked = true; audio.play("click"); } };
    if (reduced) { tl.call(() => root.classList.add("words"), null, 0); tl.to(intro, { u: 1, duration: 0.6, ease: "power2.inOut" }, 0.2); }
    else {
      /* shot 1 and 2: the dial turns to its index (a small overshoot), the core stack seats as it aligns: the click */
      tl.to(intro, { d: 1, duration: 0.8, ease: "back.out(1.4)" }, 0.5);
      tl.to(intro, { k: 1, duration: 0.45, ease: "power4.in" }, 0.85);
      tl.call(click, null, 1.3);
      /* shot 3: the seating unlocks the register by assembly while the camera pulls back; the words resolve */
      tl.to(intro, { cam: 1, duration: 1.1, ease: "power2.inOut" }, 1.3);
      tl.to(intro, { u: 1, duration: 1.2, ease: "power2.inOut", onStart: () => audio.play("texture") }, 1.35);
      tl.call(() => root.classList.add("words"), null, 1.5);
      tl.to({}, { duration: 0.4 }, 2.6);   // shot 4: settle
    }
    const skip = () => { if (!intro.running) return; tl.progress(1); };
    for (const ev of ["wheel", "touchstart", "keydown"]) addEventListener(ev, skip, { passive: true, once: true, signal: sig });
    $("skip").addEventListener("click", skip, { signal: sig }); };
  if (root.classList.contains("opening") && inst && hasGsap) playOpening(); else enter();
  for (const id of ["replay", "replay-hero"]) $(id).addEventListener("click", () => { if (document.hidden) return; playOpening(); $(id).blur(); });

  /* ---- pause: every animation owner stops (the renderer, GSAP, the fragments, the audio) ---- */
  const pauseBtn = $("pause");
  const setPaused = on => { root.classList.toggle("paused", on); pauseBtn.setAttribute("aria-pressed", on ? "true" : "false"); pauseBtn.querySelector(".text").textContent = on ? "Resume" : "Pause"; pauseBtn.setAttribute("aria-label", on ? "Resume motion" : "Pause motion");
    if (inst) inst.paused = on; if (hasGsap) (on ? gsap.globalTimeline.pause() : gsap.globalTimeline.resume()); if (on) audio.suspend(); else audio.resume(); };
  pauseBtn.addEventListener("click", () => setPaused(!root.classList.contains("paused")));
  document.addEventListener("visibilitychange", () => { if (!document.hidden && inst) inst.paused = root.classList.contains("paused"); });

  /* ---- the system chapter's controls, pointer drag (fine pointers) and the keyboard ---- */
  const sys = { state: "open", sep: 1, spin: 0 };
  const cfgBtns = [...document.querySelectorAll("[data-config]")];
  cfgBtns.forEach(b => b.addEventListener("click", () => { sys.state = b.dataset.config; cfgBtns.forEach(x => x.setAttribute("aria-pressed", x === b ? "true" : "false")); audio.play("cue"); }));
  const sep = $("separate"); sep.addEventListener("input", () => { sys.sep = +sep.value; if (sys.state !== "open" && sys.state !== "closed") { sys.state = "open"; cfgBtns.forEach(x => x.setAttribute("aria-pressed", x.dataset.config === "open" ? "true" : "false")); } });
  const turn = d => { sys.spin += d; }; $("turn-left").addEventListener("click", () => turn(-0.35)); $("turn-right").addEventListener("click", () => turn(0.35)); $("turn-reset").addEventListener("click", () => { sys.spin = 0; ptr.spin = 0; });
  document.querySelector(".system").addEventListener("keydown", e => { if (e.key === "ArrowLeft") { turn(-0.2); e.preventDefault(); } else if (e.key === "ArrowRight") { turn(0.2); e.preventDefault(); } else if (e.key === "Home") { sys.spin = 0; ptr.spin = 0; e.preventDefault(); } });
  const ptr = { nx: 0, ny: 0, down: false, lx: 0, spin: 0, vel: 0 };
  if (fine) {
    addEventListener("pointermove", e => { ptr.nx = (e.clientX / innerWidth) * 2 - 1; ptr.ny = -((e.clientY / innerHeight) * 2 - 1); if (ptr.down) { ptr.vel = (e.clientX - ptr.lx) * 0.006; ptr.spin += ptr.vel; ptr.lx = e.clientX; } }, { passive: true });
    addEventListener("pointerdown", e => { if (e.button !== 0 || e.target.closest("a, button, input, label, table, form, .text, .evidence, .lineup, .reading")) return; ptr.down = true; ptr.lx = e.clientX; ptr.vel = 0; root.classList.add("dragging"); }, { passive: true });
    addEventListener("pointerup", () => { ptr.down = false; root.classList.remove("dragging"); }, { passive: true });
  }

  /* ---- the loop: scroll to chapter, chapter to pose ---- */
  // short phones (and a phone-wide window at 200% zoom): the chapters are not pinned, so a fixed object would cross the
  // words as they scroll; the register shows in the hero and leaves for the rest of the page (a deliberate alternate composition)
  const short = () => phone() && innerHeight <= 820;
  const mix = (a, b, t) => ({ x: lerp(a.x, b.x, t), y: lerp(a.y, b.y, t), s: lerp(a.s, b.s, t) });
  const stageFor = ch => { const ph = phone(), st = ch.dataset.state, c = intro.cam;
    if (ch.dataset.chapter === "hero") return ph ? mix({ x: 0.5, y: 0.3, s: 1.4 }, { x: 0.5, y: short() ? 0.2 : 0.26, s: short() ? 0.4 : 0.55 }, c) : mix({ x: 0.74, y: 0.38, s: 2.3 }, { x: 0.71, y: 0.52, s: 1 }, c);
    if (short()) return { x: 0.5, y: 1.3, s: 0.001 };
    if (ch.dataset.chapter === "orient") return ph ? { x: 0.5, y: 0.13, s: 0.55 } : { x: 0.78, y: 0.8, s: 1.9 };
    if (ch.classList.contains("wide")) return ph ? { x: 0.5, y: 0.33, s: 0.42 } : { x: 0.63, y: 0.56, s: 0.92 };
    if (ch.dataset.chapter === "system") return ph ? { x: 0.5, y: 0.22, s: 0.42 } : { x: 0.68, y: 0.5, s: 0.9 };
    // on a phone the reading ground has no room beside the words: the register leaves at the handoff (a deliberate exit)
    if (ch.dataset.chapter === "about") return ph ? { x: 0.5, y: 1.3, s: 0.001 } : { x: 0.82, y: 0.36, s: 0.55 };
    if (ch.dataset.chapter === "archive") return ph ? { x: 0.5, y: 1.3, s: 0.001 } : { x: 0.86, y: 0.55, s: 0.4 };
    if (ch.dataset.chapter === "contact") return ph ? { x: 0.5, y: 1.3, s: 0.001 } : { x: 0.72, y: 0.5, s: 0.85 };
    const long = st === "pipeline" || st === "timeline"; return ph ? { x: 0.5, y: 0.22, s: long ? 0.36 : 0.5 } : { x: long ? 0.66 : 0.69, y: 0.46, s: long ? 0.72 : st === "network" ? 0.8 : 0.88 }; };
  const RY = { open: -0.5, closed: -0.5, network: -0.22, pipeline: -0.34, timeline: -0.28, documents: -0.5 };
  const testsEl = $("tests-n"); let lastTests = -1, lastChapterCue = -1;
  const tick = t => {
    requestAnimationFrame(tick);
    if (root.classList.contains("paused")) return;
    const ch = where(), name = ch.dataset.chapter, k = chapters.indexOf(ch);
    if (name !== curChapter) { curChapter = name; if (k !== lastChapterCue && k > 0 && !intro.running) audio.play("cue"); lastChapterCue = k; }
    const field = scrollY + innerHeight * 0.92 >= tops.get(handoff) ? "ivory" : "green"; if (field !== curField) { curField = field; root.dataset.field = field; }
    const prev = chapters[Math.max(0, k - 1)], prevState = prev.dataset.state, st = ch.dataset.state;
    const u = cl((scrollY - tops.get(ch)) / Math.max(1, ch.offsetHeight - innerHeight));
    let pose = { state: st, stage: stageFor(ch), introK: intro.k, introD: intro.d, introStill: intro.still, tilt: { x: ptr.nx, y: ptr.ny }, spin: ptr.spin, ry: RY[st] == null ? -0.5 : RY[st], rx: 0.16, force: intro.running, ground: -3.3 };
    if (name === "hero") { const c = sm(intro.cam); pose.state = "closed"; pose.next = "open"; pose.u = intro.u; pose.lead = true; pose.ry = lerp(-0.95, -0.5, c); pose.rx = lerp(0.05, 0.16, c); }
    else if (name === "orient") { pose.state = "closed"; pose.ry = -0.3; pose.rx = 0.1; }
    else if (ch.dataset.slug) { pose.state = prevState === "open" || prevState === "closed" ? (k === 1 ? "closed" : "open") : prevState; pose.next = st; pose.u = cl((u - 0.04) / 0.5); pose.arg = prev.dataset.slug ? +prev.dataset.argEnd || undefined : undefined; pose.arg2 = prev.dataset.slug ? +prev.dataset.argEnd2 || undefined : undefined;
      if (st === "network") { pose.nextArg = hourOf().h; pose.nextArg2 = lateOf(); }
      else if (st === "pipeline") { pose.nextArg = Math.round(31 * cl((u - 0.3) / 0.5)); if (testsEl && pose.nextArg !== lastTests) { testsEl.textContent = String(pose.nextArg); if (pose.nextArg > lastTests && lastTests >= 0) audio.play("tick"); lastTests = pose.nextArg; } }
      else if (st === "documents") { pose.nextArg = cl((u - 0.08) / 0.4) + cl((u - 0.7) / 0.28); ch.classList.toggle("refusing", pose.nextArg > 1.5); }
      ch.dataset.argEnd = pose.nextArg == null ? "" : String(pose.nextArg); ch.dataset.argEnd2 = pose.nextArg2 == null ? "" : String(pose.nextArg2); }
    else if (name === "system") { if (sys.state === "open" || sys.state === "closed") { pose.state = "closed"; pose.next = "open"; pose.u = sys.sep; } else pose.state = sys.state; pose.arg = sys.state === "pipeline" ? 31 : sys.state === "documents" ? 1 : undefined; pose.spin = ptr.spin + sys.spin; pose.ry = RY[sys.state]; }
    else if (name === "contact") { pose.state = "closed"; pose.ry = -0.5 + Math.sin(t / 9000) * 0.25; pose.force = true; }
    else if (name === "about" || name === "archive") { pose.state = "closed"; pose.ry = -0.65; }
    if (inst) inst.update(t, pose);
    ptr.spin *= 0.985;
    for (const f of frags) if (f.on) drawFrag(f, t);
  };
  requestAnimationFrame(tick);
})();
