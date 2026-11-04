// ATELIER X shared behaviour for every page under x/: reveal, cursor, sound, page veil, starfield backdrop.
// No dependencies. Everything degrades: without JS pages are complete; reduced motion skips motion.
const doc = document.documentElement;
doc.classList.add("js");
const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
const fine = matchMedia("(hover: hover) and (pointer: fine)").matches;

// reveal on enter
const io = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } }), { rootMargin: "0px 0px -8% 0px" });
document.querySelectorAll(".rv").forEach((el) => io.observe(el));

// cursor ring with a label from data-cursor
if (fine && !reduce) {
  const c = document.createElement("div"); c.className = "cur"; c.innerHTML = "<span></span>"; document.body.appendChild(c);
  let x = innerWidth / 2, y = innerHeight / 2, cx = x, cy = y;
  addEventListener("pointermove", (e) => { x = e.clientX; y = e.clientY; }, { passive: true });
  (function f() { cx += (x - cx) * 0.2; cy += (y - cy) * 0.2; c.style.transform = `translate(${cx}px, ${cy}px)`; requestAnimationFrame(f); })();
  document.addEventListener("pointerover", (e) => { const t = e.target.closest("a, button, [data-cursor]"); c.classList.toggle("on", !!t); c.firstChild.textContent = t ? (t.dataset.cursor || "") : ""; });
}

// sound: a generated ambient bed (Web Audio, no files), off by default, remembered per visitor
const btn = document.querySelector(".sound");
let ctx = null, master = null;
function startSound() {
  ctx = ctx || new AudioContext();
  if (!master) {
    master = ctx.createGain(); master.gain.value = 0; master.connect(ctx.destination);
    const lp = ctx.createBiquadFilter(); lp.type = "lowpass"; lp.frequency.value = 900; lp.Q.value = 0.4; lp.connect(master);
    [55, 82.41, 110, 164.81].forEach((f, i) => {
      const o = ctx.createOscillator(), g = ctx.createGain(), l = ctx.createOscillator(), lg = ctx.createGain();
      o.type = i % 2 ? "sine" : "triangle"; o.frequency.value = f; o.detune.value = (i - 1.5) * 4;
      g.gain.value = [0.16, 0.07, 0.06, 0.025][i]; l.frequency.value = 0.05 + i * 0.03; lg.gain.value = g.gain.value * 0.6;
      l.connect(lg); lg.connect(g.gain); o.connect(g); g.connect(lp); o.start(); l.start();
    });
  }
  ctx.resume(); master.gain.cancelScheduledValues(ctx.currentTime); master.gain.linearRampToValueAtTime(0.5, ctx.currentTime + 1.6);
}
function stopSound() { if (master) { master.gain.cancelScheduledValues(ctx.currentTime); master.gain.linearRampToValueAtTime(0, ctx.currentTime + 0.6); } }
if (btn) {
  const set = (on) => { btn.setAttribute("aria-pressed", on); btn.querySelector(".lbl").textContent = on ? "Sound on" : "Sound off"; try { localStorage.setItem("x-sound", on ? "1" : "0"); } catch {} };
  btn.addEventListener("click", () => { const on = btn.getAttribute("aria-pressed") !== "true"; set(on); on ? startSound() : stopSound(); });
  window.xSound = { blip(freq = 880, dur = 0.08) { if (!ctx || btn.getAttribute("aria-pressed") !== "true") return; const o = ctx.createOscillator(), g = ctx.createGain(); o.frequency.value = freq; g.gain.value = 0.04; g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + dur); o.connect(g); g.connect(ctx.destination); o.start(); o.stop(ctx.currentTime + dur); } };
}

// veil between pages (same-origin links only; browsers with cross-document view transitions use those instead)
if (!reduce && !("onpagereveal" in window)) {
  const v = document.createElement("div"); v.className = "veil"; document.body.appendChild(v);
  document.addEventListener("click", (e) => {
    const a = e.target.closest("a[href]"); if (!a || e.metaKey || e.ctrlKey || e.shiftKey || a.target === "_blank" || a.hasAttribute("download")) return;
    const u = new URL(a.href, location.href); if (u.origin !== location.origin || u.hash && u.pathname === location.pathname) return;
    e.preventDefault(); v.classList.add("on"); setTimeout(() => (location.href = u.href), 420);
  });
  addEventListener("pageshow", () => v.classList.remove("on"));
}

// starfield backdrop for non-film pages: a 2D canvas, drawn once per resize, drifts slowly
const sf = document.querySelector("canvas.stars");
if (sf) {
  const g = sf.getContext("2d"); let pts = [];
  const draw = (t) => { const w = sf.width, h = sf.height; g.clearRect(0, 0, w, h); for (const p of pts) { const y = (p.y + (reduce ? 0 : t * p.s * 0.004)) % h; g.globalAlpha = p.a; g.fillStyle = "#fff"; g.fillRect(p.x, y, p.r, p.r); } };
  const size = () => { const d = Math.min(devicePixelRatio, 2); sf.width = innerWidth * d; sf.height = innerHeight * d; pts = Array.from({ length: Math.round(innerWidth * innerHeight / 2600) }, () => ({ x: Math.random() * sf.width, y: Math.random() * sf.height, r: (Math.random() < 0.1 ? 2 : 1) * d, a: 0.2 + Math.random() * 0.6, s: 0.3 + Math.random() })); draw(0); };
  addEventListener("resize", size); size();
  if (!reduce) (function f(t) { draw(t); requestAnimationFrame(f); })(0);
}
