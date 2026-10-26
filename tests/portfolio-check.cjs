/* Regression checks for the Precision Atelier portfolio: the home (index.html), the archive (all.html) and every case
   study. Run against a local server of the built site:
     python3 -m http.server 8800 --bind 127.0.0.1 &  NODE_PATH=$(npm root -g) node tests/portfolio-check.cjs
   Covers: the home and the archive without JavaScript (identity, nav, the four chapters in featured.json order with their
   arrangement, figure, definition, marks and links, the hour data, the about line-up, the archive, contact, every internal
   link on disk, the poster standing in for the instrument); the opening (html.opening on a first top arrival, a wheel
   skipping it, none on a return from a case study, with a hash, on a second visit or under reduced motion); WebGL on
   (the canvas rendering champagne pixels, the poster hidden) and off (the poster shown); the ground following the handoff;
   chapters toggling is-in, the evidence fragments drawing, the test counter, the refusal state, the hour input, the
   arrangement controls, pause, sound, copy e-mail; keyboard order and the skip link; every case-study route and its
   required content fields; the case page's instrument, section chips and zoom; the archive's thumbnails, search, filter,
   reveal, dialog and history; deep links and forwards; overflow at five widths on three page types; palette contrast;
   console errors. The suite launches Chromium on the GPU (--use-angle=metal); SOFTGL=1 keeps the software renderer. */
const { chromium } = require("playwright");
const fs = require("fs"), path = require("path");
const BASE = process.env.BASE || "http://127.0.0.1:8800/";
const ALL = BASE + "all.html";
const root = path.join(__dirname, "..");
let passed = 0;
const assert = (ok, msg) => { if (!ok) { console.error("FAIL:", msg); process.exit(1); } passed++; console.log("ok:", msg); };
const contrastOf = sels => {
  const lum = c => { const v = c.match(/[\d.]+/g).slice(0, 3).map(x => x / 255).map(x => x <= .03928 ? x / 12.92 : ((x + .055) / 1.055) ** 2.4); return .2126 * v[0] + .7152 * v[1] + .0722 * v[2]; };
  const r = (a, c) => ((Math.max(a, c) + .05) / (Math.min(a, c) + .05));
  const bgOf = el => { for (let e = el; e; e = e.parentElement) { const c = getComputedStyle(e).backgroundColor; if (!/rgba\(0, 0, 0, 0\)|transparent/.test(c) && !/, 0\)$/.test(c)) return c; } return getComputedStyle(document.documentElement).backgroundColor; };
  return sels.map(s => { const el = document.querySelector(s); return [s, el ? r(lum(getComputedStyle(el).color), lum(bgOf(el))).toFixed(2) : "missing"]; });
};

