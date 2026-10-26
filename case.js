/* Case-study pages: small enhancements on top of plain HTML (every page still works without this file).
   the instrument in the page's own arrangement (loaded after the page, lite quality, a still under reduced motion) ·
   reading progress · section chips that follow the scroll · reveal on scroll · copy buttons on code · click-to-zoom
   figures · sortable result tables · the next project's motion loop playing in its link · the title carried in and
   out by cross-document View Transitions. */
(() => {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];

  // the title travels: in from the home's chapter, out to the next case study
  addEventListener("pageswap", (e) => {
    if (!e.viewTransition || reduce) return;
    const next = document.querySelector(".next-link"), to = e.activation && e.activation.entry && e.activation.entry.url;
    if (next && to && to.startsWith(new URL(next.getAttribute("href"), location.href).href)) { next.querySelector(".t").style.viewTransitionName = "title"; document.querySelector("h1").style.viewTransitionName = ""; }
  });

  // the instrument, in this project's arrangement, once the page has loaded (never before the words)
  const cv = document.querySelector(".case-canvas");
  if (cv && !navigator.connection?.saveData) {
    const start = () => import("../instrument.js").then(async ({ createInstrument, prepareTextures }) => {
      const words = (() => { try { return JSON.parse(cv.dataset.words); } catch (_) { return undefined; } })();
      const state = cv.dataset.config || "open", wide = state === "pipeline" || state === "timeline";
      const texSize = innerWidth <= 760 ? 256 : 384; const textures = await prepareTextures({ texSize, words });
      const inst = createInstrument({ canvas: cv, phone: () => innerWidth <= 760, reduced: reduce, words, quality: "lite", texSize, textures, onReady: () => document.documentElement.classList.add("gl-on") });
      if (!inst) return;
      let t0 = 0; const tick = t => { requestAnimationFrame(tick); if (document.hidden) return; if (!t0) t0 = t;
        const ph = innerWidth <= 760, u = Math.min(1, (t - t0) / 1400);
        inst.update(t, { state: "closed", next: state, u: reduce ? 1 : u, arg: state === "pipeline" ? 31 : state === "documents" ? 1 : undefined, nextArg: state === "pipeline" ? 31 : state === "documents" ? 1 : undefined,
          stage: { x: 0.5, y: 0.5, s: ph ? (wide ? 0.44 : 0.6) : (wide ? 0.78 : 0.95) }, ry: (state === "network" ? -0.2 : -0.45) + (reduce ? 0 : Math.sin(t / 7000) * 0.18), rx: 0.14, ground: -3.1, force: !reduce }); };
      requestAnimationFrame(tick);
    }).catch(() => 0);
    if (document.readyState === "complete") setTimeout(start, 50); else addEventListener("load", () => setTimeout(start, 50));
  }

  // reading progress
  const bar = Object.assign(document.createElement("div"), { className: "progress" });
  document.body.append(bar);
  const doc = document.documentElement;
  const onScroll = () => { bar.style.transform = `scaleX(${doc.scrollTop / Math.max(1, doc.scrollHeight - doc.clientHeight)})`; };
  addEventListener("scroll", onScroll, { passive: true }); onScroll();

  // section chips: jump between sections, the current one lit
  const secs = $$("section.s");
  const toc = Object.assign(document.createElement("nav"), { className: "toc" });
  toc.setAttribute("aria-label", "Sections");
  secs.forEach((s, i) => {
    s.id = s.id || `s${i + 1}`;
    const a = Object.assign(document.createElement("a"), { href: `#${s.id}` });
    a.textContent = s.querySelector("h2").textContent.replace(/^\d+\s*/, "");
    toc.append(a);
  });
  document.body.append(toc);
  const spy = new IntersectionObserver((es) => es.forEach((e) => {
    if (!e.isIntersecting) return;
    $$("a", toc).forEach((a) => a.classList.toggle("on", a.hash === `#${e.target.id}`));
    const on = toc.querySelector("a.on");
    if (on) toc.scrollTo({ left: on.offsetLeft - (toc.clientWidth - on.offsetWidth) / 2, behavior: reduce ? "auto" : "smooth" });
  }), { rootMargin: "-45% 0px -50% 0px" });
  secs.forEach((s) => spy.observe(s));
  const hero = document.querySelector(".case-hero"), tail = document.querySelector(".neighbours");
  const seen = new Map();
  const vis = new IntersectionObserver((es) => { es.forEach((e) => seen.set(e.target, e.isIntersecting)); toc.classList.toggle("show", !seen.get(hero) && !seen.get(tail)); });
  [hero, tail].forEach((el) => el && vis.observe(el));

  // reveal on scroll
  if (!reduce && "IntersectionObserver" in window) {
    const r = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("in"); r.unobserve(e.target); } }), { rootMargin: "0px 0px -8% 0px" });
    $$("section.s, ol.steps > li, .body > img, .body table").forEach((el) => { el.classList.add("rv"); r.observe(el); });
  }

  // copy buttons on code
  $$("pre").forEach((pre) => {
    const b = Object.assign(document.createElement("button"), { className: "copy", type: "button", textContent: "Copy" });
    b.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(pre.querySelector("code")?.textContent ?? pre.textContent); b.textContent = "Copied"; }
      catch { b.textContent = "Select and copy"; }
      setTimeout(() => (b.textContent = "Copy"), 1600);
    });
    pre.append(b);
  });

  // click-to-zoom for the cover and every figure
  const box = Object.assign(document.createElement("dialog"), { className: "zoom" });
  box.innerHTML = '<img alt=""><p></p>';
  document.body.append(box);
  box.addEventListener("click", () => box.close());
  $$(".cover img, .body img").forEach((img) => {
    img.classList.add("zoomable"); img.tabIndex = 0; img.setAttribute("role", "button");
    img.setAttribute("aria-label", `Enlarge: ${img.alt}`);
    const open = () => { const z = box.querySelector("img"); z.src = img.currentSrc || img.src; z.alt = img.alt; box.querySelector("p").textContent = "Click or press Esc to close"; box.showModal(); };
    img.addEventListener("click", open);
    img.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } });
  });

  // sortable tables: click a column header; numbers sort as numbers
  const val = (td) => {
    const t = td.textContent.trim(), m = t.replace(/−/g, "-").replace(/,/g, "").match(/-?\d+(\.\d+)?/);
    return m && /^[\s$−\-+<>~(]*\d/.test(t) ? parseFloat(m[0]) : t.toLowerCase();
  };
  $$(".body table").forEach((table) => {
    const rows = $$("tr", table), head = rows.find((r) => r.querySelector("th"));
    const body = rows.filter((r) => r !== head && !r.querySelector("th"));
    if (!head || body.length < 3) return;
    $$("th", head).forEach((th, col) => {
      if (!th.textContent.trim()) return;
      th.classList.add("sortable"); th.tabIndex = 0; th.title = "Sort";
      const sort = () => {
        const dir = th.getAttribute("aria-sort") === "descending" ? 1 : -1;
        $$("th", head).forEach((o) => o.removeAttribute("aria-sort"));
        th.setAttribute("aria-sort", dir === 1 ? "ascending" : "descending");
        const parent = body[0].parentNode;
        body.sort((a, b) => { const x = val(a.cells[col]), y = val(b.cells[col]); return (typeof x === typeof y ? (x > y ? 1 : x < y ? -1 : 0) : typeof x === "number" ? -1 : 1) * dir; })
            .forEach((r) => parent.append(r));
      };
      th.addEventListener("click", sort);
      th.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); sort(); } });
    });
  });

  // the next project's motion loop plays while its link is on screen
  const peek = document.querySelector(".next-link video");
  if (peek && !reduce) new IntersectionObserver(([e]) => { if (e.isIntersecting) peek.play().catch(() => {}); else peek.pause(); }).observe(peek);
})();
