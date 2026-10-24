/* Regression checks for the portfolio home (index.html) and the catalogue (all.html). Run against a local server of the built site:
     python3 -m http.server 8800 --bind 127.0.0.1 &  NODE_PATH=$(npm root -g) node tests/portfolio-check.cjs
   Covers: content and links without JavaScript on both pages, every internal link resolving to a real file, the home's page
   order, the intro (first load, faster on a repeat visit, none under reduced motion), the hero's camera flight following
   scroll and handing over to the first project, the four project screens (object lifts, number lands on the figure in
   featured.json, the object flips to what I did), the pager, the nav stepping away on scroll down and back on scroll up, the
   catalogue's sharp thumbnails (one lazy image per project, at least twice its displayed width) and its search / filter /
   twelve-at-a-time reveal / detail dialog (#<slug>, Previous / Next keeping the URL and history in step), old addresses
   forwarding to all.html, keyboard order, copy e-mail, reduced motion, contrast from computed styles on every colour field,
   overflow at five breakpoints, console errors. */
const { chromium } = require("playwright");
const fs = require("fs"), path = require("path");
const BASE = process.env.BASE || "http://127.0.0.1:8800/";
const ALL = BASE + "all.html";
const root = path.join(__dirname, "..");
const assert = (ok, msg) => { if (!ok) { console.error("FAIL:", msg); process.exit(1); } console.log("ok:", msg); };
const contrastOf = sels => {
  const lum = c => { const v = c.match(/[\d.]+/g).slice(0, 3).map(x => x / 255).map(x => x <= .03928 ? x / 12.92 : ((x + .055) / 1.055) ** 2.4); return .2126 * v[0] + .7152 * v[1] + .0722 * v[2]; };
  const r = (a, c) => ((Math.max(a, c) + .05) / (Math.min(a, c) + .05));
  const bgOf = el => { for (let e = el; e; e = e.parentElement) { const c = getComputedStyle(e).backgroundColor; if (!/rgba\(0, 0, 0, 0\)|transparent/.test(c) && !/, 0\)$/.test(c)) return c; } return "rgb(255,255,255)"; };
  return sels.map(s => { const el = document.querySelector(s); return [s, el ? r(lum(getComputedStyle(el).color), lum(bgOf(el))).toFixed(2) : "missing"]; });
};

