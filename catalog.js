/* The catalogue page (all.html): every project, twelve at a time, with search, a kind filter (tabs + the full select,
   also from ?q= / ?kind=), and a project dialog addressable as #<slug> with explicit history ownership. Thumbnails are
   plain lazy images (assets/thumbs, tools/thumbs.py). One classic script, no build step. */
(() => {
  "use strict";
  const root = document.documentElement, $ = id => document.getElementById(id);
  const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
  const DATA = JSON.parse($("projects-data").textContent);
  const bySlug = new Map(DATA.map((p, i) => [p.slug, { ...p, index: i }]));
  /* ---- phone menu: one row (wordmark + Menu); the links open as a sheet ---- */
  const menuBtn = $("menu-btn"), linksBox = $("nav-links");
  if (menuBtn) {
    const setMenu = open => { menuBtn.setAttribute("aria-expanded", String(open)); document.body.classList.toggle("menu-open", open); menuBtn.textContent = open ? "Close" : "Menu"; };
    menuBtn.addEventListener("click", () => setMenu(menuBtn.getAttribute("aria-expanded") !== "true"));
    linksBox.addEventListener("click", e => { if (e.target.closest("a")) setMenu(false); });
    addEventListener("keydown", e => { if (e.key === "Escape" && document.body.classList.contains("menu-open")) { setMenu(false); menuBtn.focus(); } });
  }

  /* ---- the nav steps away while scrolling down and returns on any scroll up ---- */
  const nav = $("nav");
  let lastY = scrollY;
  addEventListener("scroll", () => { const y = scrollY; if (Math.abs(y - lastY) > 6) { nav.classList.toggle("is-away", y > lastY && y > 200); lastY = y; } }, { passive: true });

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

  /* ---- thumbnails past the first row get their source after the page has loaded (they are lazy images from then on) ---- */
  let loaded = document.readyState === "complete";
  const thumbs = () => loaded && document.querySelectorAll(".tile:not(.is-beyond):not([hidden]) img[data-src]").forEach(i => { i.src = i.dataset.src; i.removeAttribute("data-src"); });
  addEventListener("load", () => setTimeout(() => { loaded = true; thumbs(); }, 300));

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
  }
  /* the query: free words match title, kind and tools; clauses filter the repository facts:
     language:python  kind:sql  year:2026  commits>10  commits<5  live:yes  (case-insensitive, any order) */
  function parse(q) {
    const words = [], clauses = [];
    for (const tok of q.toLowerCase().split(/\s+/).filter(Boolean)) {
      const m = tok.match(/^(language|lang|kind|year|commits|live)(:|>=|<=|>|<|=)(.+)$/);
      if (m) clauses.push({ key: m[1] === "lang" ? "language" : m[1], op: m[2] === ":" ? "=" : m[2], val: m[3] }); else words.push(tok);
    }
    return { words, clauses };
  }
  const cmp = (a, op, b) => op === "=" ? a === b : op === ">" ? a > b : op === "<" ? a < b : op === ">=" ? a >= b : a <= b;
  function matches(t, { words, clauses }) {
    if (!words.every(w => t.dataset.search.includes(w))) return false;
    return clauses.every(c => {
      if (c.key === "language") return (t.dataset.lang || "").toLowerCase().startsWith(c.val);
      if (c.key === "kind") return (t.dataset.kind || "").toLowerCase().startsWith(c.val);
      if (c.key === "year") return cmp(+t.dataset.year, c.op, +c.val);
      if (c.key === "commits") return cmp(+t.dataset.commits, c.op, +c.val);
      if (c.key === "live") return (t.dataset.live === "1") === /^(y|yes|1|true)$/.test(c.val);
      return true;
    });
  }
  function applyFilter(resetPage = true) {
    const q = search.value.trim(), k = kind.value, parsed = parse(q);
    visible = [];
    for (const t of tiles) {
      const show = (!k || t.dataset.kind === k) && (!q || matches(t, parsed));
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
  /* two views of the same list: covers, or a dense table */
  const tilesEl = $("tiles"), vGrid = $("view-grid"), vTable = $("view-table");
  const setView = table => { tilesEl.classList.toggle("is-table", table); vGrid.setAttribute("aria-pressed", String(!table)); vTable.setAttribute("aria-pressed", String(table)); try { localStorage.setItem("view", table ? "table" : "grid"); } catch (_) {} };
  if (vGrid && vTable) { vGrid.addEventListener("click", () => setView(false)); vTable.addEventListener("click", () => setView(true)); let v = null; try { v = localStorage.getItem("view"); } catch (_) {} if (v === "table") setView(true); }
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
    const g = p.gh; $("detail-gh").textContent = g ? [g.language, `${g.commits} commits`, `last push ${g.pushed}`, g.homepage ? "live site" : ""].filter(Boolean).join(" · ") : "";
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
    if (!detail.open) { detail.showModal(); settle(detail.querySelector(".detail-body"), { y: 28, s: 0.975 }); }
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
    show(initial, tile?.querySelector("a"));
  }

  /* ---- into a case study: the clicked title and cover fly to the case study's own (cross-document View Transitions) ---- */
  const slugOf = url => { const m = new URL(url, location.href).pathname.match(/\/([^/]+)\/(index\.html)?$/); return m && bySlug.has(m[1]) ? m[1] : null; };
  const nameFor = (slug, apply) => {
        if (detail.open && current === slug) { apply($("detail-cover"), "cover"); apply($("detail-title"), "title"); }
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