(async () => {
  const b = await chromium.launch(process.env.SOFTGL ? {} : { args: ["--use-angle=metal", "--ignore-gpu-blocklist"] });
  const errors = [];
  const page = async (opts = {}, init, url = BASE, settle = 1200, waitUntil = "networkidle") => {
    const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, permissions: ["clipboard-write"], ...opts });
    if (init) await ctx.addInitScript(init);
    const p = await ctx.newPage();
    p.on("pageerror", e => errors.push(String(e)));
    p.on("console", m => { if (m.type() === "error" && !/ERR_INTERNET|net::/.test(m.text())) errors.push(m.text()); });
    await p.goto(url, { waitUntil });
    await p.waitForTimeout(settle);
    return p;
  };
  const featured = JSON.parse(fs.readFileSync(path.join(root, "featured.json"), "utf8"));
  const slugs = fs.readdirSync(root).filter(d => fs.existsSync(path.join(root, d, "project.json")));
  const gh = JSON.parse(fs.readFileSync(path.join(root, "data", "github.json"), "utf8"));
  const jump = (p, sel, block = "start") => p.evaluate(([s, bl]) => document.querySelector(s).scrollIntoView({ block: bl, behavior: "instant" }), [sel, block]);
  const scrollChapter = (p, sel, f) => p.evaluate(([s, f]) => { const el = document.querySelector(s); const top = el.getBoundingClientRect().top + scrollY; scrollTo(0, top + Math.max(0, el.offsetHeight - innerHeight) * f); }, [sel, f]);
  const linksOnDisk = async (p, base = root) => {
    const hrefs = await p.$$eval("a[href]", as => as.map(a => a.getAttribute("href")));
    const internal = hrefs.filter(h => !/^(https?:|mailto:|#)/.test(h));
    const missing = internal.filter(h => { const f = path.join(base, h.split(/[?#]/)[0]); return !(fs.existsSync(f) && (fs.statSync(f).isFile() || fs.existsSync(path.join(f, "index.html")))); });
    return [internal.length, missing];
  };
  const has = (p, c) => p.evaluate(k => document.documentElement.classList.contains(k), c);
  const openingOn = p => p.evaluate(() => typeof gsap !== "undefined" && gsap.globalTimeline.getChildren(false, false, true).some(t => t.duration() > 2 && t.isActive()));

  // 1. home without JavaScript: identity, navigation, the four chapters in order, the system, about, archive, contact
  let p = await page({ javaScriptEnabled: false }, null, BASE, 0);
  assert(await p.$eval("h1#name", h => /Built\s*with\s*intent/i.test(h.textContent) && !!h.closest(".hero#top[data-chapter=hero]")), "the hero carries the statement as the one h1");
  assert(await p.$eval(".hero .kicker", e => /Rishit Raj Mathur, data analyst, Tampa/.test(e.textContent)), "the kicker names the owner, the role and the city");
  assert(await p.$eval(".hero .lead", (e, n) => /Data analytics, Python, data engineering, cloud security and AI orchestration/.test(e.textContent) && new RegExp(`${n} case studies`).test(e.textContent), slugs.length), `the lead names the five domains and the count ${slugs.length}`);
  assert(await p.$$eval(".top nav a", as => as.map(a => a.textContent)).then(t => ["Work", "About", "Résumé", "Contact"].every(x => t.includes(x))), "nav: Work / About / Résumé / Contact");
  assert(await p.evaluate(() => !document.documentElement.classList.contains("js") && getComputedStyle(document.querySelector(".poster")).display !== "none" && getComputedStyle(document.querySelector("canvas.instrument")).display === "none"), "no-JS: the poster stands in for the instrument, the canvas is hidden");
  assert(await p.$eval(".poster img", i => i.getAttribute("src")).then(s => s === "assets/atelier-poster.webp" && fs.existsSync(path.join(root, s)) && fs.existsSync(path.join(root, "assets/atelier-poster-m.webp"))), "the posters exist (desktop and phone)");
  const order = await p.$$eval("[data-chapter]", els => els.map(e => e.dataset.chapter + "#" + e.id));
  assert(JSON.stringify(order) === JSON.stringify(["hero#top", "orient#work", ...featured.map((f, i) => `work-${i + 1}#feature-${f.slug}`), "system#system", "about#about", "archive#archive", "contact#contact"]), `chapter order: hero > work > four chapters > system > about > archive > contact (${order.join(" > ")})`);
  const chapters = await p.$$eval(".chapter", els => els.map(e => ({ slug: e.dataset.slug, state: e.dataset.state, title: e.querySelector("h2").textContent, fig: (e.querySelector(".figure b").textContent + e.querySelector(".figure .unit").textContent).replace(/\s/g, ""), def: e.querySelector(".figure .def").textContent, marks: [...e.querySelectorAll(".marks span")].map(s => s.textContent), open: e.querySelector(".btns a.fill").getAttribute("href"), canvas: !!e.querySelector(".evidence canvas[data-slug]"), still: e.querySelector(".evidence img").getAttribute("src"), stillShown: getComputedStyle(e.querySelector(".evidence img")).display !== "none", caption: e.querySelector(".evidence figcaption").textContent })));
  assert(chapters.length === 4 && chapters.every((x, i) => x.slug === featured[i].slug && x.state === featured[i].atelier.state && x.title.includes(JSON.parse(fs.readFileSync(path.join(root, x.slug, "project.json"), "utf8")).title) && x.fig === `${featured[i].scale.value}${featured[i].scale.unit}`.replace(/\s/g, "") && x.def === featured[i].atelier.definition && JSON.stringify(x.marks) === JSON.stringify(featured[i].atelier.marks) && x.open === x.slug + "/" && x.canvas && x.still === x.slug + "/cover-800.webp" && x.stillShown && x.caption === featured[i].caption), "four chapters in featured.json order: arrangement, title, figure with unit, definition, four marks, the button into the case study, a live evidence canvas with its still shown without JavaScript");
  assert(chapters[0].def.includes("arrived within 15 minutes") && !/departures on time|on-time departures/i.test(chapters[0].def + featured[0].scale.metric) && featured[0].scale.metric === "On-time arrivals", "the Florida figure is labelled as arrivals within 15 minutes, never as on-time departures");
  assert(chapters[1].def.includes("as reported in the repository") && chapters[2].def.includes("not a promise") && chapters[3].def.includes("recorded demo"), "the dbt, forecast and 10-K definitions carry their limitations");
  assert(featured.every(f => fs.existsSync(path.join(root, f.slug, "cover-800.webp")) && fs.existsSync(path.join(root, "motion", "scenes", f.slug + ".js"))), "each flagship has its still and its scene");
  const hours = JSON.parse(await p.$eval("#hours-data", e => e.textContent));
  assert(hours.length === 19 && hours[0].h === 5 && hours[hours.length - 1].h === 23 && hours.every(h => h.otp > 0 && h.otp < 1 && h.n > 0) && Math.abs(hours.find(h => h.h === 6).otp - 0.92) < 0.01 && Math.abs(hours.find(h => h.h === 20).otp - 0.63) < 0.01, "the Florida chapter carries the published hourly on-time rates (5 a.m. to 11 p.m.; 6 a.m. about 92%, 8 p.m. about 63%)");
  assert(await p.evaluate(() => { const i = document.getElementById("hour"); return i.type === "range" && i.min === "5" && i.max === "23" && document.querySelector("label[for=hour]") !== null && document.getElementById("hour-out").tagName === "OUTPUT"; }), "the hour input is a labelled native range with an output");
  assert(await p.$$eval("#about .lineup tbody tr", rs => rs.length) === 5 && await p.$eval("#about", e => /TraceRT/.test(e.textContent) && /22%/.test(e.textContent) && /Power BI Data Analyst Associate/.test(e.textContent) && /REACH Lab/.test(e.textContent) && /Expected May 2028/.test(e.textContent)), "about lists the résumé's roles, certification and degrees");
  const recent = await p.$$eval("#archive .lineup tbody tr", rs => rs.map(r => [r.querySelector("a").getAttribute("href"), r.querySelector("a").textContent]));
  assert(recent.length === 12 && recent.every(([h]) => /\/$/.test(h) && fs.existsSync(path.join(root, h, "index.html"))), "the archive lists twelve case studies that exist");
  assert(await p.$eval("form.query", f => f.getAttribute("action") === "all.html" && f.querySelector("input[name=q]") !== null), "no-JS: the home query form submits to the archive");
  assert(await p.$$eval("a[href$='resume.pdf']", as => as.length) >= 2, "résumé links present (nav, about)");
  assert(await p.$$eval("a[href^='mailto:rishit.mathur@yahoo.com']", as => as.length) === 1, "verified e-mail link present");
  assert(await p.$eval("a[href*='linkedin.com/in/rishitrajmathur']", a => !!a), "verified LinkedIn link present");
  assert(await p.$$eval("a[href='all.html']", as => as.length) >= 2, "the archive is linked from the home and the footer");
  assert(await p.evaluate(() => [...document.querySelectorAll("section")].every(s => s.querySelector("h1, h2")) && document.querySelectorAll("h1").length === 1), "every section has a heading; one h1");
  assert(await p.$$eval("[data-config]", bs => bs.map(x => x.dataset.config)).then(c => JSON.stringify(c) === JSON.stringify(["closed", "open", "network", "pipeline", "timeline", "documents"])), "the system chapter offers the six arrangements as buttons");
  let [n, missing] = await linksOnDisk(p);
  assert(missing.length === 0, `home: all ${n} internal links resolve on disk` + (missing.length ? ": missing " + missing.join(", ") : ""));
  const homeContrast = await p.evaluate(contrastOf, [".hero .lead", ".hero .kicker", ".hero .foot-lines", ".figure .def", ".btn.fill", ".controls button", ".marks", ".system .legend"]);
  assert(homeContrast.every(([, v]) => +v >= 4.5), "home text on the green ground clears 4.5:1: " + homeContrast.map(x => x.join(" ")).join(", "));
  await p.close();
  // the posters' pixels: transparent ground, no lab controls in the bottom-left strip, the object present; the same for the six arrangement stills
  const pxPage = await page({}, null, ALL, 0);
  const pix = await pxPage.evaluate(async srcs => { const out = {}; for (const s of srcs) { const img = new Image(); img.src = s; await img.decode(); const c = document.createElement("canvas"); c.width = img.width; c.height = img.height; const g = c.getContext("2d"); g.drawImage(img, 0, 0); const d = g.getImageData(0, 0, c.width, c.height).data; let strip = 0, opaque = 0, corner = 0, blue = 0; for (let y = 0; y < c.height; y += 2) for (let x = 0; x < c.width; x += 2) { const i = (y * c.width + x) * 4, a = d[i + 3]; if (a > 200) opaque++; if (y > c.height * 0.9 && x < c.width * 0.3 && a > 0) strip++; if (y < 40 && x < 40 && a > 0) corner++; if (a > 200 && d[i + 2] > 180 && d[i] < 80) blue++; } out[s] = { w: c.width, h: c.height, strip, opaque, corner, blue, total: Math.ceil(c.width / 2) * Math.ceil(c.height / 2) }; } return out; }, ["assets/atelier-poster.webp", "assets/atelier-poster-m.webp", ...["closed", "open", "network", "pipeline", "timeline", "documents"].map(s => `assets/config-${s}.webp`)]);
  assert(Object.values(pix).every(v => v.strip === 0 && v.corner === 0 && v.blue === 0 && v.opaque > v.total * 0.02 && v.opaque < v.total * 0.6), "posters and arrangement stills: transparent ground, no control strip, no corner artefact, no blue slider pixels, the object present: " + Object.entries(pix).map(([k, v]) => k.replace("assets/", "") + " " + Math.round(100 * v.opaque / v.total) + "%").join(", "));
  assert(pix["assets/atelier-poster.webp"].w === 1440 && pix["assets/atelier-poster-m.webp"].w === 390 && Object.keys(pix).filter(k => /config-/.test(k)).every(k => pix[k].w === 900), "posters are the stage sizes (1440, 390, 900)");
  await pxPage.close();

  // 2. the archive without JavaScript: an editorial index, every project one row with its fields, no thumbnails anywhere
  p = await page({ javaScriptEnabled: false }, null, ALL, 0);
  const tiles = await p.$$eval(".tile", els => els.map(e => ({ slug: e.dataset.slug, href: e.querySelector("a").getAttribute("href"), shown: getComputedStyle(e).display !== "none", no: e.querySelector(".tile-no").textContent, title: e.querySelector(".tile-title").textContent, kind: e.querySelector(".tile-kind").textContent, tools: e.querySelector(".tile-tools").textContent, meta: e.querySelector(".tile-meta").textContent, img: e.querySelectorAll("img").length })));
  assert(tiles.length === slugs.length, `${tiles.length} archive entries rendered for ${slugs.length} project folders`);
  assert(tiles.every(t => t.href === t.slug + "/") && tiles.every(t => t.shown) && new Set(tiles.map(t => t.slug)).size === tiles.length, "every archive entry links to its own project folder, is visible without JavaScript, and is unique");
  assert(tiles.every(t => /^\d{3}$/.test(t.no) && t.title.length > 0 && t.kind.length > 0 && t.tools.length > 0 && /^\d{4} · (Archived|Live demo|Live site|Repository)/.test(t.meta)), "every row carries its number, title, kind, tools, year and status");
  assert(tiles.every(t => t.img === 0) && await p.$$eval("#tiles img, .tile-thumb", es => es.length) === 0, "no thumbnail wall: the index carries no images (the owner's brief forbids a thumbnail wall)");
  assert(await p.$eval(".tile[data-slug='trading-bot'] .tile-meta", e => /Archived/.test(e.textContent)) && await p.$eval(".tile[data-slug='florida-flight-delays'] .tile-meta", e => /Live demo/.test(e.textContent)), "status reflects the project record: trading-bot archived, Florida a live demo");
  [n, missing] = await linksOnDisk(p);
  assert(missing.length === 0, `archive: all ${n} internal links resolve on disk` + (missing.length ? ": missing " + missing.join(", ") : ""));
  await p.close();

  // 3. the opening on a first top arrival: html.opening, the skip control, the timeline, the instrument renders
  p = await page({}, null, BASE, 0, "domcontentloaded");
  assert(await has(p, "opening") && await has(p, "js"), "first load: html.opening");
  assert(await p.$eval("h1#name", h => getComputedStyle(h).opacity === "1"), "the headline is in the first frame (it does not wait for the sequence)");
  await p.waitForFunction(() => document.documentElement.classList.contains("gl-on"), null, { timeout: 15000 });
  await p.waitForTimeout(300);
  const mid = await p.evaluate(() => [getComputedStyle(document.getElementById("skip")).visibility, getComputedStyle(document.querySelector(".poster")).display, getComputedStyle(document.getElementById("replay")).visibility]);
  assert(mid[0] === "visible" && mid[1] === "none" && mid[2] === "hidden" && await openingOn(p), "during the opening: Skip is visible, Replay is not, the poster is gone, the timeline runs");
  const t0 = Date.now();
  await p.waitForFunction(() => document.documentElement.classList.contains("entered"), null, { timeout: 8000 });
  const dur = Date.now() - t0 + 300;
  await p.waitForTimeout(300);
  assert(!(await openingOn(p)) && await p.$eval("#skip", e => getComputedStyle(e).visibility) === "hidden" && await p.$eval("#replay", e => getComputedStyle(e).visibility) === "visible", `after the opening (about ${(dur / 1000).toFixed(1)} s from first render): html.entered, Skip gone, Replay back`);
  assert(await p.evaluate(() => { const c = document.getElementById("instrument"); return c.width > 0 && getComputedStyle(c).display !== "none"; }), "the canvas is live");
  await p.addStyleTag({ content: "main, header, footer, .skip-intro, .reading, .handoff { visibility: hidden !important; }" }); await p.waitForTimeout(400);
  const shot = (await p.screenshot()).toString("base64");
  const lit = await p.evaluate(async b64 => { const img = new Image(); img.src = "data:image/png;base64," + b64; await img.decode(); const c = document.createElement("canvas"); c.width = img.width; c.height = img.height; const x = c.getContext("2d"); x.drawImage(img, 0, 0); const d = x.getImageData(0, 0, c.width, c.height).data; let n = 0; for (let i = 0; i < d.length; i += 4) if (d[i] > 140 && d[i + 1] > 110 && d[i] > d[i + 2] + 30) n++; return n / (d.length / 4); }, shot);
  assert(lit > 0.015, `the instrument renders on the green ground: ${(lit * 100).toFixed(1)}% of pixels are champagne brass`);
  await p.evaluate(() => document.querySelectorAll("style").forEach(s => /visibility: hidden !important/.test(s.textContent) && s.remove()));
  assert(await p.$$eval(".evidence img", is => is.every(i => getComputedStyle(i).display === "none")), "with JavaScript, the stills give way to the live evidence fragments");
  // 4. the walk: the ground follows the handoff, chapters is-in, the fragments draw, the counters, the controls
  const grounds = [];
  for (const id of ["top", "work", "feature-" + featured[0].slug, "system", "about", "archive", "contact"]) { await jump(p, "#" + id); await p.waitForTimeout(700); grounds.push(await p.evaluate(() => document.documentElement.dataset.field)); }
  assert(JSON.stringify(grounds) === JSON.stringify(["green", "green", "green", "green", "ivory", "ivory", "ivory"]), `the ground is green through the instrument's chapters and ivory from About (${grounds.join(" ")})`);
  for (let i = 0; i < 4; i++) {
    await scrollChapter(p, "#feature-" + featured[i].slug, 0.8); await p.waitForTimeout(1600);
    const [inP, drawn] = await p.evaluate(k => { const ps = [...document.querySelectorAll(".chapter")]; const cv = ps[k].querySelector(".evidence canvas"); const g = cv.getContext("2d"); const d = g.getImageData(0, 0, cv.width, cv.height).data; let n = 0; for (let j = 0; j < d.length; j += 4 * 97) if (d[j] + d[j + 1] + d[j + 2] > 60) n++; return [ps.map(x => x.classList.contains("is-in")), n]; }, i);
    assert(inP[i] && inP.filter(Boolean).length === 1 && drawn > 0, `chapter ${i + 1}: is-in on this chapter only (${inP}), its fragment is drawing (${drawn} lit samples)`);
  }
  await scrollChapter(p, "#feature-retail-dbt", 0.95); await p.waitForTimeout(600);
  assert(await p.$eval("#tests-n", e => e.textContent) === "31", "at the end of the dbt chapter all 31 tests are pinned in");
  await scrollChapter(p, "#feature-retail-dbt", 0.35); await p.waitForTimeout(600);
  assert(await p.$eval("#tests-n", e => +e.textContent) < 31, "earlier in the dbt chapter fewer tests are in (the count follows the scroll both ways)");
  await scrollChapter(p, "#feature-sec-10k-rag", 1); await p.waitForTimeout(600);
  assert(await p.$eval("#feature-sec-10k-rag", e => e.classList.contains("refusing")), "the end of the 10-K chapter is the refusal state");
  await jump(p, "#feature-florida-flight-delays"); await p.waitForTimeout(500);
  const h8 = await p.$eval("#hour-v", e => e.textContent);
  await p.evaluate(() => { const i = document.getElementById("hour"); i.value = "20"; i.dispatchEvent(new Event("input", { bubbles: true })); }); await p.waitForTimeout(100);
  const h20 = await p.evaluate(() => [document.getElementById("hour-v").textContent, document.getElementById("hour-out").textContent, document.getElementById("hour-n").textContent]);
  assert(h8 === (hours.find(h => h.h === 8).otp * 100).toFixed(1) && h20[0] === (hours.find(h => h.h === 20).otp * 100).toFixed(1) && h20[1] === "8 p.m." && /33,337 flights/.test(h20[2]), `the hour input changes the figure from the published data: 8 a.m. ${h8}%, 8 p.m. ${h20[0]}% (${h20[2]})`);
  await jump(p, "#system"); await p.waitForTimeout(500);
  await p.click("[data-config=network]"); await p.waitForTimeout(200);
  assert(await p.$$eval("[data-config]", bs => bs.map(x => x.getAttribute("aria-pressed"))).then(a => a.join("") === "falsefalsetruefalsefalsefalse"), "an arrangement button presses itself and releases the others");
  await p.focus("#turn-right"); await p.keyboard.press("ArrowRight"); await p.click("#turn-reset");
  const snd = [];
  for (let i = 0; i < 2; i++) { await p.click("#sound"); await p.waitForTimeout(150); snd.push(await p.$eval("#sound", b => b.getAttribute("aria-pressed") + "/" + b.textContent.trim())); }
  assert(snd[0] === "true/Sound on" && snd[1] === "false/Sound off", `the sound button toggles aria-pressed and its label (${snd.join(", ")})`);
  await p.click("#pause"); await p.waitForTimeout(150);
  const paused = await p.evaluate(() => [document.documentElement.classList.contains("paused"), document.getElementById("pause").getAttribute("aria-pressed"), typeof gsap !== "undefined" && gsap.globalTimeline.paused()]);
  await p.click("#pause"); await p.waitForTimeout(150);
  assert(paused[0] && paused[1] === "true" && paused[2] && !(await has(p, "paused")), "Pause stops the renderer, GSAP and the page's motion classes; Resume restores them");
  await p.close();
  // audio reflects real capability: a context that cannot be created, a resume that is refused, a foreground while paused
  p = await page({}, () => { window.AudioContext = function () { throw new Error("no audio"); }; window.webkitAudioContext = undefined; }, BASE, 0, "domcontentloaded");
  await p.waitForTimeout(400); await p.click("#sound"); await p.waitForTimeout(300);
  assert(await p.evaluate(() => document.getElementById("sound").getAttribute("aria-pressed") === "false" && document.getElementById("sound").textContent.includes("Sound off") && /not available/.test(document.getElementById("copy-status").textContent) && sessionStorage.getItem("sound") !== "1"), "AudioContext creation failing: the control stays off, says so accessibly, stores no preference, throws nothing");
  await p.close();
  p = await page({}, () => { const R = window.AudioContext; window.AudioContext = function () { const c = new R(); c.resume = () => Promise.reject(new Error("denied")); Object.defineProperty(c, "state", { get: () => "suspended" }); return c; }; }, BASE, 0, "domcontentloaded");
  await p.waitForTimeout(400); await p.click("#sound"); await p.waitForTimeout(300);
  assert(await p.evaluate(() => document.getElementById("sound").getAttribute("aria-pressed") === "false" && /could not start/.test(document.getElementById("copy-status").textContent)), "a refused resume: the control stays off and says so");
  await p.close();
  p = await page({}, null, BASE, 0, "domcontentloaded"); await p.waitForTimeout(400);
  await p.click("#sound"); await p.waitForTimeout(300);
  const running = await p.evaluate(() => document.getElementById("sound").getAttribute("aria-pressed") === "true");
  await p.click("#pause"); await p.waitForTimeout(200);
  await p.evaluate(() => { Object.defineProperty(document, "hidden", { get: () => true, configurable: true }); document.dispatchEvent(new Event("visibilitychange")); Object.defineProperty(document, "hidden", { get: () => false, configurable: true }); document.dispatchEvent(new Event("visibilitychange")); }); await p.waitForTimeout(300);
  const whilePaused = await p.evaluate(() => document.documentElement.classList.contains("paused"));
  for (let i = 0; i < 6; i++) { await p.click("#sound"); }
  await p.waitForTimeout(400);
  const afterToggles = await p.evaluate(() => [document.getElementById("sound").getAttribute("aria-pressed"), sessionStorage.getItem("sound")]);
  assert(running && whilePaused && afterToggles[0] === "true" && afterToggles[1] === "1", `sound started on a gesture (${running}); the foreground while paused left the page paused; six rapid toggles end consistent (${afterToggles})`);
  await p.click("#pause");
  await jump(p, "#contact"); await p.waitForTimeout(600);
  assert(await p.evaluate(async () => { const btn = document.getElementById("copy-mail"); if (btn.hidden) return false; btn.click(); await new Promise(r => setTimeout(r, 500)); return btn.textContent.trim() === "Copied" && document.getElementById("copy-status").textContent.length > 0; }), "Copy e-mail copies and confirms");
  await p.close();

  // 5. a wheel during the opening skips it; Replay runs it again
  p = await page({}, null, BASE, 0, "domcontentloaded");
  await p.waitForFunction(() => document.documentElement.classList.contains("gl-on"), null, { timeout: 15000 }); await p.waitForTimeout(250);
  const before = await openingOn(p);
  await p.mouse.move(720, 450); await p.mouse.wheel(0, 120); await p.waitForTimeout(200);
  const after = await openingOn(p);
  assert(before && !after && await has(p, "entered"), "a wheel during the opening ends it at once: html.entered");
  await p.click("#replay"); await p.waitForTimeout(400);
  assert(await has(p, "opening") && await openingOn(p) && await p.evaluate(() => scrollY === 0), "Replay restarts the sequence from the top");
  await p.waitForFunction(() => document.documentElement.classList.contains("entered"), null, { timeout: 8000 });
  await p.close();

  // 6. a return from a case study (sessionStorage vt), a hash, a second visit: no opening; keyboard order from the top
  p = await page({}, () => { try { sessionStorage.setItem("vt", "retail-dbt"); } catch (_) {} }, BASE, 0, "domcontentloaded");
  assert(!(await has(p, "opening")) && await has(p, "entered"), "coming back from a case study: no opening");
  await p.keyboard.press("Tab");
  assert(await p.evaluate(() => document.activeElement.className === "skip"), "first Tab lands on the skip link");
  await p.keyboard.press("Tab"); await p.keyboard.press("Tab");
  assert(await p.evaluate(() => document.activeElement.textContent === "Work"), "then the brand, then the nav");
  await p.close();
  p = await page({}, () => { try { sessionStorage.setItem("seen", "1"); } catch (_) {} }, BASE, 0, "domcontentloaded");
  assert(!(await has(p, "opening")), "a second visit in the session: no opening");
  await p.close();
  p = await page({}, null, BASE + "#about", 1200, "domcontentloaded");
  assert(!(await has(p, "opening")) && await p.evaluate(() => scrollY > 100 && document.documentElement.dataset.field === "ivory"), "an #about deep link: no opening, lands on the ivory ground");
  await p.close();

  // 7. reduced motion: no opening, the instrument still on, no running animation, chapter content visible
  p = await page({ reducedMotion: "reduce" }, null, BASE, 0, "domcontentloaded");
  await p.waitForTimeout(1800);
  const rm = await p.evaluate(() => [document.documentElement.classList.contains("opening"), document.documentElement.classList.contains("entered"), document.documentElement.classList.contains("gl-on"), document.getAnimations().filter(a => a.playState === "running").length]);
  assert(!rm[0] && rm[1] && rm[2] && rm[3] === 0, `reduced motion: no opening, entered, the instrument on, no running animation (${rm})`);
  await scrollChapter(p, "#feature-retail-dbt", 0.5); await p.waitForTimeout(500);
  assert(await p.$$eval("#feature-retail-dbt .text > *", els => els.every(e => getComputedStyle(e).opacity === "1")), "reduced motion: chapter content is visible without entrances");
  await p.close();

  // 8. without WebGL: the poster shows, nothing errors, everything reads
  const ctxNoGl = await b.newContext({ viewport: { width: 1440, height: 900 } });
  await ctxNoGl.addInitScript(() => { const g = HTMLCanvasElement.prototype.getContext; HTMLCanvasElement.prototype.getContext = function (t, ...a) { return /webgl/.test(t) ? null : g.call(this, t, ...a); }; });
  const q = await ctxNoGl.newPage(); q.on("pageerror", e => errors.push(String(e))); await q.goto(BASE, { waitUntil: "domcontentloaded" }); await q.waitForTimeout(1500);
  assert(await q.evaluate(() => !document.documentElement.classList.contains("gl-on") && document.documentElement.classList.contains("entered") && getComputedStyle(document.querySelector(".poster")).display !== "none"), "no WebGL: the poster stays, the page is entered");
  await q.goto(BASE + featured[0].slug + "/", { waitUntil: "load" }); await q.waitForTimeout(800);
  assert(await q.evaluate(() => !document.documentElement.classList.contains("gl-on") && document.querySelector("h1").textContent.length > 0 && document.querySelector(".summary").children.length === 5 && getComputedStyle(document.querySelector(".object-still")).display !== "none" && document.querySelector(".object-still").naturalWidth === 900), "no WebGL on a case study: the words, the summary and the arrangement still stand on their own");
  await ctxNoGl.close();
  const ctxNoMod = await b.newContext({ viewport: { width: 1440, height: 900 } }); const q2 = await ctxNoMod.newPage(); q2.on("pageerror", e => errors.push(String(e))); await q2.route("**/instrument.js*", r => r.abort());
  await q2.goto(BASE + featured[1].slug + "/", { waitUntil: "load" }).catch(() => 0); await q2.waitForTimeout(1200);
  assert(await q2.evaluate(() => !document.documentElement.classList.contains("gl-on") && getComputedStyle(document.querySelector(".object-still")).display !== "none" && document.querySelector(".toc") !== null), "a failed instrument import on a case study: the still stays, the page's own enhancements still run, no unhandled rejection");
  await ctxNoMod.close();

  // 9. every case-study route: the file, one h1, the hero, the instrument, the five summary fields, metadata, neighbours
  const bad = [];
  for (const s of slugs) {
    const f = path.join(root, s, "index.html"); if (!fs.existsSync(f)) { bad.push(s + ": no index.html"); continue; }
    const html = fs.readFileSync(f, "utf8");
    if (s === "trading-bot") { if (!/<h1/.test(html)) bad.push(s + ": frozen page has no h1"); continue; }
    const h1 = (html.match(/<h1[\s>]/g) || []).length, dts = (html.match(/<dt>(Problem|Role|Tools|Status|Evidence)<\/dt>/g) || []).length;
    const next = (html.match(/class="next-link" href="\.\.\/([\w-]+)\/"/) || [])[1], prev = (html.match(/class="prev-link" href="\.\.\/([\w-]+)\/"/) || [])[1];
    if (h1 !== 1) bad.push(s + ": h1 count " + h1);
    if (dts !== 5) bad.push(s + ": summary fields " + dts);
    if (!/class="case-hero/.test(html) || !/case-canvas" data-config="(closed|open|network|pipeline|timeline|documents)"/.test(html)) bad.push(s + ": no hero or instrument");
    if (!/<link rel="canonical"/.test(html) || !/property="og:title"/.test(html) || !/<title>[^<]+<\/title>/.test(html) || !/name="description" content="[^"]+"/.test(html)) bad.push(s + ": metadata");
    if (!next || !prev || !fs.existsSync(path.join(root, next, "index.html")) || !fs.existsSync(path.join(root, prev, "index.html"))) bad.push(s + ": neighbours");
    if (!/atelier\.css/.test(html) || /site\.css|portfolio\.css|home\.css/.test(html)) bad.push(s + ": stylesheet");
    if (!/Code on GitHub/.test(html) || !/class="neighbours"/.test(html) || !/id="problem"/.test(html) || !/id="results"/.test(html)) bad.push(s + ": sections");
  }
  assert(bad.length === 0, `all ${slugs.length} case-study routes exist with one h1, the hero, the instrument, five summary fields, metadata, neighbours and the shared stylesheet (trading-bot frozen by rule)` + (bad.length ? ": " + bad.slice(0, 6).join("; ") : ""));

  // 10. a case study with JavaScript: the instrument comes up, the chips follow, zoom works, the transition hooks exist
  p = await page({}, null, BASE + featured[0].slug + "/", 2500);
  assert(await has(p, "gl-on") && await p.$eval(".case-canvas", c => c.width > 0), "the case page's instrument renders after load");
  const navLinks = await p.$$eval("header.top nav a", as => as.map(a => a.getAttribute("href")));
  assert(navLinks.includes("../#feature-" + featured[0].slug) && navLinks.includes("../all.html"), "a flagship's case study links back to its own chapter on the home and to the archive");
  assert(await p.$eval(".facts-strip", d => d.textContent.includes("Commits") && d.textContent.includes("Last push")), "the case study carries the repository facts strip");
  await jump(p, "#results"); await p.waitForTimeout(900);
  assert(await p.$eval(".toc", t => t.classList.contains("show") && t.querySelector("a.on") && /Results/i.test(t.querySelector("a.on").textContent)), "the section chips show and light the current section");
  await jump(p, ".cover"); await p.waitForTimeout(300); await p.click(".cover img"); await p.waitForTimeout(300);
  assert(await p.evaluate(() => document.querySelector("dialog.zoom").open), "the cover opens in the zoom dialog");
  await p.keyboard.press("Escape");
  const caseContrast = await p.evaluate(contrastOf, [".case-hero .kicker", ".case-hero .tagline", ".summary dd", ".summary dt", ".cover figcaption", "section.s .body", "ol.steps .n", ".facts-strip dt", ".note", ".neighbours .label", ".case-foot"]);
  assert(caseContrast.every(([, v]) => +v >= 4.5), "case-study text clears 4.5:1: " + caseContrast.map(x => x.join(" ")).join(", "));
  [n, missing] = await linksOnDisk(p, path.join(root, featured[0].slug));
  assert(missing.length === 0, `case study: all ${n} internal links resolve on disk` + (missing.length ? ": missing " + missing.join(", ") : ""));
  await p.close();
  p = await page({}, null, BASE, 1500, "domcontentloaded");
  await scrollChapter(p, "#feature-" + featured[0].slug, 0.8); await p.waitForTimeout(800);
  await p.click("#feature-" + featured[0].slug + " .btns a.fill"); await p.waitForLoadState("load"); await p.goBack(); await p.waitForLoadState("load"); await p.waitForTimeout(800);
  assert(/index\.html$|\/$/.test(p.url().split("#")[0]) && await has(p, "entered") && !(await has(p, "opening")), "Back from a case study returns to the home without replaying the opening");
  await p.close();

  // 11. the archive with JavaScript
  p = await page({}, null, ALL);
  const catContrast = await p.evaluate(contrastOf, [".catalog-head .lead", ".tile-kind", ".tile-title", ".tile-tools", ".tile-meta", ".tiles-head", ".count", ".kind-tab[aria-pressed=false]", ".foot", "#search"]);
  assert(catContrast.every(([, v]) => +v >= 4.5), "archive text clears 4.5:1: " + catContrast.map(x => x.join(" ")).join(", "));
  assert(await p.$$eval("#tiles img", es => es.length) === 0 && !(await p.$("#view-grid")), "with JavaScript the index stays an index: no images, no cover view to switch to");
  const visibleTiles = () => p.$$eval(".tile", els => els.filter(e => getComputedStyle(e).display !== "none").length);
  assert(await visibleTiles() === 12 && !(await p.$eval("#more", btn => btn.hidden)) && await p.$eval("#shown", e => e.textContent) === `12 of ${slugs.length} shown`, "archive starts with 12 projects and an accurate count");
  await p.click("#more"); await p.waitForTimeout(200);
  assert(await visibleTiles() === 24, "Show more projects reveals twelve more (24)");
  await p.fill("#search", "spark"); await p.waitForTimeout(150);
  const shown = await p.$$eval(".tile:not([hidden])", els => els.length);
  assert(shown > 0 && await p.$eval("#count-n", e => +e.textContent) === shown && shown === slugs.filter(s => /spark/i.test(JSON.stringify((({ title, kind, tech }) => ({ title, kind, tech }))(JSON.parse(fs.readFileSync(path.join(root, s, "project.json"), "utf8")))))).length, `search for "spark" matches the ${shown} projects that mention it, and the count follows`);
  await p.selectOption("#kind", "SQL"); await p.waitForTimeout(150);
  assert(await p.$$eval(".tile:not([hidden])", els => els.every(e => e.dataset.kind === "SQL")) && await p.$eval(".kind-tab[data-kind='SQL']", btn => btn.getAttribute("aria-pressed") === "true"), "the kind filter keeps only that kind and the kind tab follows the select");
  await p.selectOption("#kind", ""); await p.fill("#search", "language:python year:2026 commits>8"); await p.waitForTimeout(200);
  assert(await p.$$eval(".tile:not([hidden])", els => els.length > 0 && els.every(e => e.dataset.lang === "Python" && e.dataset.year === "2026" && +e.dataset.commits > 8)), "a clause query keeps only matching repositories");
  await p.fill("#search", "zzzz-nothing"); await p.waitForTimeout(150);
  assert(await p.$eval("#empty", e => !e.hidden), "zero results shows the empty state");
  await p.click("#reset"); await p.waitForTimeout(150);
  assert(await p.$$eval(".tile:not([hidden])", els => els.length) === slugs.length, "the empty state's reset shows the whole collection");
  await p.focus(".tile:nth-child(2) a"); await p.keyboard.press("Enter"); await p.waitForTimeout(400);
  assert(await p.evaluate(() => document.getElementById("detail").open && document.activeElement.id === "detail-title" && location.hash === "#" + document.querySelector(".tile:nth-child(2)").dataset.slug), "Enter on a tile opens the detail, focuses its heading and names the project in the hash");
  await p.keyboard.press("Escape"); await p.waitForTimeout(400);
  assert(await p.evaluate(() => !document.getElementById("detail").open && location.hash === "" && document.activeElement === document.querySelector(".tile:nth-child(2) a")), "Escape closes it, clears the hash and restores focus");
  await p.close();

  // 12. deep links and old addresses
  p = await page({}, null, ALL + "#sec-10k-rag", 1500);
  assert(await p.evaluate(() => document.getElementById("detail").open) && await p.$eval("#detail-title", e => e.textContent) === "Ask the 10-K", "a direct link all.html#sec-10k-rag opens that project");
  await p.close();
  p = await page({}, null, BASE + "#sec-10k-rag", 1500);
  assert(/all\.html#sec-10k-rag$/.test(p.url()) && await p.evaluate(() => document.getElementById("detail").open), `an old home link #sec-10k-rag forwards to the archive with the project open`);
  await p.close();
  p = await page({}, null, BASE + "?kind=SQL", 1500);
  assert(/all\.html\?kind=SQL$/.test(p.url()) && await p.$eval("#kind", s => s.value) === "SQL", "?kind=SQL forwards to the archive and arrives filtered");
  await p.close();

  // 13. no horizontal overflow at the required breakpoints on the home, the archive and two case studies; the phone keeps the chapter's primary button on screen
  for (const url of [BASE, ALL, BASE + featured[0].slug + "/", BASE + "workforce-scheduler/"]) for (const [w, h] of [[1440, 900], [1280, 720], [768, 1024], [390, 844], [360, 800]]) {
    p = await page({ viewport: { width: w, height: h } }, null, url, 500);
    const sw = await p.evaluate(() => document.documentElement.scrollWidth);
    assert(sw <= w, `${url.replace(BASE, "/") || "home"} ${w}x${h}: no horizontal overflow (scrollWidth ${sw})`);
    if (url === BASE && w <= 390) { await scrollChapter(p, "#feature-" + featured[0].slug, 0.8); await p.waitForTimeout(900);
      const r = await p.$eval("#feature-" + featured[0].slug + " .btns a.fill", a => { const q = a.getBoundingClientRect(); return [q.top, q.bottom, q.height]; });
      assert(r[0] > 0 && r[1] <= h && r[2] >= 44, `${w}x${h}: the chapter's primary button is on screen and at least 44px tall (${r.map(Math.round)})`); }
    await p.close();
  }
  await b.close();
  assert(errors.length === 0, "no console errors or unhandled rejections" + (errors.length ? ": " + errors.join(" | ") : ""));
  console.log(`all ${passed} checks passed`);
})().catch(e => { console.error(e); process.exit(1); });
