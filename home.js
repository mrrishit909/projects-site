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
  const introOn = root.classList.contains("intro");
  let introRun = introOn && !reduced;   // the camera is lifting off the boarding pass: scroll does not drive the hero yet
  if (!reduced) {
    const imgs = Array(N).fill(null);
    let shown = null;
    const blit = im => {
      if (im === shown) return;
      const dpr = Math.min(devicePixelRatio || 1, 2), w = Math.round(cv.clientWidth * dpr), h = Math.round(cv.clientHeight * dpr);
      if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; }
      const s = Math.max(w / im.width, h / im.height), dw = im.width * s, dh = im.height * s;   // cover, like the still
      ctx.drawImage(im, (w - dw) / 2, (h - dh) * 0.3, dw, dh); shown = im;   // cropped like the still (object-position 50% 30%)
      root.classList.add("hero-live");
    };
    const draw = i => {   // the nearest flight frame that has arrived
      let k = -1;
      for (let d = 0; d < N && k < 0; d++) k = imgs[i - d] ? i - d : imgs[i + d] ? i + d : -1;
      if (k >= 0) blit(imgs[k]);
    };
    addEventListener("resize", () => { shown = null; });
    jobs.push(() => {
      if (introRun) return;
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
      img.onload = () => { imgs[i] = img; if (i === 0 || (shown && Math.abs(i - imgs.indexOf(shown)) < 4)) kick(); done(); };
      img.onerror = done;
      img.src = `assets/flight/${SET}/${String(i).padStart(3, "0")}.webp`;
    });
    /* the intro: the boarding pass prints from the top down (seven frames, tools/desk/world.py), holds a beat, then the
       flight plays backwards, 47 -> 0, over 2.6 s so the camera lifts off onto the whole desk (faster on a repeat visit);
       the wordmark lands at 55% of the lift; a skip button, any wheel, key or tap ends it at once; after 7 s it ends
       regardless (frames that never came). Then scroll owns the hero as usual. */
    const endIntro = () => { if (!introRun) return; introRun = false; draw(0); root.classList.add("intro-land", "intro-done"); if (lenis) lenis.start(); kick(); };
    if (introRun) {
      if (lenis) lenis.stop();
      scrollTo(0, 0);
      const P = 7, prints = Array(P).fill(null);
      const loadPrint = i => new Promise(done => { const img = new Image(); img.onload = () => { prints[i] = img; done(); }; img.onerror = done; img.src = `assets/world/${SET}/print-${String(i).padStart(2, "0")}.webp`; });
      const k = root.classList.contains("intro-again") ? 0.45 : 1, TP = 820 * k, TH = 320 * k, D = 2600 * k;
      let t0 = 0, started = false;
      const tick = now => {
        if (!introRun) return;
        if (!t0) t0 = now;
        const t = now - t0;
        if (t < TP + TH) {   // printing: a frame every 117 ms, then the finished pass held for a beat
          const j = Math.min(P - 1, Math.floor(t / TP * P));
          for (let q = j; q >= 0; q--) if (prints[q]) { blit(prints[q]); break; }
        } else {
          const u = cl((t - TP - TH) / D), e = u < 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2;
          draw(Math.round((N - 1) * (1 - e)));
          if (u > 0.55) root.classList.add("intro-land");
          if (u >= 1) { endIntro(); return; }
        }
        requestAnimationFrame(tick);
      };
      const start = () => { if (!started) { started = true; requestAnimationFrame(tick); } };
      setTimeout(start, 1500);
      setTimeout(endIntro, 7000 * k);
      $("intro-skip").addEventListener("click", endIntro);
      for (const ev of ["wheel", "touchstart", "keydown", "pointerdown"]) addEventListener(ev, e => { if (e.target !== $("intro-skip")) endIntro(); }, { passive: true });
      (async () => {
        await Promise.all(Array.from({ length: P - 1 }, (_, q) => loadPrint(q + 1)));   // print-00 is the still already on screen
        start();
        for (let i = N - 1; i >= 0; i -= 8) await Promise.all(Array.from({ length: 8 }, (_, q) => i - q).filter(q => q >= 0).map(load));
      })();
    } else {
      setTimeout(async () => { await load(0); for (let i = 1; i < N; i += 8) await Promise.all(Array.from({ length: 8 }, (_, k) => i + k).filter(k => k < N).map(load)); }, 400);
    }
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
      o.s.style.setProperty("--kb", p.toFixed(3));                                   // the camera breathes
      o.s.style.setProperty("--slide", ease(cl((p - 0.12) / 0.33)).toFixed(3));       // the artefact slides out from under the object
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

  /* ---- into a case study and back: the clicked project's object and title travel (cross-document View Transitions).
     Only the project being opened carries the names, so the other three cards never collide; sessionStorage "vt" tells the
     returning home which card to hand the object back to (and the head script to skip the intro). ---- */
  const nameFor = (slug, on) => {
    const o = screens.find(o => o.s.dataset.slug === slug);
    if (!o) return;
    // the face that is showing travels: the printed front, or the back when the card has flipped to "What I did"
    const front = o.s.querySelector(".front"), back = o.s.querySelector(".back"), flipped = o.card.classList.contains("is-flipped");
    front.style.viewTransitionName = on && !flipped ? "object" : "";
    back.style.viewTransitionName = on && flipped ? "object" : "";
    o.s.querySelector("h3 a").style.viewTransitionName = on ? "title" : "";
  };
  const slugOf = url => { try { const path = new URL(url, location.href).pathname; return screens.map(o => o.s.dataset.slug).find(s => path.endsWith("/" + s + "/")); } catch (_) { return null; } };
  addEventListener("pageswap", e => {
    if (!e.viewTransition) return;
    const to = e.activation && e.activation.entry && e.activation.entry.url, s = to && slugOf(to);
    if (!s) { e.viewTransition.skipTransition(); return; }
    nameFor(s, true);
    try { sessionStorage.setItem("vt", s); } catch (_) {}
  });
  addEventListener("pagereveal", e => {
    let s = null;
    try { s = sessionStorage.getItem("vt"); sessionStorage.removeItem("vt"); } catch (_) {}
    if (!e.viewTransition) return;
    if (!s) { e.viewTransition.skipTransition(); return; }
    run(); nameFor(s, true);
    e.viewTransition.finished.then(() => nameFor(s, false));
  });

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

  /* ---- the desk's clock: Tampa time in the footer ---- */
  const clock = $("clock");
  if (clock) {
    const fmt = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" });
    const tickClock = () => { clock.textContent = fmt.format(new Date()) + " in Tampa"; };
    tickClock(); setInterval(tickClock, 30000);
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
