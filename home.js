/* The home page's behaviour (one classic script, no build step).
   Hero: a 48-frame Blender camera flight (tools/desk/flight.py) drawn on a canvas as the hero scrolls: from high over the desk
   down onto the boarding pass, while the RISHIT wordmark splits and "Clean. Model. Explain." passes; the boarding pass then
   hands over to the first project screen. The intro on first load is CSS (portfolio.css, html.intro).
   Selected Work: each screen's printed object lifts off the table, its number counts up, then it flips to show what I did;
   the pager follows the current project. Everything that moves is driven by scroll and stops under reduced motion, where
   the page shows the finished still images. */
(() => {
  "use strict";
  const root = document.documentElement, $ = id => document.getElementById(id);
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const fine = matchMedia("(hover: hover) and (pointer: fine)").matches;
  const cl = v => Math.max(0, Math.min(1, v)), ease = t => 1 - Math.pow(1 - t, 3);
  root.classList.add(reduced ? "is-still" : "is-moving");

  let lenis = null;
  if (typeof Lenis !== "undefined" && !reduced) { lenis = new Lenis({ lerp: 0.11, autoRaf: true, anchors: true }); root.classList.add("lenis-on"); }

  /* one scroll loop for everything scroll-driven */
  const jobs = [];
  let raf = 0;
  const run = () => { raf = 0; for (const j of jobs) j(); };
  const kick = () => { if (!raf) raf = requestAnimationFrame(run); };
  addEventListener("scroll", kick, { passive: true });

  /* the nav steps away while scrolling down past the hero's first screen and returns on any scroll up */
  const nav = $("nav");
  let lastY = scrollY;
  jobs.push(() => { const y = scrollY; if (Math.abs(y - lastY) > 6) { nav.classList.toggle("is-away", y > lastY && y > innerHeight * 0.6); lastY = y; } });
  addEventListener("resize", kick);

  /* ---- hero: frames load after first paint; scroll through the hero picks the frame ---- */
  const hero = document.querySelector(".hero"), cv = $("hero-canvas"), ctx = cv.getContext("2d");
  const tall = matchMedia("(max-aspect-ratio: 4/5)").matches, SET = tall ? "m" : "d", N = 48;
  const letters = [...document.querySelectorAll(".wordmark-xl span")], words = [...document.querySelectorAll(".beat span")];
  if (!reduced) {
    const imgs = Array(N).fill(null);
    let shown = -1;
    const draw = i => {
      let k = -1;
      for (let d = 0; d < N && k < 0; d++) k = imgs[i - d] ? i - d : imgs[i + d] ? i + d : -1;
      if (k < 0 || k === shown) return;
      const dpr = Math.min(devicePixelRatio || 1, 2), w = Math.round(cv.clientWidth * dpr), h = Math.round(cv.clientHeight * dpr);
      if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; }
      const im = imgs[k], s = Math.max(w / im.width, h / im.height), dw = im.width * s, dh = im.height * s;   // cover, like the still
      ctx.drawImage(im, (w - dw) / 2, (h - dh) * 0.3, dw, dh); shown = k;   // cropped like the still (object-position 50% 30%)
      root.classList.add("hero-live");
    };
    addEventListener("resize", () => { shown = -1; });
    jobs.push(() => {
      const r = hero.getBoundingClientRect(), p = cl(-r.top / Math.max(1, r.height - innerHeight));
      if (r.bottom < 0) return;
      draw(Math.round(cl(p / 0.92) * (N - 1)));
      hero.style.setProperty("--p", p.toFixed(3));
      hero.style.setProperty("--veil", (cl((p - 0.22) / 0.08) * (1 - cl((p - 0.8) / 0.08))).toFixed(3));
      letters.forEach((el, i) => { el.style.transform = `translateX(${((i - 2.5) * ease(cl(p * 1.6)) * 9).toFixed(2)}vw)`; el.style.opacity = (1 - cl(p * 3.8)).toFixed(3); });
      words.forEach((el, i) => { const a = cl((p - 0.28 - i * 0.07) / 0.1), b = cl((p - 0.74) / 0.08); el.style.opacity = (a * (1 - b)).toFixed(3); el.style.transform = `translateY(${((1 - ease(a)) * 40).toFixed(1)}px)`; });
    });
    const load = i => new Promise(done => {
      const img = new Image();
      img.onload = () => { imgs[i] = img; if (i === 0 || Math.abs(i - shown) < 4) kick(); done(); };
      img.onerror = done;
      img.src = `assets/flight/${SET}/${String(i).padStart(3, "0")}.webp`;
    });
    setTimeout(async () => { await load(0); for (let i = 1; i < N; i += 8) await Promise.all(Array.from({ length: 8 }, (_, k) => i + k).filter(k => k < N).map(load)); }, 400);
  }

  /* ---- Selected Work: lift, count, flip as each sticky screen scrolls ---- */
  const screens = [...document.querySelectorAll(".screen")].map(s => {
    const v = s.querySelector(".num-v"), end = +s.dataset.value;
    return { s, card: s.querySelector(".card"), v, end, dec: (String(end).split(".")[1] || "").length, final: v.textContent, counts: !/\bof\b/.test(s.dataset.unit) };
  });
  if (!reduced) jobs.push(() => {
    for (const o of screens) {
      const r = o.s.getBoundingClientRect();
      if (r.bottom < -100 || r.top > innerHeight + 100) continue;
      const p = cl(-r.top / Math.max(1, r.height - innerHeight)), enter = cl((innerHeight - r.top) / innerHeight);
      const lift = ease(cl((enter - 0.2) / 0.8)), flip = ease(cl((p - 0.45) / 0.3));
      o.card.style.transform = `translateY(${((1 - lift) * 30).toFixed(2)}vh) rotate(${(-10 + 7 * lift).toFixed(2)}deg) scale(${(0.86 + 0.14 * lift).toFixed(3)}) rotateY(${(180 * flip).toFixed(1)}deg)`;
      o.card.classList.toggle("is-flipped", flip > 0.5);
      // "31 of 31" counted up would read as failing tests on the way, so only percentages count
      if (o.counts) { const k = ease(cl((enter - 0.25) / 0.6)); o.v.textContent = k < 1 ? (o.end * k).toFixed(o.dec) : o.final; }
    }
  });

  /* the pager names the current project; arrows go to the neighbouring screen */
  const pager = $("work-pager"), work = $("work"), pname = $("pager-name");
  let cur = 0;
  jobs.push(() => {
    const wr = work.getBoundingClientRect();
    pager.classList.toggle("is-on", wr.top < innerHeight * 0.5 && wr.bottom > innerHeight * 0.8);
    let i = screens.findIndex(o => { const r = o.s.getBoundingClientRect(); return r.top <= innerHeight * 0.5 && r.bottom > innerHeight * 0.5; });
    if (i < 0) i = cur;
    if (i !== cur || !pname.dataset.set) {
      cur = i; pname.dataset.set = "1";
      pname.textContent = screens[i].s.dataset.title; pname.href = screens[i].s.dataset.slug + "/";
      $("pager-prev").disabled = i === 0; $("pager-next").disabled = i === screens.length - 1;
    }
  });
  const go = d => {
    const t = screens[cur + d];
    if (!t) return;
    lenis ? lenis.scrollTo(t.s, { duration: 1.1 }) : t.s.scrollIntoView({ behavior: reduced ? "instant" : "smooth" });
  };
  $("pager-prev").addEventListener("click", () => go(-1));
  $("pager-next").addEventListener("click", () => go(1));
  kick();

  /* ---- phone menu: one row (wordmark + Menu); the links open as a sheet ---- */
  const menuBtn = $("menu-btn"), linksBox = $("nav-links");
  const setMenu = open => { menuBtn.setAttribute("aria-expanded", String(open)); document.body.classList.toggle("menu-open", open); menuBtn.textContent = open ? "Close" : "Menu"; };
  menuBtn.addEventListener("click", () => setMenu(menuBtn.getAttribute("aria-expanded") !== "true"));
  linksBox.addEventListener("click", e => { if (e.target.closest("a")) setMenu(false); });
  addEventListener("keydown", e => { if (e.key === "Escape" && document.body.classList.contains("menu-open")) { setMenu(false); menuBtn.focus(); } });

  /* ---- the business card leans toward a fine pointer ---- */
  const card = $("biz-card");
  if (fine && !reduced) {
    card.addEventListener("pointermove", e => { const r = card.getBoundingClientRect(), x = (e.clientX - r.left) / r.width - 0.5, y = (e.clientY - r.top) / r.height - 0.5; card.style.transform = `perspective(1000px) rotateY(${(x * 10).toFixed(2)}deg) rotateX(${(-y * 8).toFixed(2)}deg)`; });
    card.addEventListener("pointerleave", () => { card.style.transform = ""; });
  }

  /* ---- copy e-mail ---- */
  const copyBtn = $("copy-mail");
  if (navigator.clipboard && copyBtn) {
    copyBtn.hidden = false;
    copyBtn.addEventListener("click", async () => {
      const label = copyBtn.querySelector(".copy-text");
      try { await navigator.clipboard.writeText(copyBtn.dataset.mail); label.textContent = "Copied"; $("copy-status").textContent = "E-mail address copied"; }
      catch (_) { label.textContent = "Copy failed"; $("copy-status").textContent = "Could not copy; the address is the link above"; }
      setTimeout(() => { label.textContent = "Copy e-mail"; }, 2200);
    });
  }
})();
