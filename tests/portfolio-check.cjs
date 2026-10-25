/* Regression checks for the portfolio home (index.html, THE BLOCK) and the archive (all.html). Run against a local server of the
   built site:   python3 -m http.server 8800 --bind 127.0.0.1 &  NODE_PATH=$(npm root -g) node tests/portfolio-check.cjs
   Covers: both pages without JavaScript (identity, nav, the four panels in featured.json order with their figures and links,
   the check's data, experience and archive line-ups, contact links, every internal link on disk, the poster standing in for
   the object); the opening (html.opening on a first top arrival, the counts rolling to the totals, a wheel skipping it, none
   on a return from a case study or with a hash, none under reduced motion); WebGL on (canvas rendering pixels, the poster
   hidden) and off (the poster shown); the chapter and field colour following scroll; panels toggling is-in; the live fragments
   drawing; the hour input changing the figure and the block; keyboard order, the skip link, the sound toggle, copy e-mail; the
   catalogue's thumbnails, search, filter, reveal, dialog and history; deep links and forwards; overflow at five widths; palette
   contrast from the tokens; console errors. */
const { chromium } = require("playwright");
const fs = require("fs"), path = require("path");
const BASE = process.env.BASE || "http://127.0.0.1:8800/";
const ALL = BASE + "all.html";
const root = path.join(__dirname, "..");
const assert = (ok, msg) => { if (!ok) { console.error("FAIL:", msg); process.exit(1); } console.log("ok:", msg); };
const contrastOf = sels => {
  const lum = c => { const v = c.match(/[\d.]+/g).slice(0, 3).map(x => x / 255).map(x => x <= .03928 ? x / 12.92 : ((x + .055) / 1.055) ** 2.4); return .2126 * v[0] + .7152 * v[1] + .0722 * v[2]; };
  const r = (a, c) => ((Math.max(a, c) + .05) / (Math.min(a, c) + .05));
  const bgOf = el => { for (let e = el; e; e = e.parentElement) { const c = getComputedStyle(e).backgroundColor; if (!/rgba\(0, 0, 0, 0\)|transparent/.test(c) && !/, 0\)$/.test(c)) return c; } return getComputedStyle(document.documentElement).backgroundColor; };
  return sels.map(s => { const el = document.querySelector(s); return [s, el ? r(lum(getComputedStyle(el).color), lum(bgOf(el))).toFixed(2) : "missing"]; });
};

