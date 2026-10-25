/* The home: THE BLOCK. Scroll decides the chapter; the chapter decides the field colour, where the block sits and which
   operation it performs; block.js draws it. The opening (once per session, and on Replay): the slips loosen, a plane of
   light passes down through them and collects each row (the check), the block settles, the two counts roll. Four live
   interface fragments are drawn by the projects' own scenes at device resolution. One bounded input (the departure hour)
   cuts the block at the published on-time rate. Sound is optional. */
import { createBlock } from "./block.js";

(() => {
  "use strict";
  const root = document.documentElement, $ = id => document.getElementById(id);
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const fine = matchMedia("(hover: hover) and (pointer: fine)").matches;
  const phone = () => innerWidth <= 720;
  const cl = v => Math.max(0, Math.min(1, v)), lerp = (a, b, t) => a + (b - a) * t, sm = t => t * t * (3 - 2 * t);
  const hasGsap = typeof gsap !== "undefined";

  /* ---- into a case study and back (cross-document View Transitions) ---- */
  const panels = [...document.querySelectorAll(".panel")];
  const slugOf = url => { try { const path = new URL(url, location.href).pathname; return panels.map(p => p.dataset.slug).find(s => path.endsWith("/" + s + "/")); } catch (_) { return null; } };
  // the clicked title and the live fragment travel into the case study's heading and cover, and back
  const nameFor = (slug, on) => { const p = panels.find(p => p.dataset.slug === slug); if (!p) return; p.querySelector("h3 a").style.viewTransitionName = on ? "title" : ""; const cv = p.querySelector(".frag canvas"); if (cv) cv.style.viewTransitionName = on ? "cover" : ""; };
  addEventListener("pageswap", e => { if (!e.viewTransition) return; const to = e.activation && e.activation.entry && e.activation.entry.url, s = to && slugOf(to); if (!s) { e.viewTransition.skipTransition(); return; } nameFor(s, true); try { sessionStorage.setItem("vt", s); } catch (_) {} });
  addEventListener("pagereveal", e => { let s = null; try { s = sessionStorage.getItem("vt"); sessionStorage.removeItem("vt"); } catch (_) {} if (!e.viewTransition) return; if (!s) { e.viewTransition.skipTransition(); return; } nameFor(s, true); e.viewTransition.finished.then(() => nameFor(s, false)); });

  /* ---- small things: clock, copy e-mail, sound ---- */
  const fmt = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" });
  const tickClock = () => { const el = $("clock"); if (el) el.textContent = fmt.format(new Date()) + ","; }; tickClock(); setInterval(tickClock, 30000);
  const copyBtn = $("copy-mail");
  if (navigator.clipboard && copyBtn) { copyBtn.hidden = false; copyBtn.addEventListener("click", async () => { const label = copyBtn.querySelector(".copy-text");
    try { await navigator.clipboard.writeText(copyBtn.dataset.mail); label.textContent = "Copied"; $("copy-status").textContent = "E-mail address copied"; }
    catch (_) { label.textContent = "Copy failed"; $("copy-status").textContent = "Could not copy; the address is the link above"; }
    setTimeout(() => { label.textContent = "Copy e-mail"; }, 2200); }); }
  const sound = { ctx: null, on: false, master: null,
    start() { if (this.ctx) return; const C = this.ctx = new (window.AudioContext || window.webkitAudioContext)(); const g = this.master = C.createGain(); g.gain.value = 0; g.connect(C.destination);
      const lp = C.createBiquadFilter(); lp.type = "lowpass"; lp.frequency.value = 180; lp.connect(g);
      [55, 55.4, 110.2].forEach((f, i) => { const o = C.createOscillator(); o.type = i === 2 ? "sine" : "sawtooth"; o.frequency.value = f; const og = C.createGain(); og.gain.value = i === 2 ? 0.05 : 0.08; o.connect(og).connect(lp); o.start(); }); },
    set(on) { this.on = on; const b = $("sound"); b.setAttribute("aria-pressed", on ? "true" : "false"); b.querySelector(".sound-label").textContent = on ? "Sound on" : "Sound off"; try { sessionStorage.setItem("sound", on ? "1" : "0"); } catch (_) {}
      if (on) { this.start(); if (this.ctx.state === "suspended") this.ctx.resume(); this.master.gain.setTargetAtTime(0.8, this.ctx.currentTime, 0.4); } else if (this.ctx) this.master.gain.setTargetAtTime(0, this.ctx.currentTime, 0.2); },
    ping(k) { if (!this.on || !this.ctx) return; const C = this.ctx, t = C.currentTime, o = C.createOscillator(), g = C.createGain(); o.type = "sine"; o.frequency.setValueAtTime(600 + k * 60, t); o.frequency.exponentialRampToValueAtTime(300, t + 0.5); g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.1, t + 0.02); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.7); o.connect(g).connect(this.master); o.start(t); o.stop(t + 0.8); } };
  $("sound").addEventListener("click", () => sound.set(!sound.on));
  try { if (sessionStorage.getItem("sound") === "1") addEventListener("pointerdown", () => sound.set(true), { once: true }); } catch (_) {}

  /* ---- the live interface fragments: each project's own scene, drawn at device resolution while on screen ---- */
  const frags = [...document.querySelectorAll(".frag canvas")].map(cv => { const def = (window.SCENES || {})[cv.dataset.slug]; return { cv, def, g: cv.getContext("2d"), S: null, t0: 0, on: false, u: 0, w: 0 }; });
  const sizeFrag = f => { const w = Math.round(f.cv.clientWidth * Math.min(2, devicePixelRatio || 1)); if (!w || w === f.w) return; f.w = w; f.cv.width = w; f.cv.height = Math.round(w / (f.def ? f.def.aspect : 1.614)); };
  const drawFrag = (f, t) => { if (!f.def || !f.S) return; sizeFrag(f); if (f.on && !f.t0) f.t0 = t; const u = f.t0 ? Math.min(0.92, (t - f.t0) / 1000 / (f.def.seconds || 6)) : 0.92; if (u === f.u && u >= 0.92) return; f.u = u;
    const g = f.g, W = f.cv.width, H = f.cv.height, grad = g.createRadialGradient(W / 2, H / 2, 0, W / 2, H / 2, Math.max(W, H) * 0.75); grad.addColorStop(0, f.def.bg[0]); grad.addColorStop(1, f.def.bg[1]);
    g.setTransform(1, 0, 0, 1, 0, 0); g.globalAlpha = 1; g.fillStyle = grad; g.fillRect(0, 0, W, H); f.def.draw(g, reduced ? 0.92 : u, W, H, f.S, window.T); };
  Promise.all([document.fonts.load("500 20px Geist"), document.fonts.load("400 20px Geist"), document.fonts.load('400 20px "Geist Mono"')] /* taste-skill-ignore: the fragments' own code labels */).catch(() => 0).then(() => frags.forEach(f => { if (f.def) { sizeFrag(f); f.S = f.def.init ? f.def.init(f.cv.width, f.cv.height, window.T) : {}; } }));
  const fragIO = new IntersectionObserver(es => es.forEach(e => { const f = frags.find(f => f.cv === e.target); if (!f) return; f.on = e.isIntersecting; if (!f.on) { f.t0 = 0; f.u = 0; } }), { threshold: 0.2 });
  frags.forEach(f => fragIO.observe(f.cv));

  /* ---- the chapters ---- */
  const chapters = [...document.querySelectorAll("[data-chapter]")];
  const chapterEl = $("chapter"), names = { hero: "", work: "Selected work", check: "The check", experience: "Experience", archive: "Archive", contact: "Contact" };
  let curPal = root.dataset.pal, curChapter = "";
  const panelState = p => p.dataset.state;
  // document positions, cached (offsetTop is relative to the nearest positioned ancestor, so it is not used)
  const tops = new Map(), measure = () => { for (const el of [...chapters, ...panels]) tops.set(el, el.getBoundingClientRect().top + scrollY); };
  measure(); addEventListener("resize", measure); addEventListener("load", measure); setInterval(measure, 2000);
  const where = () => { const y = scrollY + innerHeight * 0.5; let ch = chapters[0]; for (const c of chapters) if (tops.get(c) <= y) ch = c; return ch; };
  const panelIO = new IntersectionObserver(es => es.forEach(e => e.target.classList.toggle("is-in", e.isIntersecting)), { rootMargin: "-20% 0px -20% 0px" });
  panels.forEach(p => panelIO.observe(p));

  /* ---- the check: a departure hour cuts the block at the published on-time rate ---- */
  const HOURS = JSON.parse($("hours-data").textContent), hourIn = $("hour"), hourOut = $("hour-out"), checkV = $("check-v"), checkN = $("check-n");
  const h12 = h => `${(h + 11) % 12 + 1} ${h < 12 ? "a.m." : "p.m."}`;
  const hourOf = () => HOURS.find(x => x.h === +hourIn.value) || HOURS[0];
  const showHour = () => { const d = hourOf(); hourOut.textContent = h12(d.h); checkV.textContent = (d.otp * 100).toFixed(1); checkN.textContent = `${d.n.toLocaleString("en-US")} flights left between ${h12(d.h)} and ${h12(d.h + 1)}`; };
  hourIn.addEventListener("input", showHour); showHour();

  /* ---- the block ---- */
  const bendData = (() => { const p = panels.find(p => p.dataset.series); try { return p ? JSON.parse(p.dataset.series) : {}; } catch (_) { return {}; } })();
  let block = null; try { block = createBlock({ canvas: $("block"), phone, reduced, series: bendData.series, fan: bendData.fan }); } catch (e) { console.error(e); }
  if (block) root.classList.add("gl-on");
  const counts = [...document.querySelectorAll(".count")];
  const intro = { k: 1, running: false, still: false, tl: null, abort: null };
  const landCounts = () => counts.forEach(c => { c.textContent = c.dataset.count; });
  const enter = () => { root.classList.add("entered"); root.classList.remove("opening"); try { sessionStorage.setItem("seen", "1"); } catch (_) {} };
  /* the opening: 0 to 0.8 s the slips loosen (anticipation), 0.8 to 2.2 s the light passes down and collects them (the
     check) while the counts roll, 2.2 to 2.6 s the block settles. Replay reuses this and tears the previous run down. */
  const playOpening = () => {
    if (!block || !hasGsap) { enter(); landCounts(); return; }
    if (intro.tl) intro.tl.kill(); if (intro.abort) intro.abort.abort();
    intro.abort = new AbortController(); const sig = intro.abort.signal;
    scrollTo({ top: 0, behavior: "instant" });
    // the field cuts to red at once on Replay instead of travelling through pink
    root.classList.add("cut"); if (root.dataset.pal !== "red") { curPal = "red"; root.dataset.pal = "red"; } setTimeout(() => root.classList.remove("cut"), 80);
    root.classList.add("opening"); root.classList.remove("entered");
    intro.k = 0; intro.running = true; intro.still = reduced;
    if (!reduced) counts.forEach(c => { c.textContent = "0"; });
    const tl = intro.tl = gsap.timeline({ onComplete: () => { intro.running = false; intro.k = 1; landCounts(); enter(); } });
    tl.to(intro, { k: 1, duration: reduced ? 1.4 : 2.6, ease: "none" }, 0);
    if (!reduced) counts.forEach(c => { const o = { v: 0 }; tl.to(o, { v: +c.dataset.count, duration: 1.1, ease: "power2.out", onUpdate: () => { c.textContent = String(Math.round(o.v)); } }, 1.0); });
    const skip = () => { if (!intro.running) return; tl.progress(1); };
    for (const ev of ["wheel", "touchstart", "keydown"]) addEventListener(ev, skip, { passive: true, once: true, signal: sig });
    $("skip").addEventListener("click", skip, { signal: sig });
    sound.ping(0); };
  if (root.classList.contains("opening") && block && hasGsap) playOpening(); else { enter(); landCounts(); }
  $("replay").addEventListener("click", () => { playOpening(); $("replay").blur(); });

  /* pointer tilt and drag (fine pointers): the one optional exploration; never required */
  const ptr = { nx: 0, ny: 0, down: false, lx: 0, spin: 0, vel: 0 };
  if (fine) {
    addEventListener("pointermove", e => { ptr.nx = (e.clientX / innerWidth) * 2 - 1; ptr.ny = -((e.clientY / innerHeight) * 2 - 1); if (ptr.down) { ptr.vel = (e.clientX - ptr.lx) * 0.006; ptr.spin += ptr.vel; ptr.lx = e.clientX; } }, { passive: true });
    addEventListener("pointerdown", e => { if (e.button !== 0 || e.target.closest("a, button, input, label, table, form, .card, .frag")) return; ptr.down = true; ptr.lx = e.clientX; ptr.vel = 0; root.classList.add("dragging"); }, { passive: true });
    addEventListener("pointerup", () => { ptr.down = false; root.classList.remove("dragging"); }, { passive: true });
  }

  /* ---- the loop: scroll to chapter, chapter to pose ---- */
  const stageFor = ch => { const ph = phone();
    if (ch === "hero") return ph ? { x: 0.5, y: 0.47, s: 0.95 } : { x: 0.7, y: 0.56, s: 1 };
    if (ch === "work") return ph ? { x: 0.5, y: 0.22, s: 0.6 } : innerWidth < 1100 ? { x: 0.72, y: 0.3, s: 0.6 } : { x: 0.7, y: 0.33, s: 0.9 };
    if (ch === "check") return ph ? { x: 0.5, y: 0.2, s: 0.68 } : innerWidth < 1000 ? { x: 0.78, y: 0.5, s: 0.62 } : { x: 0.7, y: 0.5, s: 1 };
    if (ch === "experience") return ph ? { x: 0.8, y: 0.86, s: 0.32 } : { x: 0.84, y: 0.28, s: 0.4 };
    if (ch === "archive") return ph ? { x: 0.82, y: 0.9, s: 0.3 } : { x: 0.8, y: 0.5, s: 0.62 };
    return ph ? { x: 0.78, y: 0.4, s: 0.4 } : { x: 0.82, y: 0.42, s: 0.5 }; };
  let lastChapterPing = -1;
  const tick = t => {
    requestAnimationFrame(tick);
    const ch = where(), name = ch.dataset.chapter;
    if (name !== curChapter) { curChapter = name; chapterEl.textContent = names[name] || ""; const k = chapters.indexOf(ch); if (k !== lastChapterPing && k > 0) sound.ping(k); lastChapterPing = k; }
    if (ch.dataset.pal !== curPal) { curPal = ch.dataset.pal; root.dataset.pal = curPal; }
    root.classList.toggle("past-hero", scrollY > innerHeight * 0.55);
    // the pose
    let pose = { state: "block", u: 0, stage: stageFor(name), pal: curPal === "paper" ? 1 : 0, introK: intro.k, introStill: intro.still, tilt: { x: ptr.nx, y: ptr.ny }, spin: ptr.spin, ry: -0.42, rx: 0.16, force: intro.running };
    if (name === "work") { let p = panels[0], u = 0; for (const q of panels) { const t0 = tops.get(q); if (t0 <= scrollY + 1) { p = q; u = cl((scrollY - t0) / Math.max(1, q.offsetHeight - innerHeight)); } }
      const st = panelState(p); pose.state = "block"; pose.next = st; pose.u = cl((u - 0.12) / 0.55); if (st === "layer") pose.nextArg = Math.round(31 * cl((u - 0.3) / 0.6)); }
    else if (name === "check") { pose.state = "hour"; pose.arg = +hourOf().otp.toFixed(3); pose.ry = -0.3; pose.rx = 0.12; }
    else if (name === "archive") { const u = cl((scrollY - tops.get(ch) + innerHeight * 0.5) / Math.max(1, ch.offsetHeight)); pose.state = "block"; if (!phone()) { pose.next = "sheet"; pose.nextArg = 224; pose.u = sm(cl(u * 1.6)); pose.ry = -0.08; pose.rx = 0.02; } }
    else if (name === "experience" || name === "contact") { pose.ry = -0.6; pose.rx = 0.22; }
    if (block) block.update(t, pose);
    ptr.spin *= 0.985;
    for (const f of frags) if (f.on) drawFrag(f, t);
  };
  requestAnimationFrame(tick);
})();
