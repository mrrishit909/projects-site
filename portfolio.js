/* The portfolio's DOM behaviour (classic script; the corridor in scene.js is a module and reports in through events).
   The intro count, smooth scroll (Lenis), the scroll choreography (GSAP ScrollTrigger: the corridor statements, the
   horizontal flagship track, the reveals), the kinetic name, the live clock, the complete catalogue (search, kind filter,
   twelve-at-a-time reveal, cover previews from the atlas, the project dialog on #<slug>), the flagship screenshot viewer,
   cross-document View Transitions into the case studies, and the static fallback when the scene never reports in. */
(() => {
  "use strict";
  const root = document.documentElement, $ = id => document.getElementById(id);
  const motionQuery = matchMedia("(prefers-reduced-motion: reduce)");
  const reduced = () => motionQuery.matches;
  const fine = matchMedia("(hover: hover) and (pointer: fine)").matches;
  const DATA = JSON.parse($("projects-data").textContent);
  const bySlug = new Map(DATA.map((p, i) => [p.slug, { ...p, index: i }]));
  const hasGsap = typeof gsap !== "undefined" && typeof ScrollTrigger !== "undefined";
  if (hasGsap) gsap.registerPlugin(ScrollTrigger, typeof SplitText !== "undefined" ? SplitText : undefined);
  const ATLAS = JSON.parse($("scene").dataset.atlas);

  /* ---- smooth scroll: Lenis drives native scroll with a little weight; it honours reduced motion itself ---- */
  let lenis = null;
  if (typeof Lenis !== "undefined" && hasGsap && !reduced()) {
    lenis = new Lenis({ lerp: 0.11, wheelMultiplier: 1, anchors: { offset: -8 } });
    lenis.on("scroll", ScrollTrigger.update);
    gsap.ticker.add(t => lenis.raf(t * 1000));
    gsap.ticker.lagSmoothing(0);
    root.classList.add("lenis-on");
  }
  const scrollToY = (y, instant) => { if (lenis && !instant) lenis.scrollTo(y); else scrollTo({ top: y, behavior: "instant" }); };

  /* ---- the intro: a count of the catalogue while the covers arrive; the curtain lifts into the hero ---- */
  const hero = document.querySelector(".hero-copy"), intro = $("intro");
  const heroLines = [...document.querySelectorAll(".hero h1 .line")];
  heroLines.forEach(line => {                                       // letters as spans: the weight swells under the cursor
    const text = line.textContent; line.textContent = "";
    [...text].forEach(ch => { const s = document.createElement("span"); s.className = "ch"; s.textContent = ch; line.append(s); });
  });
  const letters = [...document.querySelectorAll(".hero h1 .ch")];
  function enterHero(fast) {
    root.classList.add("is-ready");
    if (!hasGsap || reduced() || fast) { hero.classList.add("is-shown"); return; }
    const tl = gsap.timeline({ defaults: { ease: "power4.out" } });
    tl.from(letters, { yPercent: 110, duration: 1.1, stagger: 0.035 }, 0)
      .from(".hero .eyebrow, .hero-role, .hero-text, .hero-aside, .scroll-hint, .marquee", { y: 24, autoAlpha: 0, duration: 0.9, stagger: 0.07 }, 0.45)
      .from("#scene", { autoAlpha: 0, duration: 1.4, ease: "power2.out" }, 0)
      .add(() => hero.classList.add("is-shown"));
  }
  let loaded = 0, loadTotal = 1;
  addEventListener("portfolio:load", e => { loaded = e.detail.loaded; loadTotal = e.detail.total; });
  function runIntro() {
    if (!intro || root.classList.contains("intro-off") || !hasGsap || reduced()) { intro?.remove(); enterHero(true); return; }
    try { sessionStorage.setItem("portfolio-intro", "1"); } catch (_) {}
    if (lenis) lenis.stop(); scrollTo(0, 0);
    const count = $("intro-count"), bar = $("intro-bar"), flip = $("intro-flip"), ctx = flip.getContext("2d");
    const atlas = new Image(); atlas.src = `assets/wall/atlas-0.jpg`;
    const [tw, th] = ATLAS.tile, cols = ATLAS.cols, n = DATA.length;
    let shown = -1, done = false;
    const flipTimer = setInterval(() => {                           // real covers flash in the frame as the count runs
      if (!atlas.complete || !atlas.naturalWidth) return;
      shown = (shown + 7) % Math.min(66, n);
      ctx.drawImage(atlas, (shown % cols) * tw, Math.floor(shown / cols) * th, tw, th, 0, 0, flip.width, flip.height);
    }, 70);
    const v = { n: 0 };
    const tl = gsap.timeline({ paused: true });
    tl.to(v, { n, duration: 2.1, ease: "power2.inOut", onUpdate: () => { count.textContent = String(Math.round(v.n)).padStart(3, "0"); bar.style.transform = `scaleX(${v.n / n})`; } }, 0)
      .from(".intro-label, .intro-sub, .intro-skip", { autoAlpha: 0, y: 12, duration: 0.6, stagger: 0.1 }, 0.1)
      .from(flip, { autoAlpha: 0, scale: 0.92, duration: 0.8, ease: "power3.out" }, 0.2)
      .from(count, { yPercent: 40, autoAlpha: 0, duration: 0.8, ease: "power3.out" }, 0);
    const leave = () => {
      if (done) return; done = true;
      clearInterval(flipTimer);
      tl.kill(); count.textContent = String(n).padStart(3, "0");
      const out = gsap.timeline({ onComplete: () => { intro.remove(); if (lenis) lenis.start(); root.classList.remove("is-intro"); } });
      out.to([count, flip, ".intro-label", ".intro-sub", ".intro-skip", bar], { y: -40, autoAlpha: 0, duration: 0.45, ease: "power3.in", stagger: 0.03 }, 0)
         .to(intro, { clipPath: "inset(0 0 100% 0)", duration: 1.0, ease: "expo.inOut" }, 0.35)
         .add(() => enterHero(false), 0.55);
    };
    const waitLoad = () => { if (loaded >= 1 || performance.now() > 6000) leave(); else setTimeout(waitLoad, 100); };
    tl.eventCallback("onComplete", waitLoad);
    tl.play();
    const skip = e => { if (e.type === "keydown" && e.key === "Tab") return; leave(); };
    intro.addEventListener("click", skip); addEventListener("keydown", skip, { once: true });
  }
  if (document.fonts?.ready) Promise.race([document.fonts.ready, new Promise(r => setTimeout(r, 800))]).then(() => requestAnimationFrame(runIntro)); else runIntro();

  /* ---- kinetic name: the variable weight follows the cursor across the letters ---- */
  if (fine && letters.length) {
    const h1 = document.querySelector(".hero h1");
    let rects = [], raf = 0;
    const measureLetters = () => { rects = letters.map(l => { const r = l.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }); };
    h1.addEventListener("pointerenter", measureLetters);
    h1.addEventListener("pointermove", e => {
      if (raf || reduced()) return;
      raf = requestAnimationFrame(() => { raf = 0; letters.forEach((l, i) => { const d = Math.hypot(e.clientX - rects[i][0], e.clientY - rects[i][1]); l.style.setProperty("--w", (300 + 300 * Math.exp(-d * d / 26000)).toFixed(0)); }); });
    });
    h1.addEventListener("pointerleave", () => letters.forEach(l => l.style.removeProperty("--w")));
  }

  /* ---- live clock in Tampa: the one piece of chrome that proves the page is alive ---- */
  const clockEl = $("nav-clock");
  if (clockEl) {
    const fmt = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "2-digit", minute: "2-digit", hour12: false });
    const tick = () => { clockEl.textContent = `Tampa ${fmt.format(new Date())}`; };
    tick(); setInterval(tick, 15000);
  }

  /* ---- navigation: a surface once the hero scrolls away, paper colours over the reading world, a sliding current mark ---- */
  const nav = $("nav"), navLinks = [...document.querySelectorAll(".nav-links a[href^='#']")];
  const mark = document.createElement("span"); mark.className = "nav-mark"; document.querySelector(".nav-links").append(mark);
  let currentLink = null;
  function moveMark(a, animate) {
    if (!a) { mark.classList.remove("is-on"); return; }
    const prev = mark.style.transition;
    if (!animate) mark.style.transition = "none";
    mark.style.transform = `translateX(${a.offsetLeft}px)`; mark.style.width = `${a.offsetWidth}px`;
    if (!animate) { void mark.offsetWidth; mark.style.transition = prev; }
    mark.classList.add("is-on");
  }
  const spy = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) { navLinks.forEach(a => a.classList.toggle("is-current", a.hash === "#" + e.target.id)); const a = navLinks.find(a => a.hash === "#" + e.target.id); if (a !== currentLink) { moveMark(a, !!currentLink); currentLink = a; } } }), { rootMargin: "-40% 0px -55% 0px" });
  navLinks.forEach(a => { const s = document.querySelector(a.hash); if (s) spy.observe(s); });
  spy.observe($("top"));                                                 // the hero carries no link: the mark leaves
  addEventListener("resize", () => moveMark(currentLink, false));
  const paper = document.querySelector(".reading-world");
  function navState() {
    nav.classList.toggle("is-scrolled", scrollY > 24);
    if (paper) { const r = paper.getBoundingClientRect(); nav.classList.toggle("on-paper", r.top < 36 && r.bottom > 36); }
  }
  addEventListener("scroll", navState, { passive: true }); navState();

  /* ---- the corridor: statements take turns in the centre as the camera flies; a running index names the screen passed ---- */
  const corridor = $("corridor"), statements = [...document.querySelectorAll(".statement")], corrN = $("corridor-n");
  const squareUp = () => { if (corridor) corridor.style.minHeight = Math.round(innerHeight * 3.2) + "px"; };   // whole pixels: the pinned track then starts on a whole scroll position (no layout-shift report at the pin)
  squareUp(); addEventListener("resize", squareUp);
  function corridorProgress() {
    if (!corridor) return;
    const r = corridor.getBoundingClientRect(), span = Math.max(1, r.height - innerHeight);
    const p = Math.min(1, Math.max(0, -r.top / span));
    statements.forEach((li, i) => { const at = +li.dataset.at, next = statements[i + 1] ? +statements[i + 1].dataset.at : 1.08; li.classList.toggle("is-on", p >= at && p < next - 0.04); });
    if (corrN) corrN.textContent = String(Math.min(DATA.length, Math.round(p * DATA.length))).padStart(3, "0");
    root.classList.toggle("in-corridor", r.top <= 0 && r.bottom > innerHeight);
  }
  addEventListener("scroll", corridorProgress, { passive: true }); corridorProgress();

  /* ---- the flagship track: horizontal on wide screens, scrubbed by the scroll; vertical elsewhere ---- */
  const track = $("track"), work = $("work"), panels = [...document.querySelectorAll(".panel")], railNo = $("rail-no"), railFill = $("rail-fill");
  const readings = [...document.querySelectorAll(".reading-value")];
  const fmtReading = (el, v) => { const unit = el.dataset.unit || "", dec = (String(el.dataset.value).split(".")[1] || "").length; el.textContent = v.toFixed(dec) + unit; };
  function railAt(p) {                                                 // p: 0 (intro panel) .. 1 (last flagship)
    const n = panels.length - 1, i = Math.min(n, Math.max(0, Math.round(p * n)));
    if (railNo) railNo.textContent = String(i).padStart(2, "0");
    if (railFill) railFill.style.transform = `scaleX(${p})`;
  }
  if (hasGsap && track) {
    const mm = gsap.matchMedia();
    mm.add("(min-width: 1024px) and (prefers-reduced-motion: no-preference)", () => {
      root.classList.add("track-horizontal");
      const dist = () => track.scrollWidth - innerWidth;
      const tween = gsap.to(track, { x: () => -dist(), ease: "none",
        scrollTrigger: { trigger: work, pin: true, pinType: "transform", scrub: 0.6, start: "top top", end: () => "+=" + dist() * 1.05, invalidateOnRefresh: true,
          onUpdate: self => { railAt(self.progress); root.classList.toggle("in-track", self.isActive); }, onRefresh: () => dispatchEvent(new CustomEvent("portfolio:layout")) } });
      panels.forEach((panel, i) => {                                   // each flagship's figure counts up and its screenshot slides inside the frame as the panel crosses
        const img = panel.querySelector(".feature-figure img"), val = panel.querySelector(".reading-value");
        if (img) gsap.fromTo(img, { xPercent: -6 }, { xPercent: 6, ease: "none", scrollTrigger: { trigger: panel, containerAnimation: tween, start: "left right", end: "right left", scrub: true } });
        if (val) { const target = +val.dataset.value; const o = { v: 0 }; gsap.to(o, { v: target, ease: "power2.out", duration: 1.2, paused: true, onUpdate: () => fmtReading(val, o.v), scrollTrigger: { trigger: panel, containerAnimation: tween, start: "left 70%", toggleActions: "play none none none" } }); }
        const copy = panel.querySelector(".feature-copy");
        if (copy) gsap.from(copy.children, { y: 26, opacity: 0, duration: 0.8, stagger: 0.06, ease: "power3.out", scrollTrigger: { trigger: panel, containerAnimation: tween, start: "left 60%" } });
      });
      return () => { root.classList.remove("track-horizontal", "in-track"); };
    });
    mm.add("(max-width: 1023px), (prefers-reduced-motion: reduce)", () => {
      readings.forEach(val => { if (reduced()) return; const target = +val.dataset.value, o = { v: 0 }; gsap.to(o, { v: target, ease: "power2.out", duration: 1.2, onUpdate: () => fmtReading(val, o.v), scrollTrigger: { trigger: val, start: "top 85%" } }); });
    });
  }

  /* ---- reveals: one orchestrated entrance per element, lines rising inside a mask; the about statement reads itself in ---- */
  if (hasGsap && !reduced()) {
    const heads = [...document.querySelectorAll(".section-head h2, .panel-intro h2, .contact h2")];
    const split = typeof SplitText !== "undefined";
    heads.forEach(h => {
      if (split) { const s = new SplitText(h, { type: "lines", mask: "lines", linesClass: "sl" }); gsap.from(s.lines, { yPercent: 110, duration: 1, ease: "power4.out", stagger: 0.08, scrollTrigger: { trigger: h, start: "top 88%" } }); }
      else gsap.from(h, { y: 24, autoAlpha: 0, duration: 0.8, scrollTrigger: { trigger: h, start: "top 88%" } });
    });
    const st = $("about-statement");
    if (st && split) { const s = new SplitText(st, { type: "words" }); gsap.from(s.words, { opacity: 0.16, stagger: 0.04, ease: "none", scrollTrigger: { trigger: st, start: "top 80%", end: "bottom 45%", scrub: true } }); }
    // opacity, not visibility: a control that has not scrolled into its reveal yet must still be focusable and fillable
    gsap.utils.toArray(".section-head .eyebrow, .about-copy, .about-facts > div, .cap-list li, .toolbar, .contact .section-lede, .contact-links, .contact-mail").forEach(el => gsap.from(el, { y: 28, opacity: 0, duration: 0.9, ease: "power3.out", scrollTrigger: { trigger: el, start: "top 90%" } }));
    gsap.utils.toArray(".timeline li").forEach((li, i) => gsap.from(li, { x: -24, opacity: 0, duration: 0.8, ease: "power3.out", scrollTrigger: { trigger: li, start: "top 88%" } }));
    const tlLine = $("timeline");
    if (tlLine) gsap.fromTo(tlLine, { "--draw": 0 }, { "--draw": 1, ease: "none", scrollTrigger: { trigger: tlLine, start: "top 75%", end: "bottom 60%", scrub: true } });
    if (!root.classList.contains("track-horizontal")) gsap.utils.toArray(".feature-copy").forEach(el => gsap.from(el.children, { y: 26, opacity: 0, duration: 0.8, stagger: 0.06, ease: "power3.out", scrollTrigger: { trigger: el, start: "top 85%" } }));
    gsap.from(".contact-copy h2", { scale: 0.96, transformOrigin: "left bottom", scrollTrigger: { trigger: "#contact", start: "top 70%" } });
  } else {
    document.querySelectorAll(".section-head, .about-copy, .about-facts, .timeline li, .cap-list li, .contact-copy, .feature-copy").forEach(el => el.classList.add("is-in"));
  }
  const tilesOl = $("tiles");
  if (hasGsap && !reduced() && tilesOl) gsap.from(".tile:not([hidden]):not(.is-beyond)", { y: 18, opacity: 0, duration: 0.6, stagger: { each: 0.03, grid: "auto", from: "start" }, ease: "power3.out", scrollTrigger: { trigger: tilesOl, start: "top 85%" } });

  /* ---- motion control: scene.js listens for the event; the preference is remembered per browser ---- */
  const toggle = $("motion-toggle");
  let paused = false;
  const setPaused = p => { paused = p; toggle.setAttribute("aria-pressed", String(p)); toggle.textContent = p ? "Motion off" : "Motion on"; try { localStorage.setItem("portfolio-motion", p ? "off" : "on"); } catch (_) {} dispatchEvent(new CustomEvent("portfolio:motion", { detail: { paused: p } })); root.classList.toggle("motion-off", p); };
  toggle.addEventListener("click", () => setPaused(!paused));
  if (root.classList.contains("motion-off")) setPaused(true);
  addEventListener("portfolio:scene", e => { toggle.hidden = e.detail.state !== "live" || reduced(); });
  motionQuery.addEventListener("change", () => { toggle.hidden = reduced() || !root.classList.contains("scene-live"); });
  setTimeout(() => { if (!root.classList.contains("scene-live")) root.classList.add("scene-static"); }, 9000);
  addEventListener("error", e => { if (/scene\.js|three/.test(e.filename || "")) root.classList.add("scene-static"); }, true);

  /* ---- a numerical spring for direct feedback: the dialog panels settle in from below ---- */
  const cssNum = (n, d) => +getComputedStyle(root).getPropertyValue(n) || d;
  const SPRING = { k: cssNum("--s-spring-responsive-stiffness", 260), c: cssNum("--s-spring-responsive-damping", 26) };
  const springs = new WeakMap();
  function settle(el, from) {
    if (reduced()) { el.style.transform = ""; return; }
    const st = springs.get(el) || { y: from.y, s: from.s, vy: 0, vs: 0, raf: 0 };
    if (!springs.has(el)) springs.set(el, st); else { st.y = from.y; st.s = from.s; }
    cancelAnimationFrame(st.raf);
    let last = performance.now();
    const tick = now => {
      const dt = Math.min(0.05, (now - last) / 1000); last = now;
      st.vy += (-SPRING.k * st.y - SPRING.c * st.vy) * dt; st.y += st.vy * dt;
      st.vs += (-SPRING.k * (st.s - 1) - SPRING.c * st.vs) * dt; st.s += st.vs * dt;
      if (Math.abs(st.y) < 0.2 && Math.abs(st.vy) < 2 && Math.abs(st.s - 1) < 0.002) { el.style.transform = ""; st.raf = 0; return; }
      el.style.transform = `translateY(${st.y.toFixed(2)}px) scale(${st.s.toFixed(4)})`;
      st.raf = requestAnimationFrame(tick);
    };
    st.raf = requestAnimationFrame(tick);
  }

  /* ---- cover previews from the atlas: a floating card follows the cursor over catalogue entries and capability rows ---- */
  const peek = $("peek"), PW = 256, PH = Math.round(256 * ATLAS.tile[1] / ATLAS.tile[0]);
  const peekAt = w => { if (!w) return; const [a, c, r] = w; peek.style.backgroundImage = `url(assets/wall/atlas-${a}.jpg)`; peek.style.backgroundSize = `${ATLAS.size / ATLAS.tile[0] * PW}px auto`; peek.style.backgroundPosition = `-${c * PW}px -${r * PH}px`; };
  if (fine && peek && hasGsap) {
    const qx = gsap.quickTo(peek, "x", { duration: 0.35, ease: "power3" }), qy = gsap.quickTo(peek, "y", { duration: 0.35, ease: "power3" });
    let on = null;
    document.addEventListener("pointermove", e => {
      const t = e.target.closest(".tile, .cap-list li[data-peek]");
      if (t !== on) {
        on = t;
        if (t) { const p = bySlug.get(t.dataset.slug || t.dataset.peek); peekAt(p?.w); peek.classList.add("is-on"); gsap.set(peek, { x: e.clientX + 20, y: e.clientY - PH / 2 }); }
        else peek.classList.remove("is-on");
      }
      if (t) { qx(e.clientX + 20); qy(e.clientY - PH / 2); }
    });
    addEventListener("scroll", () => { if (on) { on = null; peek.classList.remove("is-on"); } }, { passive: true });   // never left floating after the page moves under the cursor
  }

  /* ---- the catalogue: twelve at a time, more only on request ---- */
  const tiles = [...document.querySelectorAll(".tile")], total = tiles.length, PAGE = 12;
  const search = $("search"), kind = $("kind"), clear = $("clear"), more = $("more"), resetAll = $("reset-all");
  const kindTabs = [...document.querySelectorAll(".kind-tab")], pill = document.querySelector(".kinds-pill");
  function paintTabs(animate = true) {
    const active = kindTabs.find(b => b.dataset.kind === kind.value);
    kindTabs.forEach(b => b.setAttribute("aria-pressed", String(b === active)));
    if (!pill) return;
    if (!active) { pill.classList.remove("is-on"); return; }
    const prev = pill.style.transition;
    if (!animate) pill.style.transition = "none";
    pill.style.transform = `translate(${active.offsetLeft}px, ${active.offsetTop - 3}px)`; pill.style.width = `${active.offsetWidth}px`;
    if (!animate) { void pill.offsetWidth; pill.style.transition = prev; }
    pill.classList.add("is-on");
  }
  kindTabs.forEach(b => b.addEventListener("click", () => { kind.value = b.dataset.kind; applyFilter(); }));
  addEventListener("resize", () => paintTabs(false));
  let visible = tiles, shown = PAGE, announceTimer = 0;
  const relayout = () => { if (hasGsap) ScrollTrigger.refresh(); dispatchEvent(new CustomEvent("portfolio:layout")); };
  function paint(fresh = []) {
    visible.forEach((t, i) => { t.classList.toggle("is-beyond", i >= shown); t.classList.remove("is-new"); });
    fresh.forEach((t, i) => { t.classList.add("is-new"); t.style.setProperty("--i", i); });
    const n = Math.min(shown, visible.length);
    more.hidden = n >= visible.length;
    $("shown").textContent = visible.length ? `${n} of ${visible.length} shown` : "";
    relayout();
  }
  function applyFilter(resetPage = true) {
    const q = search.value.trim().toLowerCase(), k = kind.value;
    visible = [];
    for (const t of tiles) {
      const show = (!k || t.dataset.kind === k) && (!q || t.dataset.search.includes(q));
      t.hidden = !show;
      if (show) visible.push(t);
    }
    if (resetPage) shown = PAGE;
    $("count-n").textContent = visible.length;
    $("empty").hidden = visible.length > 0;
    clear.hidden = !search.value;
    resetAll.hidden = !search.value && !k;
    paintTabs();
    paint();
    clearTimeout(announceTimer);
    announceTimer = setTimeout(() => { $("announce").textContent = `${visible.length} of ${total} projects match`; }, 400);
  }
  search.addEventListener("input", () => applyFilter());
  kind.addEventListener("change", () => applyFilter());
  clear.addEventListener("click", () => { search.value = ""; applyFilter(); search.focus(); });
  const resetFilters = () => { search.value = ""; kind.value = ""; applyFilter(); search.focus(); };
  resetAll.addEventListener("click", resetFilters);
  $("reset").addEventListener("click", resetFilters);
  more.addEventListener("click", () => { const first = visible[shown], fresh = visible.slice(shown, shown + PAGE); shown += PAGE; paint(fresh); first?.querySelector("a")?.focus({ preventScroll: true }); });
  const params = new URLSearchParams(location.search);
  if (params.get("q")) search.value = params.get("q");
  if (params.get("kind") && [...kind.options].some(o => o.value === params.get("kind"))) kind.value = params.get("kind");
  applyFilter(); paintTabs(false);

  /* ---- project detail: a dialog filled from the catalogue data, addressable as #<slug>.
     render (show) is separate from history: a click pushes one entry, Previous / Next replace it, popstate only renders. ---- */
  const detail = $("detail");
  let current = null, trigger = null;
  function fill(p) {
    const n = String(p.index + 1).padStart(3, "0");
    $("detail-catalog").textContent = `Project ${n} of ${DATA.length}, ${p.kind}, ${p.date}`;
    $("detail-cover").src = p.slug + "/" + p.cover;
    $("detail-cover").alt = "Screenshot of " + p.title;
    $("detail-title").textContent = p.title;
    $("detail-tagline").textContent = p.tagline || "";
    $("detail-tech").replaceChildren(...(p.tech || []).map(t => Object.assign(document.createElement("li"), { textContent: t })));
    $("detail-open").href = p.slug + "/";
    $("detail-repo").href = p.repo;
    $("detail-demo").hidden = !p.demo;
    if (p.demo) { $("detail-demo").href = /^https?:/.test(p.demo) ? p.demo : p.slug + "/" + p.demo; $("detail-demo").textContent = p.demo_label || "Live demo"; }
    const pos = visible.indexOf(document.querySelector(`.tile[data-slug="${p.slug}"]`));
    $("detail-pos").textContent = pos < 0 ? n : `${pos + 1} / ${visible.length}`;
    $("detail-prev").disabled = pos <= 0;
    $("detail-next").disabled = pos < 0 || pos >= visible.length - 1;
  }
  function show(slug, from = null) {
    const p = bySlug.get(slug);
    if (!p) return false;
    if (!detail.open) trigger = from;
    current = slug;
    fill(p);
    if (!detail.open) { detail.showModal(); settle(detail.querySelector(".detail-body"), { y: 28, s: 0.975 }); peek?.classList.remove("is-on"); }
    $("detail-title").focus({ preventScroll: true });
    return true;
  }
  function open(slug, from) { if (show(slug, from)) history.pushState({ project: slug, pushed: true }, "", "#" + slug); }
  function step(d) {
    const i = visible.indexOf(document.querySelector(`.tile[data-slug="${current}"]`)), t = visible[i + d];
    if (t && show(t.dataset.slug)) history.replaceState({ project: t.dataset.slug, pushed: !!history.state?.pushed }, "", "#" + t.dataset.slug);
  }
  function hide() {
    if (!detail.open) return;
    detail.close();
    current = null;
    const t = trigger?.isConnected && !trigger.closest(".tile")?.hidden ? trigger : search;
    t.focus({ preventScroll: true });
    trigger = null;
  }
  function close() {
    if (!detail.open) return;
    if (history.state?.pushed) { history.back(); return; }
    hide();
    if (location.hash) history.replaceState(null, "", location.pathname + location.search);
  }
  $("tiles").addEventListener("click", e => {
    const t = e.target.closest(".tile");
    if (!t || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    open(t.dataset.slug, t.querySelector("a"));
  });
  addEventListener("portfolio:open", e => open(e.detail.slug, document.querySelector(`.tile[data-slug="${e.detail.slug}"] a`)));   // a screen clicked in the corridor
  $("detail-close").addEventListener("click", close);
  $("detail-prev").addEventListener("click", () => step(-1));
  $("detail-next").addEventListener("click", () => step(1));
  detail.addEventListener("cancel", e => { e.preventDefault(); close(); });
  detail.addEventListener("click", e => { if (e.target === detail) close(); });
  detail.addEventListener("keydown", e => { if (e.key === "ArrowLeft") step(-1); if (e.key === "ArrowRight") step(1); });
  addEventListener("popstate", () => {
    const slug = location.hash.slice(1);
    if (slug && bySlug.has(slug)) show(slug, trigger ?? document.querySelector(`.tile[data-slug="${slug}"] a`));
    else hide();
  });
  const initial = location.hash.slice(1);
  if (initial && bySlug.has(initial)) {
    const tile = document.querySelector(`.tile[data-slug="${initial}"]`);
    const i = visible.indexOf(tile);
    if (i >= shown) { shown = Math.ceil((i + 1) / PAGE) * PAGE; paint(); }
    $("projects").scrollIntoView({ block: "start", behavior: "instant" });
    show(initial, tile?.querySelector("a"));
  }

  /* ---- screenshot viewer for the flagship projects: the real image, full size, original aspect ratio ---- */
  const viewer = $("viewer");
  let viewerTrigger = null;
  document.addEventListener("click", e => {
    const a = e.target.closest("[data-inspect]");
    if (!a || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    const p = bySlug.get(a.dataset.inspect);
    if (!p) return;
    e.preventDefault();
    viewerTrigger = a;
    const img = $("viewer-img");
    img.src = p.slug + "/" + p.cover; img.alt = "Screenshot of " + p.title;
    if (p.size) { img.width = p.size[0]; img.height = p.size[1]; }
    $("viewer-title").textContent = p.title + ", " + p.kind;
    $("viewer-caption").textContent = p.caption || p.tagline || "";
    $("viewer-case").href = p.slug + "/";
    $("viewer-demo").hidden = !p.demo;
    if (p.demo) { $("viewer-demo").href = /^https?:/.test(p.demo) ? p.demo : p.slug + "/" + p.demo; $("viewer-demo").textContent = p.demo_label || "Demo"; }
    const shot = a.querySelector("img");
    const openViewer = () => { viewer.showModal(); $("viewer-close").focus(); };
    if (document.startViewTransition && !reduced() && shot) {
      shot.style.viewTransitionName = "shot";
      const vt = document.startViewTransition(() => { shot.style.viewTransitionName = ""; img.style.viewTransitionName = "shot"; openViewer(); });
      vt.finished.finally(() => { img.style.viewTransitionName = ""; shot.style.viewTransitionName = ""; });
    } else { openViewer(); settle(viewer.querySelector(".viewer-body"), { y: 24, s: 0.98 }); }
  });
  const closeViewer = () => { if (viewer.open) viewer.close(); };
  $("viewer-close").addEventListener("click", closeViewer);
  viewer.addEventListener("cancel", e => { e.preventDefault(); closeViewer(); });
  viewer.addEventListener("click", e => { if (e.target === viewer) closeViewer(); });
  viewer.addEventListener("close", () => { viewerTrigger?.focus({ preventScroll: true }); viewerTrigger = null; });

  /* ---- copy e-mail ---- */
  const copyBtn = $("copy-mail");
  if (navigator.clipboard && copyBtn) {
    copyBtn.hidden = false;
    copyBtn.addEventListener("click", async () => {
      const label = copyBtn.querySelector(".copy-text");
      const swap = text => { copyBtn.classList.add("is-swapping"); setTimeout(() => { label.textContent = text; copyBtn.classList.remove("is-swapping"); }, reduced() ? 0 : 150); };
      try { await navigator.clipboard.writeText(copyBtn.dataset.mail); swap("Copied"); copyBtn.classList.add("is-done"); $("copy-status").textContent = "E-mail address copied"; }
      catch (_) { swap("Copy failed"); $("copy-status").textContent = "Could not copy; the address is the link beside this button"; }
      setTimeout(() => { swap("Copy e-mail"); copyBtn.classList.remove("is-done"); }, 2200);
    });
  }

  /* ---- into a case study: the clicked title and cover fly to the case study's own (cross-document View Transitions;
     browsers without them cut, as before). On the way back the case study's cover lands on its flagship figure. ---- */
  const slugOf = url => { const m = new URL(url, location.href).pathname.match(/\/([^/]+)\/(index\.html)?$/); return m && bySlug.has(m[1]) ? m[1] : null; };
  const nameFor = (slug, apply) => {
    const feat = document.querySelector(`.feature[data-slug="${slug}"]`);
    if (detail.open && current === slug) { apply($("detail-cover"), "cover"); apply($("detail-title"), "title"); }
    else if (viewer.open && $("viewer-case").href.includes(slug + "/")) apply($("viewer-img"), "cover");
    else if (feat) { apply(feat.querySelector(".feature-figure img"), "cover"); apply(feat.querySelector("h3"), "title"); }
  };
  addEventListener("pageswap", e => {
    if (!e.viewTransition || reduced()) return;
    const slug = slugOf(e.activation?.entry?.url || "");
    if (!slug) { e.viewTransition.skipTransition(); return; }
    nameFor(slug, (el, n) => { if (el) el.style.viewTransitionName = n; });
  });
  addEventListener("pagereveal", e => {
    if (!e.viewTransition) return;
    const from = navigation?.activation?.from?.url, slug = from ? slugOf(from) : null;
    if (!slug) return;
    const named = [];
    nameFor(slug, (el, n) => { if (el) { el.style.viewTransitionName = n; named.push(el); } });
    e.viewTransition.finished.finally(() => named.forEach(el => { el.style.viewTransitionName = ""; }));
  });
})();