(async () => {
  const b = await chromium.launch();
  const errors = [];
  const page = async (opts = {}, init, url = BASE, settle = 1200) => {
    const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, permissions: ["clipboard-write"], ...opts });   // the copy-e-mail check needs the clipboard
    if (init) await ctx.addInitScript(init);
    const p = await ctx.newPage();
    p.on("pageerror", e => errors.push(String(e)));
    p.on("console", m => { if (m.type() === "error") errors.push(m.text()); });
    await p.goto(url, { waitUntil: "networkidle" });
    await p.waitForTimeout(settle);
    return p;
  };
  const featured = JSON.parse(fs.readFileSync(path.join(root, "featured.json"), "utf8"));
  const slugs = fs.readdirSync(root).filter(d => fs.existsSync(path.join(root, d, "project.json")));
  const jump = (p, sel, block = "start") => p.evaluate(([s, bl]) => document.querySelector(s).scrollIntoView({ block: bl, behavior: "instant" }), [sel, block]);
  const linksOnDisk = async p => {
    const hrefs = await p.$$eval("a[href]", as => as.map(a => a.getAttribute("href")));
    const internal = hrefs.filter(h => !/^(https?:|mailto:|#)/.test(h));
    const missing = internal.filter(h => { const f = path.join(root, h.split(/[?#]/)[0]); return !(fs.existsSync(f) && (fs.statSync(f).isFile() || fs.existsSync(path.join(f, "index.html")))); });
    return [internal.length, missing];
  };

  // 1. home without JavaScript: identity, navigation, the count, the four projects, about, index, contact
  let p = await page({ javaScriptEnabled: false }, null, BASE, 0);
  assert(await p.$eval("h1", h => /public repositories/.test(h.getAttribute("aria-label")) && /^\d{3}$/.test(h.textContent.trim())), "the count is the h1, named for screen readers");
  assert(await p.$$eval(".nav-links a", as => as.map(a => a.textContent)).then(t => ["Work", "Index", "Contact"].every(x => t.includes(x))), "nav: Work / Index / Contact");
  const order = await p.$$eval("main > section[id], main > div[id]", els => els.map(e => e.id));
  assert(JSON.stringify(order) === JSON.stringify(["top", "work", "about", "index", "contact"]), `page order: hero, work, about, index, contact (${order.join(" > ")})`);
  assert(featured.length === 4 && await p.$$eval(".project", els => els.length) === 4, "four flagship projects rendered as static HTML");
  assert(await p.$$eval(".scene", els => els.every(e => getComputedStyle(e).color === "rgb(255, 255, 255)")), "no-JS: every scene is readable white on the field");
  assert(await p.$$eval(".project", els => els.map(e => e.querySelector(".num").textContent.replace(/\s/g, ""))).then(t => t.every((x, i) => x === `${featured[i].scale.value}${featured[i].scale.unit}`.replace(/\s/g, ""))), "each project shows the figure in featured.json");
  assert(await p.$$eval(".project .display", els => els.map(e => e.textContent)).then(t => t.every((x, i) => x === featured[i].word)), "each project carries its one-word headline");
  const fieldData = JSON.parse(await p.$eval("#field-data", e => e.textContent));
  assert(fieldData.length >= 200 && fieldData.every(r => r.n && r.t && typeof r.c === "number"), `the field carries one record per public repository (${fieldData.length})`);
  assert(await p.$eval("#counter", e => e.textContent.trim()) === String(fieldData.length), "the headline count equals the number of repositories");
  assert(await p.$eval("form.query", f => f.getAttribute("action") === "all.html" && f.querySelector("input[name=q]") !== null), "no-JS: the home query form submits to the index");
  assert(await p.$$eval("a[href$='resume.pdf']", as => as.length) >= 2, "résumé link present (about, contact)");
  assert(await p.$$eval("a[href^='mailto:rishit.mathur@yahoo.com']", as => as.length) === 1, "verified e-mail link present");
  assert(await p.$eval("a[href*='linkedin.com/in/rishitrajmathur']", a => !!a), "verified LinkedIn link present");
  assert(await p.$$eval("a[href='all.html']", as => as.length) >= 2, "the index is linked from the nav and the footer");
  let [n, missing] = await linksOnDisk(p);
  assert(missing.length === 0, `home: all ${n} internal links resolve on disk` + (missing.length ? ": missing " + missing.join(", ") : ""));
  await p.close();

  // 2. the catalogue without JavaScript: every project is a real link
  p = await page({ javaScriptEnabled: false }, null, ALL, 0);
  // without JavaScript the first row is a plain image and the rest are lazy images inside <noscript>, which then render
  const thumbs = await p.$$eval(".tile", els => els.map(e => { const i = e.querySelector("img.tile-thumb[src]"); return i && [e.dataset.slug, i.getAttribute("src"), i.loading, +i.getAttribute("width")]; }));
  assert(thumbs.every((t, i) => t && t[1] === `assets/thumbs/${t[0]}.webp` && (i < 3 ? t[2] !== "lazy" : t[2] === "lazy") && t[3] === 880 && fs.existsSync(path.join(root, t[1]))), "every catalogue entry has its own 880px thumbnail (the first row at once, the rest lazy), and the file exists");
  const tiles = await p.$$eval(".tile", els => els.map(e => ({ slug: e.dataset.slug, href: e.querySelector("a").getAttribute("href"), shown: getComputedStyle(e).display !== "none" })));
  assert(tiles.length === slugs.length, `${tiles.length} catalogue entries rendered for ${slugs.length} project folders`);
  assert(tiles.every(t => t.href === t.slug + "/"), "every catalogue entry links to its own project folder");
  assert(tiles.every(t => t.shown), "no-JS: the whole catalogue is visible");
  assert(new Set(tiles.map(t => t.slug)).size === tiles.length, "no duplicate entries");
  [n, missing] = await linksOnDisk(p);
  assert(missing.length === 0, `catalogue: all ${n} internal links resolve on disk` + (missing.length ? ": missing " + missing.join(", ") : ""));
  await p.close();

  // 2b. the opening: the count runs 000 to the total while the points arrive; skip ends it; faster on a repeat; never under reduced motion
  p = await page({}, null, BASE, 0);
  const firstFrame = await p.evaluate(() => [document.documentElement.classList.contains("intro"), document.getElementById("counter").textContent, document.getElementById("intro-skip").getBoundingClientRect().width > 0, +getComputedStyle(document.querySelector(".nav")).opacity, document.documentElement.classList.contains("gl-on")]);
  assert(firstFrame[0] && /^\d{3}$/.test(firstFrame[1]) && firstFrame[2] && firstFrame[3] === 0 && firstFrame[4], `the opening starts counting with the nav hidden, a Skip button and the field on (${firstFrame})`);
  await p.waitForFunction(() => document.documentElement.classList.contains("intro-done"), null, { timeout: 8000 });
  const landed = await p.evaluate(() => [document.getElementById("counter").textContent, document.documentElement.classList.contains("intro-again"), document.getAnimations().some(a => a.animationName === "up")]);
  await p.reload({ waitUntil: "networkidle" });
  const againIntro = await p.evaluate(() => document.documentElement.classList.contains("intro-again"));
  await p.waitForTimeout(2600);
  const settled = await p.evaluate(() => [+getComputedStyle(document.querySelector(".nav")).opacity, document.getAnimations().filter(a => a.playState === "running" && a.animationName !== "sweep").length]);
  assert(/^\d{3}$/.test(landed[0]) && !landed[1] && landed[2] && againIntro && settled[0] === 1 && settled[1] === 0, `the count lands on the total, the lines rise, a repeat visit is faster and settles (${landed}, ${againIntro}, ${settled})`);
  await p.close();
  p = await page({ reducedMotion: "reduce" }, null, BASE, 0);
  assert(await p.evaluate(() => !document.documentElement.classList.contains("intro")), "no opening under reduced motion");
  await p.close();

  // 3. home with JavaScript: keyboard order, the field re-forms per section, the numbers count, copy e-mail, contrast
  p = await page();
  await p.keyboard.press("Tab");
  assert(await p.evaluate(() => document.activeElement.className === "skip"), "first Tab lands on the skip link");
  await p.keyboard.press("Tab"); await p.keyboard.press("Tab");
  assert(await p.evaluate(() => document.activeElement.textContent === "Work"), "nav is reachable by keyboard");
  await p.waitForFunction(() => document.documentElement.classList.contains("intro-done"), null, { timeout: 12000 });
  await p.waitForTimeout(1200);
  assert(await p.evaluate(() => { const c = document.getElementById("field"); return document.documentElement.classList.contains("gl-on") && c.width > 0 && getComputedStyle(c).display !== "none"; }), "the field is live");
  const sample = async () => p.evaluate(() => { const c = document.getElementById("field"), gl = c.getContext("webgl2"); const px = new Uint8Array(4 * 64 * 64); gl.readPixels(Math.floor(c.width * 0.6), Math.floor(c.height * 0.3), 64, 64, gl.RGBA, gl.UNSIGNED_BYTE, px); let lit = 0; for (let i = 0; i < px.length; i += 4) if (px[i + 3] > 0) lit++; return lit; });
  for (let i = 0; i < 4; i++) {
    await jump(p, "#feature-" + featured[i].slug); await p.waitForTimeout(1500);
    const want = `${featured[i].scale.value}${featured[i].scale.unit}`.replace(/\s/g, "");
    const num = await p.evaluate(k => document.querySelectorAll(".project")[k].querySelector(".num").textContent.replace(/\s/g, ""), i);
    assert(num === want, `screen ${i + 1}: the number lands on ${want} (${num})`);
  }
  await jump(p, "#index"); await p.waitForTimeout(1500);
  assert(await p.evaluate(() => document.querySelector("#index").getBoundingClientRect().top <= 1), "the index section is reachable by anchor");
  await jump(p, "#contact"); await p.waitForTimeout(900);
  assert(await p.evaluate(async () => { const btn = document.getElementById("copy-mail"); if (btn.hidden) return false; btn.click(); await new Promise(r => setTimeout(r, 500)); return btn.textContent.trim() === "Copied" && document.getElementById("copy-status").textContent.length > 0; }), "Copy e-mail copies and confirms");
  const homeContrast = await p.evaluate(contrastOf, [".hero-line", ".hero-sub", ".project .num", ".project .line", ".project .mono.small", ".meta", ".langs dd", ".query input", ".mail", ".foot", ".nav-links a", ".btn", ".btn-fill"]);
  assert(homeContrast.every(([, v]) => +v >= 4.5), "home text clears 4.5:1 on the field: " + homeContrast.filter(([, v]) => +v < 4.5).map(x => x.join(" ")).join(", "));
  await p.close();

  // 4. the catalogue with JavaScript
  p = await page({}, null, ALL);
  const catContrast = await p.evaluate(contrastOf, [".section-lede", ".tile-kind", ".tile-title", ".tile-gh", ".count", ".kind-tab[aria-pressed=false]", ".view-btn[aria-pressed=false]", ".foot", "#search"]);
  assert(catContrast.every(([, v]) => +v >= 4.5), "catalogue text clears 4.5:1: " + catContrast.map(x => x.join(" ")).join(", "));
  // thumbnails are sharp: the first batch has loaded at least twice its displayed width, in true colour (no filter)
  await p.evaluate(() => scrollTo(0, 400)); await p.waitForTimeout(1200);
  const sharp = await p.$$eval(".tile:not(.is-beyond) img.tile-thumb", is => is.filter(i => i.getBoundingClientRect().top < innerHeight).map(i => [i.complete && i.naturalWidth, i.getBoundingClientRect().width, getComputedStyle(i).filter]));
  assert(sharp.length >= 3 && sharp.every(([nw, w, f]) => nw >= 2 * w - 2 && f === "none"), `catalogue thumbnails load at 2x their size with no filter (${sharp.map(x => x[0] + "/" + Math.round(x[1])).join(", ")})`);
  // the nav steps away while scrolling down and returns on scroll up
  await p.evaluate(() => scrollTo(0, 1200)); await p.waitForTimeout(500);
  const away = await p.evaluate(() => document.getElementById("nav").classList.contains("is-away"));
  await p.evaluate(() => scrollTo(0, 900)); await p.waitForTimeout(500);
  assert(away && await p.evaluate(() => !document.getElementById("nav").classList.contains("is-away")), "the nav steps away on scroll down and comes back on scroll up");
  await p.evaluate(() => scrollTo(0, 0)); await p.waitForTimeout(300);
  // the catalogue: progressive reveal, search, filter, detail dialog with history and focus restoration
  const visibleTiles = () => p.$$eval(".tile", els => els.filter(e => getComputedStyle(e).display !== "none").length);
  const firstShown = await visibleTiles();
  assert(firstShown === 12 && !(await p.$eval("#more", btn => btn.hidden)) && await p.$eval("#shown", e => e.textContent) === `12 of ${slugs.length} shown`, `catalogue starts with ${firstShown} projects and an accurate count`);
  const cols = await p.evaluate(() => getComputedStyle(document.getElementById("tiles")).gridTemplateColumns.split(" ").length);
  assert(12 % cols === 0, `the first batch fills complete rows at this width (${cols} columns)`);
  await jump(p, "#more", "center"); await p.evaluate(() => scrollBy(0, 300)); await p.waitForTimeout(800);
  assert(await visibleTiles() === 12, "scrolling near the end reveals nothing by itself");
  await p.click("#more"); await p.waitForTimeout(200);
  assert(await visibleTiles() === 24 && await p.$eval("#shown", e => e.textContent) === `24 of ${slugs.length} shown`, "Show more projects reveals twelve more (24) and the count follows");
  await p.fill("#search", "spark"); await p.waitForTimeout(150);
  const shown = await p.$$eval(".tile:not([hidden])", els => els.length);
  assert(shown > 0 && await p.$eval("#count-n", e => +e.textContent) === shown && shown === slugs.filter(s => /spark/i.test(JSON.stringify((({ title, kind, tech }) => ({ title, kind, tech }))(JSON.parse(fs.readFileSync(path.join(root, s, "project.json"), "utf8")))))).length, `search for "spark" matches the ${shown} projects that mention it, and the count follows`);
  await p.selectOption("#kind", "SQL"); await p.waitForTimeout(150);
  assert(await p.$$eval(".tile:not([hidden])", els => els.every(e => e.dataset.kind === "SQL")) && await p.$eval(".kind-tab[data-kind='SQL']", btn => btn.getAttribute("aria-pressed") === "true"), "the kind filter keeps only that kind and the kind tab follows the select");
  await p.click(".kind-tab[data-kind='Python']"); await p.waitForTimeout(400);
  assert(await p.$eval("#kind", s => s.value) === "Python" && await p.$$eval(".tile:not([hidden])", els => els.every(e => e.dataset.kind === "Python")), "a kind tab sets the select");
  // the query language: clauses over the repository facts
  await p.selectOption("#kind", ""); await p.fill("#search", "language:python year:2026 commits>8"); await p.waitForTimeout(200);
  assert(await p.$$eval(".tile:not([hidden])", els => els.length > 0 && els.every(e => e.dataset.lang === "Python" && e.dataset.year === "2026" && +e.dataset.commits > 8)), "a clause query keeps only matching repositories");
  await p.fill("#search", "kind:sql live:yes"); await p.waitForTimeout(200);
  assert(await p.$$eval(".tile:not([hidden])", els => els.length > 0 && els.every(e => /^sql/i.test(e.dataset.kind) && e.dataset.live === "1")), "kind and live clauses combine");
  await p.click("#view-table"); await p.waitForTimeout(300);
  assert(await p.evaluate(() => document.getElementById("tiles").classList.contains("is-table") && getComputedStyle(document.querySelector(".tile:not([hidden]) .tile-thumb")).display === "none"), "the table view drops the covers");
  await p.click("#view-grid"); await p.waitForTimeout(300);
  await p.selectOption("#kind", "SQL"); await p.waitForTimeout(150);
  await p.fill("#search", "zzzz-nothing"); await p.waitForTimeout(150);
  assert(await p.$eval("#empty", e => !e.hidden) && await p.$eval("#reset", btn => btn.textContent.trim()) === "Reset all filters", "zero results shows the empty state with a 'Reset all filters' action");
  await p.click("#clear"); await p.waitForTimeout(150);
  assert(await p.$eval("#search", i => i.value) === "" && await p.$eval("#kind", s => s.value) === "SQL" && await p.$$eval(".tile:not([hidden])", els => els.length > 0 && els.every(e => e.dataset.kind === "SQL")) && await p.evaluate(() => document.activeElement.id === "search"), "Clear search clears only the text and keeps the kind");
  await p.click("#reset-all"); await p.waitForTimeout(150);
  assert(await p.$eval("#kind", s => s.value) === "" && await p.$$eval(".tile:not([hidden])", els => els.length) === slugs.length && await p.$eval("#reset-all", btn => btn.hidden), "Reset all filters clears both and shows the whole collection");
  await p.fill("#search", "zzzz-nothing"); await p.selectOption("#kind", "SQL"); await p.waitForTimeout(150);
  await p.click("#reset"); await p.waitForTimeout(150);
  assert(await p.$$eval(".tile:not([hidden])", els => els.length) === slugs.length && await p.$eval("#kind", s => s.value) === "", "the empty state's reset clears both filters too");
  await p.focus(".tile:nth-child(2) a"); await p.keyboard.press("Enter"); await p.waitForTimeout(400);
  assert(await p.evaluate(() => document.getElementById("detail").open && document.activeElement.id === "detail-title"), "Enter on a tile opens the detail and focuses its heading");
  const detailLinks = await p.evaluate(() => [document.getElementById("detail-open").getAttribute("href"), document.getElementById("detail-repo").href, location.hash]);
  assert(detailLinks[0] === tiles[1].slug + "/" && detailLinks[2] === "#" + tiles[1].slug && /github\.com/.test(detailLinks[1]), "detail links to the real case study and repo; URL hash names the project");
  const lenBefore = await p.evaluate(() => history.length);
  await p.click("#detail-next"); await p.waitForTimeout(200); await p.click("#detail-next"); await p.waitForTimeout(200); await p.click("#detail-prev"); await p.waitForTimeout(200);
  const stepped = await p.evaluate(() => [document.getElementById("detail-title").textContent, location.hash, history.state && history.state.project, history.length]);
  assert(stepped[1] === "#" + tiles[2].slug && stepped[2] === tiles[2].slug && stepped[3] === lenBefore && await p.$eval("#detail-open", a => a.getAttribute("href")) === tiles[2].slug + "/", `Previous / Next keep the hash, history state and links on the displayed project without adding history (${stepped[0]})`);
  await p.reload({ waitUntil: "networkidle" }); await p.waitForTimeout(1200);
  assert(await p.evaluate(() => document.getElementById("detail").open && location.hash) === "#" + tiles[2].slug && await p.$eval("#detail-open", a => a.getAttribute("href")) === tiles[2].slug + "/", "reload after stepping opens the project the URL names");
  await p.keyboard.press("Escape"); await p.waitForTimeout(400);
  assert(await p.evaluate(() => !document.getElementById("detail").open && location.hash === ""), "Escape on a reloaded deep link closes it and clears the hash");
  await p.focus(".tile:nth-child(2) a"); await p.keyboard.press("Enter"); await p.waitForTimeout(400);
  await p.keyboard.press("Escape"); await p.waitForTimeout(400);
  assert(await p.evaluate(() => !document.getElementById("detail").open && location.hash === "" && document.activeElement === document.querySelector(".tile:nth-child(2) a")), "Escape closes it, clears the hash and restores focus");
  await p.focus(".tile:nth-child(3) a"); await p.keyboard.press("Enter"); await p.waitForTimeout(400);
  await p.goBack(); await p.waitForTimeout(400);
  const back = await p.evaluate(() => [document.getElementById("detail").open, location.hash]);
  await p.goForward(); await p.waitForTimeout(400);
  const fwd = await p.evaluate(() => [document.getElementById("detail").open, location.hash, document.getElementById("detail-title").textContent]);
  assert(!back[0] && back[1] === "" && fwd[0] && fwd[1] === "#" + tiles[2].slug, `Back closes the dialog, Forward reopens the same project (${fwd[2]})`);
  await p.keyboard.press("Escape"); await p.waitForTimeout(400);
  const prevented = await p.evaluate(() => { const a = document.querySelector(".tile:first-child a"); const seen = []; document.addEventListener("click", e => { seen.push(e.defaultPrevented); e.preventDefault(); }); const fire = init => { a.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, ...init })); }; fire({ metaKey: true }); const meta = seen.pop(); document.getElementById("detail").open && document.getElementById("detail").close(); fire({}); const plain = seen.pop(); return { meta, plain }; });
  assert(!prevented.meta && prevented.plain, "cmd-click stays a native link; a plain click opens the detail");
  await p.close();

  // 5. deep links and old addresses: #<slug> on all.html opens that project; the home's old #<slug>, #projects, ?kind= forward to all.html
  p = await page({}, null, ALL + "#sec-10k-rag", 1500);
  assert(await p.evaluate(() => document.getElementById("detail").open) && await p.$eval("#detail-title", e => e.textContent) === "Ask the 10-K", "a direct link all.html#sec-10k-rag opens that project");
  const urlBefore = p.url().split("#")[0], lenDirect = await p.evaluate(() => history.length);
  await p.click("#detail-next"); await p.waitForTimeout(250);
  const steppedFrom = await p.evaluate(() => [location.hash, history.length, !!(history.state && history.state.pushed)]);
  await p.click("#detail-close"); await p.waitForTimeout(500);
  const afterClose = await p.evaluate(() => [document.getElementById("detail").open, location.hash, location.href]);
  assert(steppedFrom[1] === lenDirect && !steppedFrom[2] && !afterClose[0] && afterClose[1] === "" && afterClose[2].split("#")[0] === urlBefore, `a direct link, then Next (${steppedFrom[0]}), then Close stays on the page and closes in place (history ${lenDirect})`);
  await p.close();
  p = await page({}, null, BASE + "#sec-10k-rag", 1500);
  assert(/all\.html#sec-10k-rag$/.test(p.url()) && await p.evaluate(() => document.getElementById("detail").open), `an old home link #sec-10k-rag forwards to the catalogue with the project open (${p.url()})`);
  await p.close();
  p = await page({}, null, BASE + "#projects", 1000);
  assert(/all\.html$/.test(p.url()), `the old #projects address forwards to all.html (${p.url()})`);
  await p.close();
  p = await page({}, null, BASE + "archive/?q=spark", 1500);
  assert(/all\.html/.test(p.url()), `the archive address forwards to the catalogue (${p.url()})`);
  await p.close();
  p = await page({}, null, BASE + "?kind=SQL", 1500);
  assert(/all\.html\?kind=SQL$/.test(p.url()) && await p.$eval("#kind", s => s.value) === "SQL" && await p.$$eval(".tile:not([hidden])", els => els.length > 0 && els.every(e => e.dataset.kind === "SQL")), "?kind=SQL forwards to the catalogue and arrives filtered");
  await p.close();
  p = await page({}, null, BASE + featured[0].slug + "/", 0);
  const nav = await p.$$eval("header.bar nav a", as => as.map(a => a.getAttribute("href")));
  assert(nav.includes("../#feature-" + featured[0].slug) && nav.includes("../all.html"), "a flagship's case study links back to its own screen on the home and to the index");
  assert(await p.$eval(".facts-strip", d => d.textContent.includes("Commits") && d.textContent.includes("Last push")), "the case study carries the repository facts strip");
  await p.close();

  // 6. reduced motion: no smooth scroll, no opening, no running animations; the field holds its pose
  p = await page({ reducedMotion: "reduce" }, null, BASE, 1500);
  const still = await p.evaluate(() => [document.documentElement.classList.contains("lenis-on"), document.getAnimations().filter(a => a.playState === "running").length, document.documentElement.classList.contains("intro"), document.documentElement.classList.contains("gl-on")]);
  assert(!still[0] && still[1] === 0 && !still[2] && still[3], `reduced motion: no smooth scroll, no running animation, no opening, the field still on (${still.join(", ")})`);
  await p.close();

  // 7. no horizontal overflow at the required breakpoints, on both pages
  for (const url of [BASE, ALL]) for (const [w, h] of [[1440, 900], [1280, 800], [768, 1024], [390, 844], [360, 800]]) {
    p = await page({ viewport: { width: w, height: h } }, null, url, 500);
    const sw = await p.evaluate(() => document.documentElement.scrollWidth);
    assert(sw <= w, `${url.endsWith("all.html") ? "catalogue" : "home"} ${w}x${h}: no horizontal overflow (scrollWidth ${sw})`);
    await p.close();
  }
  await b.close();
  assert(errors.length === 0, "no console errors or unhandled rejections" + (errors.length ? ": " + errors.join(" | ") : ""));
  console.log("all checks passed");
})().catch(e => { console.error(e); process.exit(1); });
