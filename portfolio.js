/* The portfolio's behaviour (one classic script, no build step).
   Motion: Lenis smooth scroll; the hero's toy blocks (a 72-frame Blender render, tools/blocks.py) stack themselves into a bar
   chart as the hero scrolls; flagship cards stack as you read them; headings and rows rise in once; counters count up; the
   kinds band drifts. Everything that moves is driven by scroll or requestAnimationFrame and stops under reduced motion.
   Behaviour kept from the previous page: the complete catalogue (search, kind filter, twelve at a time, cover previews from
   the atlas, the project dialog on #<slug> with explicit history ownership), the flagship screenshot viewer, copy e-mail,
   and cross-document View Transitions into the case studies. */
(() => {
  "use strict";
  const root = document.documentElement, $ = id => document.getElementById(id);
  const motionQuery = matchMedia("(prefers-reduced-motion: reduce)");
  const reduced = () => motionQuery.matches;
  const fine = matchMedia("(hover: hover) and (pointer: fine)").matches;
  const DATA = JSON.parse($("projects-data").textContent);
  const bySlug = new Map(DATA.map((p, i) => [p.slug, { ...p, index: i }]));
  const ATLAS = JSON.parse(document.body.dataset.atlas);
  root.classList.add(reduced() ? "is-still" : "is-moving");

  /* ---- smooth scroll: Lenis runs its own frame loop (autoRaf); it honours reduced motion by not starting ---- */
  let lenis = null;
  if (typeof Lenis !== "undefined" && !reduced()) {
    lenis = new Lenis({ lerp: 0.12, autoRaf: true, anchors: { offset: -12 } });
    root.classList.add("lenis-on");
  }

  /* ---- one scroll loop for everything scroll-driven ---- */
  const jobs = [];
  let raf = 0;
  const run = () => { raf = 0; for (const j of jobs) j(); };
  const kick = () => { if (!raf) raf = requestAnimationFrame(run); };
  addEventListener("scroll", kick, { passive: true });
  addEventListener("resize", kick);

  /* ---- the hero's blocks: frames load after first paint; scroll through the hero picks the frame ---- */
  const FRAMES = 72, hero = document.querySelector(".hero"), cv = $("blocks"), ctx = cv?.getContext("2d");
  if (reduced()) document.querySelector(".blocks-still").src = "assets/blocks/071.webp";   // still: show the finished chart
  if (cv && ctx && !reduced()) {
    const imgs = Array(FRAMES).fill(null);
    let shown = -1;
    const draw = i => {
      let k = -1;
      for (let d = 0; d < FRAMES && k < 0; d++) k = imgs[i - d] ? i - d : imgs[i + d] ? i + d : -1;
      if (k < 0 || k === shown) return;
      const dpr = Math.min(devicePixelRatio || 1, 2), s = Math.round(cv.clientWidth * dpr);
      if (cv.width !== s) { cv.width = s; cv.height = s; }
      ctx.clearRect(0, 0, s, s); ctx.drawImage(imgs[k], 0, 0, s, s); shown = k;
      root.classList.add("blocks-live");
    };
    jobs.push(() => {
      const r = hero.getBoundingClientRect();
      const p = Math.max(0, Math.min(1, -r.top / Math.max(1, r.height - innerHeight)));
      hero.style.setProperty("--p", p.toFixed(3));
      draw(Math.round(p * (FRAMES - 1)));
    });
    const load = i => new Promise(done => {
      const img = new Image();
      img.onload = () => { imgs[i] = img; if (i === 0 || Math.abs(i - shown) < 6) kick(); done(); };
      img.onerror = done;
      img.src = `assets/blocks/${String(i).padStart(3, "0")}.webp`;
    });
    setTimeout(async () => { await load(0); for (let i = 1; i < FRAMES; i += 8) await Promise.all(Array.from({ length: 8 }, (_, k) => i + k).filter(k => k < FRAMES).map(load)); }, 150);
  }

  /* ---- the blocks come back in About, Experience and Contact: each section's own short sequence (an R, a staircase, "HI")
     builds as the section comes up the screen; frames load only when the section is near ---- */
  if (!reduced()) document.querySelectorAll(".sec-blocks").forEach(fig => {
    const seq = fig.dataset.seq, N = 30, c = fig.querySelector("canvas"), g = c.getContext("2d"), imgs = Array(N).fill(null);
    let shownS = -1, loaded = false;
    const drawS = i => {
      let k = -1;
      for (let d = 0; d < N && k < 0; d++) k = imgs[i - d] ? i - d : imgs[i + d] ? i + d : -1;
      if (k < 0 || k === shownS) return;
      const dpr = Math.min(devicePixelRatio || 1, 2), sz = Math.round(c.clientWidth * dpr);
      if (c.width !== sz) { c.width = sz; c.height = sz; }
      g.clearRect(0, 0, sz, sz); g.drawImage(imgs[k], 0, 0, sz, sz); shownS = k; fig.classList.add("is-live");
    };
    const loadAll = () => { if (loaded) return; loaded = true; for (let i = 0; i < N; i++) { const im = new Image(); im.onload = () => { imgs[i] = im; kick(); }; im.src = `assets/blocks-${seq}/${String(i).padStart(3, "0")}.webp`; } };
    jobs.push(() => {
      const r = fig.getBoundingClientRect();
      if (r.top < innerHeight * 1.6 && r.bottom > -innerHeight) loadAll();
      // from the figure's top entering the screen to its middle reaching the centre
      const p = Math.max(0, Math.min(1, (innerHeight - r.top) / (innerHeight * 0.42)));   // built by the time its top is a little above the middle
      if (loaded) drawS(Math.round(p * (N - 1)));
    });
  });

  /* ---- the sculptures lean toward the pointer, like picking up a toy (fine pointers, motion on) ---- */
  if (fine && !reduced()) {
    let tiltRaf = 0, ex = 0, ey = 0;
    addEventListener("pointermove", e => {
      ex = e.clientX / innerWidth - 0.5; ey = e.clientY / innerHeight - 0.5;
      if (tiltRaf) return;
      tiltRaf = requestAnimationFrame(() => {
        tiltRaf = 0;
        document.querySelectorAll(".blocks, .sec-blocks, .cap-icon").forEach(el => { el.style.transform = `perspective(900px) rotateY(${(ex * 10).toFixed(2)}deg) rotateX(${(-ey * 7).toFixed(2)}deg) translate(${(ex * 10).toFixed(1)}px, ${(ey * 8).toFixed(1)}px)`; });
      });
    }, { passive: true });
  }

  /* ---- phone menu: one row (wordmark + Menu); the links open as a sheet ---- */
  const menuBtn = $("menu-btn"), linksBox = $("nav-links");
  if (menuBtn) {
    const setMenu = open => { menuBtn.setAttribute("aria-expanded", String(open)); document.body.classList.toggle("menu-open", open); menuBtn.textContent = open ? "Close" : "Menu"; };
    menuBtn.addEventListener("click", () => setMenu(menuBtn.getAttribute("aria-expanded") !== "true"));
    linksBox.addEventListener("click", e => { if (e.target.closest("a")) setMenu(false); });
    addEventListener("keydown", e => { if (e.key === "Escape" && document.body.classList.contains("menu-open")) { setMenu(false); menuBtn.focus(); } });
  }

  /* ---- reveals: things rise in once as they enter (opacity and transform only, so controls stay focusable) ---- */
  const revealEls = document.querySelectorAll(".display, .statement-big, .timeline li, .cap-list li, .feature, .about-facts > div, .contact-mail");
  if ("IntersectionObserver" in window && !reduced()) {
    revealEls.forEach(el => el.classList.add("reveal"));
    const io = new IntersectionObserver(es => es.forEach(e => { if (e.isIntersecting) { e.target.classList.add("is-in"); io.unobserve(e.target); } }), { rootMargin: "0px 0px -8% 0px" });
    revealEls.forEach(el => io.observe(el));
  }

  /* ---- flagship figures count up to the value their case study reports, once, when the card arrives ---- */
  const counters = document.querySelectorAll(".reading-value");
  const fmt = (v, unit, dec) => v.toFixed(dec) + unit;
  if ("IntersectionObserver" in window && !reduced()) {
    const io = new IntersectionObserver(es => es.forEach(e => {
      if (!e.isIntersecting) return;
      io.unobserve(e.target);
      const el = e.target, end = +el.dataset.value, unit = el.dataset.unit || "", dec = (String(end).split(".")[1] || "").length, final = el.textContent;
      if (/\bof\b/.test(unit)) return;   // "31 of 31" counted up would read as failing tests on the way
      const t0 = performance.now(), dur = 1100;
      const step = now => { const k = Math.min(1, (now - t0) / dur), ease = 1 - Math.pow(1 - k, 3); el.textContent = k < 1 ? fmt(end * ease, unit, dec) : final; if (k < 1) requestAnimationFrame(step); };
      requestAnimationFrame(step);
    }), { threshold: 0.6 });
    counters.forEach(c => io.observe(c));
  }

  /* ---- nav: a solid bar once the hero has scrolled away; the current section is marked ---- */
  const nav = $("nav"), navLinks = [...document.querySelectorAll(".nav-links a[href^='#']")];
  jobs.push(() => nav.classList.toggle("is-solid", scrollY > innerHeight * 0.6));
  if ("IntersectionObserver" in window) {
    const spy = new IntersectionObserver(es => es.forEach(e => {
      if (!e.isIntersecting) return;
      navLinks.forEach(a => a.toggleAttribute("aria-current", a.hash === "#" + e.target.id));   // sections without a link (hero, capabilities) clear the mark
    }), { rootMargin: "-45% 0px -50% 0px" });
    document.querySelectorAll("main > section[id]").forEach(sec => spy.observe(sec));
  }
  kick();

  /* ---- a numerical spring for direct feedback: dialog panels settle in from below ---- */
  const springs = new WeakMap();
  function settle(el, from) {
    if (reduced()) { el.style.transform = ""; return; }
    const st = springs.get(el) || { y: from.y, s: from.s, vy: 0, vs: 0, raf: 0 };
    if (!springs.has(el)) springs.set(el, st); else { st.y = from.y; st.s = from.s; }
    cancelAnimationFrame(st.raf);
    let last = performance.now();
    const tick = now => {
      const dt = Math.min(0.05, (now - last) / 1000); last = now;
      st.vy += (-260 * st.y - 26 * st.vy) * dt; st.y += st.vy * dt;
      st.vs += (-260 * (st.s - 1) - 26 * st.vs) * dt; st.s += st.vs * dt;
      if (Math.abs(st.y) < 0.2 && Math.abs(st.vy) < 2 && Math.abs(st.s - 1) < 0.002) { el.style.transform = ""; st.raf = 0; return; }
      el.style.transform = `translateY(${st.y.toFixed(2)}px) scale(${st.s.toFixed(4)})`;
      st.raf = requestAnimationFrame(tick);
    };
    st.raf = requestAnimationFrame(tick);
  }

  /* ---- cover previews from the atlas: a card follows the cursor over catalogue entries and capability rows ---- */
  const peek = $("peek"), PW = 256, PH = Math.round(256 * ATLAS.tile[1] / ATLAS.tile[0]);
  const peekAt = w => { if (!w) return; const [a, c, r] = w; peek.style.backgroundImage = `url(assets/wall/atlas-${a}.jpg)`; peek.style.backgroundSize = `${ATLAS.size / ATLAS.tile[0] * PW}px auto`; peek.style.backgroundPosition = `-${c * PW}px -${r * PH}px`; };
  if (fine && peek) {
    let on = null, tx = 0, ty = 0, x = 0, y = 0, prf = 0;
    const follow = () => { x += (tx - x) * 0.22; y += (ty - y) * 0.22; peek.style.transform = `translate(${x}px, ${y}px)`; prf = Math.abs(tx - x) + Math.abs(ty - y) > 0.5 ? requestAnimationFrame(follow) : 0; };
    document.addEventListener("pointermove", e => {
      const t = e.target.closest(".tile, .cap-list li[data-peek]");
      tx = e.clientX + 20; ty = e.clientY - PH / 2;
      if (t !== on) {
        on = t;
        if (t) { const p = bySlug.get(t.dataset.slug || t.dataset.peek); peekAt(p?.w); x = tx; y = ty; peek.classList.add("is-on"); }
        else peek.classList.remove("is-on");
      }
      if (t && !prf) prf = requestAnimationFrame(follow);
    });
    addEventListener("scroll", () => { if (on) { on = null; peek.classList.remove("is-on"); } }, { passive: true });
  }

  /* ---- catalogue thumbnails, cut from the cover atlas (kept out of the HTML so the page arrives light) ---- */
  const [TW, TH] = ATLAS.tile, AS = ATLAS.size;
  const thumbs = () => document.querySelectorAll(".tile:not(.is-beyond):not([hidden]) .tile-thumb:not(.is-set)").forEach(el => {
    const [a, c, r] = el.closest(".tile").dataset.w.split(",").map(Number);
    el.style.setProperty("--thumb", `url(assets/wall/atlas-${a}.jpg)`);
    el.style.setProperty("--thumb-size", `${(AS / TW) * 100}% auto`);
    el.style.setProperty("--thumb-pos", `${(c * TW / (AS - TW)) * 100}% ${(r * TH / (AS - TH)) * 100}%`);
    el.classList.add("is-set");
    shade(el, a, c, r);
  });
  // light screenshots (spreadsheets, white reports) must not be inverted: measure each thumbnail once from its atlas
  const atlasImgs = new Map(), probe = document.createElement("canvas").getContext("2d", { willReadFrequently: true });
  function shade(el, a, c, r) {
    const measure = img => { probe.canvas.width = 8; probe.canvas.height = 5; probe.drawImage(img, c * TW, r * TH, TW, TH, 0, 0, 8, 5);
      const d = probe.getImageData(0, 0, 8, 5).data; let sum = 0; for (let i = 0; i < d.length; i += 4) sum += 0.2126 * d[i] + 0.7152 * d[i + 1] + 0.0722 * d[i + 2];
      el.classList.toggle("is-light", sum / (d.length / 4) > 128); };
    let img = atlasImgs.get(a);
    if (!img) { img = new Image(); img.src = `assets/wall/atlas-${a}.jpg`; atlasImgs.set(a, img); }
    if (img.complete && img.naturalWidth) measure(img); else img.addEventListener("load", () => measure(img), { once: true });
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
    pill.style.transform = `translate(${active.offsetLeft}px, ${active.offsetTop}px)`; pill.style.width = `${active.offsetWidth}px`; pill.style.height = `${active.offsetHeight}px`;
    if (!animate) { void pill.offsetWidth; pill.style.transition = prev; }
    pill.classList.add("is-on");
  }
  kindTabs.forEach(b => b.addEventListener("click", () => { kind.value = b.dataset.kind; applyFilter(); }));
  addEventListener("resize", () => paintTabs(false));
  let visible = tiles, shown = PAGE, announceTimer = 0;
  function paint(fresh = []) {
    visible.forEach((t, i) => { t.classList.toggle("is-beyond", i >= shown); t.classList.remove("is-new"); });
    fresh.forEach((t, i) => { t.classList.add("is-new"); t.style.setProperty("--i", i); });
    const n = Math.min(shown, visible.length);
    more.hidden = n >= visible.length;
    $("shown").textContent = visible.length ? `${n} of ${visible.length} shown` : "";
    thumbs();
    kick();
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
  root.classList.add("catalog-live");
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
    if (!detail.open) { detail.showModal(); settle(detail.querySelector(".detail-body"), { y: 28, s: 0.975 }); peek?.classList.remove("is-on"); lenis?.stop(); }
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
    lenis?.start();
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
    img.src = p.slug + "/" + (p.figure || p.cover); img.alt = "Screenshot of " + p.title;
    if (p.size) { img.width = p.size[0]; img.height = p.size[1]; }
    $("viewer-title").textContent = p.title + ", " + p.kind;
    $("viewer-caption").textContent = p.caption || p.tagline || "";
    $("viewer-case").href = p.slug + "/";
    $("viewer-demo").hidden = !p.demo;
    if (p.demo) { $("viewer-demo").href = /^https?:/.test(p.demo) ? p.demo : p.slug + "/" + p.demo; $("viewer-demo").textContent = p.demo_label || "Demo"; }
    const shot = a.querySelector("img");
    const openViewer = () => { viewer.showModal(); lenis?.stop(); $("viewer-close").focus(); };
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
  viewer.addEventListener("close", () => { lenis?.start(); viewerTrigger?.focus({ preventScroll: true }); viewerTrigger = null; });

  /* ---- copy e-mail ---- */
  const copyBtn = $("copy-mail");
  if (navigator.clipboard && copyBtn) {
    copyBtn.hidden = false;
    copyBtn.addEventListener("click", async () => {
      const label = copyBtn.querySelector(".copy-text");
      try { await navigator.clipboard.writeText(copyBtn.dataset.mail); label.textContent = "Copied"; copyBtn.classList.add("is-done"); $("copy-status").textContent = "E-mail address copied"; }
      catch (_) { label.textContent = "Copy failed"; $("copy-status").textContent = "Could not copy; the address is the link above"; }
      setTimeout(() => { label.textContent = "Copy e-mail"; copyBtn.classList.remove("is-done"); }, 2200);
    });
  }

  /* ---- into a case study: the clicked title and cover fly to the case study's own (cross-document View Transitions) ---- */
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
    const from = typeof navigation !== "undefined" ? navigation.activation?.from?.url : null, slug = from ? slugOf(from) : null;
    if (!slug) return;
    const named = [];
    nameFor(slug, (el, n) => { if (el) { el.style.viewTransitionName = n; named.push(el); } });
    e.viewTransition.finished.finally(() => named.forEach(el => { el.style.viewTransitionName = ""; }));
  });
})();