(async () => {
  // the object is a WebGL scene: render it on the machine's GPU (headless Chromium otherwise falls back to SwiftShader). SOFTGL=1 keeps the software renderer.
  const b = await chromium.launch(process.env.SOFTGL ? {} : { args: ["--use-angle=metal", "--ignore-gpu-blocklist"] });
  const errors = [];
  const page = async (opts = {}, init, url = BASE, settle = 1200, waitUntil = "networkidle") => {
    const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, permissions: ["clipboard-write"], ...opts });
    if (init) await ctx.addInitScript(init);
    const p = await ctx.newPage();
    p.on("pageerror", e => errors.push(String(e)));
    p.on("console", m => { if (m.type() === "error" && !/fontshare|ERR_INTERNET|net::/.test(m.text())) errors.push(m.text()); });
    await p.goto(url, { waitUntil });
    await p.waitForTimeout(settle);
    return p;
  };
  const featured = JSON.parse(fs.readFileSync(path.join(root, "featured.json"), "utf8"));
  const slugs = fs.readdirSync(root).filter(d => fs.existsSync(path.join(root, d, "project.json")));
  const gh = JSON.parse(fs.readFileSync(path.join(root, "data", "github.json"), "utf8"));
  const jump = (p, sel, block = "start") => p.evaluate(([s, bl]) => document.querySelector(s).scrollIntoView({ block: bl, behavior: "instant" }), [sel, block]);
  const linksOnDisk = async p => {
    const hrefs = await p.$$eval("a[href]", as => as.map(a => a.getAttribute("href")));
    const internal = hrefs.filter(h => !/^(https?:|mailto:|#)/.test(h));
    const missing = internal.filter(h => { const f = path.join(root, h.split(/[?#]/)[0]); return !(fs.existsSync(f) && (fs.statSync(f).isFile() || fs.existsSync(path.join(f, "index.html")))); });
    return [internal.length, missing];
  };
  const has = (p, c) => p.evaluate(k => document.documentElement.classList.contains(k), c);
  const openingOn = p => p.evaluate(() => typeof gsap !== "undefined" && gsap.globalTimeline.getChildren(false, false, true).some(t => t.duration() > 2 && t.isActive()));
  const counts = p => p.$$eval(".count", es => es.map(e => e.textContent));

  // 1. home without JavaScript: identity, navigation, the panels in order, the check, experience, archive, contact
  let p = await page({ javaScriptEnabled: false }, null, BASE, 0);
  assert(await p.$eval("h1#name", h => /Rishit Raj\s*Mathur/.test(h.textContent) && !!h.closest(".hero#top[data-chapter=hero]")), "the hero carries the name as the one h1");
  assert(await p.$eval(".role-line", e => /Data analyst in Tampa/.test(e.textContent) && /checked against its source/.test(e.textContent)), "the line under the name says what this is");
  assert(await p.$$eval(".lineup", ts => ts.every(t => t.querySelector("thead th[scope=col]"))), "the line-ups are tables with column headers");
  assert(await p.$$eval(".top .links a", as => as.map(a => a.textContent)).then(t => ["Work", "Archive", "Contact", "Résumé"].every(x => t.includes(x))), "nav: Work / Archive / Contact / Résumé");
  assert(await p.evaluate(() => !document.documentElement.classList.contains("js") && getComputedStyle(document.querySelector(".poster")).display !== "none" && getComputedStyle(document.querySelector("canvas.block")).display === "none"), "no-JS: the poster stands in for the object, the canvas is hidden");
  assert(await p.$eval(".poster img", i => i.getAttribute("src")).then(s => s === "assets/block-poster.webp" && fs.existsSync(path.join(root, s))), "the poster image exists");
  const order = await p.$$eval("main [data-chapter]", els => els.map(e => e.dataset.chapter + "#" + e.id));
  assert(JSON.stringify(order) === JSON.stringify(["hero#top", "work#work", "check#check", "experience#experience", "archive#archive", "contact#contact"]), `chapter order: hero > work > check > experience > archive > contact (${order.join(" > ")})`);
  const panels = await p.$$eval(".panel", els => els.map(e => ({ slug: e.dataset.slug, state: e.dataset.state, q: e.querySelector(".q").textContent, fig: (e.querySelector(".fig-v").textContent + e.querySelector(".fig-u").textContent).replace(/\s/g, ""), href: e.querySelector("h3 a").getAttribute("href"), open: e.querySelector(".btns a.fill").getAttribute("href"), canvas: !!e.querySelector(".frag canvas[data-slug]"), still: e.querySelector(".frag img").getAttribute("src"), stillShown: getComputedStyle(e.querySelector(".frag img")).display !== "none", src: e.querySelector(".src").textContent })));
  assert(panels.length === 4 && panels.every((x, i) => x.slug === featured[i].slug && x.state === featured[i].op && x.q === featured[i].card && x.fig === `${featured[i].scale.value}${featured[i].scale.unit}`.replace(/\s/g, "") && x.href === x.slug + "/" && x.open === x.slug + "/" && x.canvas && x.still === x.slug + "/cover-800.webp" && x.stillShown && x.src.includes(featured[i].scale.evidence)), "four panels in featured.json order: operation, question, figure with unit, source line, title and button to the case study, a live canvas with its still shown without JavaScript");
  assert(featured.every(f => fs.existsSync(path.join(root, f.slug, "cover-800.webp")) && fs.existsSync(path.join(root, "motion", "scenes", f.slug + ".js"))), "each flagship has its still and its scene");
  const hours = JSON.parse(await p.$eval("#hours-data", e => e.textContent));
  assert(hours.length === 19 && hours[0].h === 5 && hours[hours.length - 1].h === 23 && hours.every(h => h.otp > 0 && h.otp < 1 && h.n > 0) && Math.abs(hours.find(h => h.h === 6).otp - 0.92) < 0.01 && Math.abs(hours.find(h => h.h === 20).otp - 0.63) < 0.01, "the check carries the published hourly on-time rates (5 a.m. to 11 p.m.; 6 a.m. about 92%, 8 p.m. about 63%)");
  assert(await p.evaluate(() => { const i = document.getElementById("hour"); return i.type === "range" && i.min === "5" && i.max === "23" && document.querySelector("label[for=hour]") !== null && document.getElementById("hour-out").tagName === "OUTPUT"; }), "the hour input is a labelled native range with an output");
  assert(await p.$$eval("#experience .lineup tbody tr", rs => rs.length) === 6 && await p.$eval("#experience", e => /TraceRT/.test(e.textContent) && /22%/.test(e.textContent) && /Power BI Data Analyst Associate/.test(e.textContent) && /REACH Lab/.test(e.textContent)), "experience lists the résumé's roles, certification and degrees");
  const recent = await p.$$eval("#archive .lineup tbody tr", rs => rs.map(r => [r.querySelector("a").getAttribute("href"), r.querySelector("a").textContent]));
  assert(recent.length === 12 && recent.every(([h]) => /\/$/.test(h) && fs.existsSync(path.join(root, h, "index.html"))), "the archive lists twelve case studies that exist");
  assert(await p.$eval("form.query", f => f.getAttribute("action") === "all.html" && f.querySelector("input[name=q]") !== null), "no-JS: the home query form submits to the archive");
  assert(await p.$$eval("a[href$='resume.pdf']", as => as.length) >= 3, "résumé links present (nav, hero, experience, contact)");
  assert(await p.$$eval("a[href^='mailto:rishit.mathur@yahoo.com']", as => as.length) === 1, "verified e-mail link present");
  assert(await p.$eval("a[href*='linkedin.com/in/rishitrajmathur']", a => !!a), "verified LinkedIn link present");
  assert(await p.$$eval("a[href='all.html']", as => as.length) >= 2, "the archive is linked from the nav and the footer");
  assert(await p.evaluate(() => [...document.querySelectorAll("main section")].every(s => s.querySelector("h1, h2"))), "every section has a heading");
  assert(await counts(p).then(c => c.join("/") === `${slugs.length}/${Object.keys(gh).length}`), `no-JS: the counts read ${slugs.length} and ${Object.keys(gh).length} from the data`);
  let [n, missing] = await linksOnDisk(p);
  assert(missing.length === 0, `home: all ${n} internal links resolve on disk` + (missing.length ? ": missing " + missing.join(", ") : ""));
  await p.close();

  // 2. the archive without JavaScript: every project is a real link
  p = await page({ javaScriptEnabled: false }, null, ALL, 0);
  const thumbs = await p.$$eval(".tile", els => els.map(e => { const i = e.querySelector("img.tile-thumb[src]"); return i && [e.dataset.slug, i.getAttribute("src"), i.loading, +i.getAttribute("width")]; }));
  assert(thumbs.every((t, i) => t && t[1] === `assets/thumbs/${t[0]}.webp` && (i < 3 ? t[2] !== "lazy" : t[2] === "lazy") && t[3] === 880 && fs.existsSync(path.join(root, t[1]))), "every archive entry has its own 880px thumbnail (the first row at once, the rest lazy), and the file exists");
  const tiles = await p.$$eval(".tile", els => els.map(e => ({ slug: e.dataset.slug, href: e.querySelector("a").getAttribute("href"), shown: getComputedStyle(e).display !== "none" })));
  assert(tiles.length === slugs.length, `${tiles.length} archive entries rendered for ${slugs.length} project folders`);
  assert(tiles.every(t => t.href === t.slug + "/"), "every archive entry links to its own project folder");
  assert(tiles.every(t => t.shown), "no-JS: the whole archive is visible");
  assert(new Set(tiles.map(t => t.slug)).size === tiles.length, "no duplicate entries");
  [n, missing] = await linksOnDisk(p);
  assert(missing.length === 0, `archive: all ${n} internal links resolve on disk` + (missing.length ? ": missing " + missing.join(", ") : ""));
  await p.close();

  // 3. the opening on a first top arrival: html.opening, the counts roll to the totals, the skip button shows, the object renders
  p = await page({}, null, BASE, 0, "domcontentloaded");
  assert(await has(p, "opening") && await has(p, "js"), "first load: html.opening");
  await p.waitForFunction(() => document.documentElement.classList.contains("gl-on"), null, { timeout: 15000 });
  await p.waitForTimeout(300);
  const mid = await p.evaluate(() => [getComputedStyle(document.getElementById("skip")).opacity, document.querySelector(".count").textContent, getComputedStyle(document.querySelector(".poster")).display]);
  assert(+mid[0] > 0.5 && +mid[1] < slugs.length && mid[2] === "none" && await openingOn(p), `during the opening: the skip button is visible, the count is rolling (${mid[1]}), the poster is gone, the timeline runs`);
  await p.waitForFunction(() => document.documentElement.classList.contains("entered"), null, { timeout: 8000 });
  await p.waitForTimeout(300);
  assert(await counts(p).then(c => c.join("/") === `${slugs.length}/${Object.keys(gh).length}`) && !(await openingOn(p)) && +(await p.$eval("#skip", e => getComputedStyle(e).opacity)) < 0.1, "after the opening: html.entered, the counts land on the totals, the skip button is gone");
  assert(await p.evaluate(() => { const c = document.getElementById("block"); return c.width > 0 && getComputedStyle(c).display !== "none"; }), "the canvas is live");
  await p.addStyleTag({ content: "main, header, footer, .hud-chapter, .skip-intro { visibility: hidden !important; }" }); await p.waitForTimeout(400);
  const shot = (await p.screenshot()).toString("base64");
  const lit = await p.evaluate(async b64 => { const img = new Image(); img.src = "data:image/png;base64," + b64; await img.decode(); const c = document.createElement("canvas"); c.width = img.width; c.height = img.height; const x = c.getContext("2d"); x.drawImage(img, 0, 0); const d = x.getImageData(0, 0, c.width, c.height).data; let n = 0; for (let i = 0; i < d.length; i += 4) if (d[i] > 150 && d[i + 1] > 150 && d[i + 2] > 150) n++; return n / (d.length / 4); }, shot);
  assert(lit > 0.04, `the object renders on the red field: ${(lit * 100).toFixed(1)}% of pixels are the block's paper`);
  await p.evaluate(() => document.querySelectorAll("style").forEach(s => /visibility: hidden !important/.test(s.textContent) && s.remove()));
  assert(await p.$$eval(".frag img", is => is.every(i => getComputedStyle(i).display === "none")), "with JavaScript, the stills give way to the live fragments");
  // 4. the walk: chapter label and field colour per section, panels is-in, the fragments draw, the hour input
  const seen = [];
  for (const id of ["top", "work", "check", "experience", "archive", "contact"]) { await jump(p, "#" + id); await p.waitForTimeout(700); seen.push(await p.evaluate(() => document.documentElement.dataset.pal + ":" + document.getElementById("chapter").textContent)); }
  assert(JSON.stringify(seen) === JSON.stringify(["red:", "paper:Selected work", "red:The check", "paper:Experience", "paper:Archive", "red:Contact"]), `the field colour and the chapter label follow every section (${seen.join(" ")})`);
  for (let i = 0; i < 4; i++) {
    await jump(p, "#feature-" + featured[i].slug); await p.waitForTimeout(1500);
    const [inP, drawn] = await p.evaluate(k => { const ps = [...document.querySelectorAll(".panel")]; const cv = ps[k].querySelector(".frag canvas"); const g = cv.getContext("2d"); const d = g.getImageData(0, 0, cv.width, cv.height).data; let n = 0; for (let j = 0; j < d.length; j += 4 * 97) if (d[j] + d[j + 1] + d[j + 2] > 60) n++; return [ps.map(x => x.classList.contains("is-in")), n]; }, i);
    assert(inP[i] && inP.filter(Boolean).length === 1 && drawn > 0, `panel ${i + 1}: is-in on this panel only (${inP}), its fragment is drawing (${drawn} lit samples)`);
  }
  await jump(p, "#check"); await p.waitForTimeout(500);
  const h8 = await p.$eval("#check-v", e => e.textContent);
  await p.evaluate(() => { const i = document.getElementById("hour"); i.value = "20"; i.dispatchEvent(new Event("input", { bubbles: true })); }); await p.waitForTimeout(100);
  const h20 = await p.evaluate(() => [document.getElementById("check-v").textContent, document.getElementById("hour-out").textContent, document.getElementById("check-n").textContent]);
  assert(h8 === (hours.find(h => h.h === 8).otp * 100).toFixed(1) && h20[0] === (hours.find(h => h.h === 20).otp * 100).toFixed(1) && h20[1] === "8 p.m." && /33,337 flights/.test(h20[2]), `the hour input changes the figure: 8 a.m. ${h8}%, 8 p.m. ${h20[0]}% (${h20[2]})`);
  const snd = [];
  for (let i = 0; i < 2; i++) { await p.click("#sound"); await p.waitForTimeout(150); snd.push(await p.$eval("#sound", b => b.getAttribute("aria-pressed") + "/" + b.textContent.trim())); }
  assert(snd[0] === "true/Sound on" && snd[1] === "false/Sound off", `the sound button toggles aria-pressed and its label (${snd.join(", ")})`);
  await jump(p, "#contact"); await p.waitForTimeout(600);
  assert(await p.evaluate(async () => { const btn = document.getElementById("copy-mail"); if (btn.hidden) return false; btn.click(); await new Promise(r => setTimeout(r, 500)); return btn.textContent.trim() === "Copied" && document.getElementById("copy-status").textContent.length > 0; }), "Copy e-mail copies and confirms");
  await p.close();

  // 5. a wheel during the opening skips it
  p = await page({}, null, BASE, 0, "domcontentloaded");
  await p.waitForFunction(() => document.documentElement.classList.contains("gl-on"), null, { timeout: 15000 }); await p.waitForTimeout(250);
  const before = await openingOn(p);
  await p.mouse.move(720, 450); await p.mouse.wheel(0, 120); await p.waitForTimeout(200);
  const after = await openingOn(p);
  assert(before && !after && await has(p, "entered") && await counts(p).then(c => c[0] === String(slugs.length)), "a wheel during the opening ends it at once: html.entered, the counts land");
  await p.close();

  // 6. a return from a case study (sessionStorage vt), a hash, a second visit: no opening; keyboard order from the top
  p = await page({}, () => { try { sessionStorage.setItem("vt", "retail-dbt"); } catch (_) {} }, BASE, 0, "domcontentloaded");
  assert(!(await has(p, "opening")) && await has(p, "entered"), "coming back from a case study: no opening");
  await p.keyboard.press("Tab");
  assert(await p.evaluate(() => document.activeElement.className === "skip"), "first Tab lands on the skip link");
  await p.keyboard.press("Tab");
  assert(await p.evaluate(() => document.activeElement.textContent === "Work"), "then the nav");
  await p.close();
  p = await page({}, () => { try { sessionStorage.setItem("seen", "1"); } catch (_) {} }, BASE, 0, "domcontentloaded");
  assert(!(await has(p, "opening")), "a second visit in the session: no opening");
  await p.close();
  p = await page({}, null, BASE + "#work", 800, "domcontentloaded");
  assert(!(await has(p, "opening")) && await p.evaluate(() => scrollY > 100 && document.documentElement.dataset.pal === "paper"), "a #work deep link: no opening, lands on the work on the paper field");
  await p.close();

  // 7. reduced motion: no opening, the counts shown final, no running animation, the object still on
  p = await page({ reducedMotion: "reduce" }, null, BASE, 0, "domcontentloaded");
  await p.waitForTimeout(1500);
  const rm = await p.evaluate(() => [document.documentElement.classList.contains("opening"), document.documentElement.classList.contains("entered"), document.documentElement.classList.contains("gl-on"), document.getAnimations().filter(a => a.playState === "running").length, document.querySelector(".count").textContent]);
  assert(!rm[0] && rm[1] && rm[2] && rm[3] === 0 && rm[4] === String(slugs.length), `reduced motion: no opening, entered, the object on, no running animation, the count final (${rm})`);
  await jump(p, "#feature-" + featured[1].slug); await p.waitForTimeout(500);
  assert(await p.$$eval(".panel:nth-of-type(2) .panel-in > *", els => els.every(e => getComputedStyle(e).opacity === "1")), "reduced motion: panel content is visible without entrances");
  await p.close();

  // 8. without WebGL: the poster shows, nothing errors, everything reads
  p = await page({}, null, BASE, 1500, "domcontentloaded");
  await p.close();
  const ctxNoGl = await b.newContext({ viewport: { width: 1440, height: 900 } });
  await ctxNoGl.addInitScript(() => { const g = HTMLCanvasElement.prototype.getContext; HTMLCanvasElement.prototype.getContext = function (t, ...a) { return /webgl/.test(t) ? null : g.call(this, t, ...a); }; });
  const q = await ctxNoGl.newPage(); q.on("pageerror", e => errors.push(String(e))); await q.goto(BASE, { waitUntil: "domcontentloaded" }); await q.waitForTimeout(1500);
  assert(await q.evaluate(() => !document.documentElement.classList.contains("gl-on") && document.documentElement.classList.contains("entered") && getComputedStyle(document.querySelector(".poster")).display !== "none" && document.querySelector(".count").textContent !== "0"), "no WebGL: the poster stays, the page is entered, the counts are final");
  await ctxNoGl.close();

  // contrast from the tokens in home.css
  const css = fs.readFileSync(path.join(root, "home.css"), "utf8");
  const tok = name => { const m = css.match(new RegExp(`--${name}:\\s*([^;]+);`)); return m && m[1].trim(); };
  const rgb = v => [1, 3, 5].map(i => parseInt(v.slice(i, i + 2), 16));
  const L = c => { const v = c.map(x => x / 255).map(x => x <= .03928 ? x / 12.92 : ((x + .055) / 1.055) ** 2.4); return .2126 * v[0] + .7152 * v[1] + .0722 * v[2]; };
  const ratio = (fg, bg) => { const a = L(rgb(tok(fg))), c = L(rgb(tok(bg))); return (Math.max(a, c) + .05) / (Math.min(a, c) + .05); };
  const pairs = [["on-red", "red"], ["ink", "paper"], ["ink", "paper-2"]].map(([f, g]) => [f + " on " + g, ratio(f, g)]);
  assert(pairs.every(([, v]) => v >= 4.5), "every text pairing in the palette clears 4.5:1: " + pairs.map(([k, v]) => k + " " + v.toFixed(2)).join(", "));

  // 9. the archive with JavaScript
  p = await page({}, null, ALL);
  const catContrast = await p.evaluate(contrastOf, [".section-lede", ".tile-kind", ".tile-title", ".tile-gh", ".count", ".kind-tab[aria-pressed=false]", ".view-btn[aria-pressed=false]", ".foot", "#search"]);
  assert(catContrast.every(([, v]) => +v >= 4.5), "archive text clears 4.5:1: " + catContrast.map(x => x.join(" ")).join(", "));
  await p.evaluate(() => scrollTo(0, 400)); await p.waitForTimeout(1200);
  const sharp = await p.$$eval(".tile:not(.is-beyond) img.tile-thumb", is => is.filter(i => i.getBoundingClientRect().top < innerHeight).map(i => [i.complete && i.naturalWidth, i.getBoundingClientRect().width, getComputedStyle(i).filter]));
  assert(sharp.length >= 3 && sharp.every(([nw, w, f]) => nw >= 2 * w - 2 && f === "none"), `archive thumbnails load at 2x their size with no filter (${sharp.map(x => x[0] + "/" + Math.round(x[1])).join(", ")})`);
  await p.evaluate(() => scrollTo(0, 0)); await p.waitForTimeout(300);
  const visibleTiles = () => p.$$eval(".tile", els => els.filter(e => getComputedStyle(e).display !== "none").length);
  const firstShown = await visibleTiles();
  assert(firstShown === 12 && !(await p.$eval("#more", btn => btn.hidden)) && await p.$eval("#shown", e => e.textContent) === `12 of ${slugs.length} shown`, `archive starts with ${firstShown} projects and an accurate count`);
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

  // 10. deep links and old addresses
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
  assert(/all\.html#sec-10k-rag$/.test(p.url()) && await p.evaluate(() => document.getElementById("detail").open), `an old home link #sec-10k-rag forwards to the archive with the project open (${p.url()})`);
  await p.close();
  p = await page({}, null, BASE + "#projects", 1000);
  assert(/all\.html$/.test(p.url()), `the old #projects address forwards to all.html (${p.url()})`);
  await p.close();
  p = await page({}, null, BASE + "?kind=SQL", 1500);
  assert(/all\.html\?kind=SQL$/.test(p.url()) && await p.$eval("#kind", s => s.value) === "SQL" && await p.$$eval(".tile:not([hidden])", els => els.length > 0 && els.every(e => e.dataset.kind === "SQL")), "?kind=SQL forwards to the archive and arrives filtered");
  await p.close();
  p = await page({}, null, BASE + featured[0].slug + "/", 0);
  const nav = await p.$$eval("header.bar nav a", as => as.map(a => a.getAttribute("href")));
  assert(nav.includes("../#feature-" + featured[0].slug) && nav.includes("../all.html"), "a flagship's case study links back to its own panel on the home and to the archive");
  assert(await p.$eval(".facts-strip", d => d.textContent.includes("Commits") && d.textContent.includes("Last push")), "the case study carries the repository facts strip");
  await p.close();
  p = await page({}, null, BASE, 1500, "domcontentloaded");
  await p.click(".panel:nth-of-type(1) h3 a"); await p.waitForLoadState("load"); await p.goBack(); await p.waitForLoadState("load"); await p.waitForTimeout(800);
  assert(/index\.html$|\/$/.test(p.url().split("#")[0]) && await has(p, "entered") && !(await has(p, "opening")), "Back from a case study returns to the home without replaying the opening");
  await p.close();

  // 11. no horizontal overflow at the required breakpoints, on both pages; the phone composition keeps the panel copy on screen
  for (const url of [BASE, ALL]) for (const [w, h] of [[1440, 900], [1280, 720], [768, 1024], [390, 844], [360, 800]]) {
    p = await page({ viewport: { width: w, height: h } }, null, url, 500);
    const sw = await p.evaluate(() => document.documentElement.scrollWidth);
    assert(sw <= w, `${url.endsWith("all.html") ? "archive" : "home"} ${w}x${h}: no horizontal overflow (scrollWidth ${sw})`);
    if (url === BASE && w <= 390) { await jump(p, ".panel:nth-of-type(1)"); await p.waitForTimeout(900);
      const r = await p.$eval(".panel:nth-of-type(1) .btns a.fill", a => { const q = a.getBoundingClientRect(); return [q.top, q.bottom, q.height]; });
      assert(r[0] > 0 && r[1] <= h && r[2] >= 44, `${w}x${h}: the panel's primary button is on screen and at least 44px tall (${r.map(Math.round)})`); }
    await p.close();
  }
  await b.close();
  assert(errors.length === 0, "no console errors or unhandled rejections" + (errors.length ? ": " + errors.join(" | ") : ""));
  console.log("all checks passed");
})().catch(e => { console.error(e); process.exit(1); });
