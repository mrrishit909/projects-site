/* Regression checks for the unified portfolio (index.html). Run against a local server of the built site:
     python3 -m http.server 8800 --bind 127.0.0.1 &  NODE_PATH=$(npm root -g) node tests/portfolio-check.cjs
   Covers: content and links without JavaScript, every internal link resolving to a real file, the page order, the complete
   catalogue and its search / filter / twelve-at-a-time reveal / detail dialog (#<slug>, Previous / Next keeping the URL and
   history in step), the screenshot viewer, keyboard order, reduced motion, WebGL unavailable, the slow-renderer hand-off,
   the archive redirect, case-study navigation, contrast from computed styles, overflow at five breakpoints, console errors.
   The corridor (scene.js) is checked through window.__scene: the flight through the corridor chapter, picking a screen,
   the posters when WebGL is unavailable. The intro count and the horizontal flagship track are checked in their own steps. */
const { chromium } = require("playwright");
const fs = require("fs"), path = require("path");
const BASE = process.env.BASE || "http://127.0.0.1:8800/";
const KEEP = BASE + "?scene=keep&intro=off";   // skip the intro (checked once on its own) so every other check starts on the hero
const root = path.join(__dirname, "..");
const assert = (ok, msg) => { if (!ok) { console.error("FAIL:", msg); process.exit(1); } console.log("ok:", msg); };
const GL = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"];

(async () => {
  const b = await chromium.launch({ args: GL });
  const errors = [];
  const page = async (opts = {}, init, url = KEEP, settle = 3500) => {
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

  // 1. without JavaScript: identity, navigation, featured work, the whole catalogue, résumé and contact are plain HTML
  let p = await page({ javaScriptEnabled: false }, null, BASE, 0);
  assert(await p.$eval("h1", h => h.textContent.trim()) === "Rishit Mathur", "name is the h1 without JavaScript");
  assert(await p.$$eval(".nav-links a", as => as.map(a => a.textContent)).then(t => ["Work", "Projects", "About", "Experience", "Résumé", "Contact"].every(x => t.includes(x))), "persistent nav: Work / About / Experience / Projects / Résumé / Contact");
  const order = await p.$$eval("main section[id]", els => els.filter(e => e.tagName === "SECTION" && !e.classList.contains("feature")).map(e => e.id));
  assert(JSON.stringify(order) === JSON.stringify(["top", "corridor", "work", "about", "experience", "capabilities", "projects", "contact"]), `page order: identity, corridor, work, about, experience, capabilities, projects, contact (${order.join(" > ")})`);
  assert(await p.$$eval("#statements li", els => els.length === 3 && els.every(e => getComputedStyle(e).opacity === "1")) && await p.$eval(".reading-world", el => el.classList.contains("paper")), "no-JS: the corridor chapter lists its three statements in plain view; about, experience, capabilities and the collection sit in the paper world");
  assert(await p.$eval("#intro", el => getComputedStyle(el).display === "none") && await p.$eval(".hero-copy", el => getComputedStyle(el).visibility === "visible"), "no-JS: no intro overlay, the hero is simply there");
  assert(featured.length === 4 && await p.$$eval(".feature", els => els.length) === 4, "four flagship projects rendered as static HTML");
  assert(await p.$$eval(".feature-figure img", imgs => imgs.length === 4 && imgs.every(i => getComputedStyle(i.closest("figure")).display !== "none" && i.naturalWidth > 0)), "no-JS: every flagship screenshot is in the page");
  assert(await p.$$eval(".feature .inspect", as => as.every(a => /cover\.jpg$/.test(a.getAttribute("href")) && /Enlarge screenshot/.test(a.getAttribute("aria-label")))), "no-JS: the enlarge control is a real link to the full-size image");
  assert(await p.$eval("#work .eyebrow", h => h.textContent.trim()) === "[ Selected work ]" && await p.$$eval(".feature .reading-value", hs => hs.length === 4 && hs.every(h => /\d/.test(h.textContent))), "'Selected work' section and one prominent qualified figure per flagship");
  assert(await p.$$eval(".feature", els => els.map(e => e.dataset.layout)).then(f => new Set(f).size === 4 && f.every(x => ["wide", "bleed", "left", "stack"].includes(x))), "the four flagship compositions are all different (wide, bleed, left, stack)");
  assert(await p.$$eval(".feature", els => els.every(e => +e.dataset.value >= +e.dataset.min && +e.dataset.value <= +e.dataset.max && e.dataset.metric && /cover\.jpg$/.test(e.dataset.cover))), "every flagship carries its figure, its scale and its screenshot");
  assert(await p.$$eval(".tile", els => els.every(e => /^\d+,\d+,\d+$/.test(e.dataset.w))) && fs.existsSync(path.join(root, "assets", "wall", "atlas-0.jpg")), "every catalogue entry knows its place in the cover atlas, and the atlas files exist");
  assert(await p.$$eval(".foot a", as => as.some(a => a.getAttribute("href") === "#about") && !as.some(a => /mrrishit909\.github\.io\/$/.test(a.href))), "footer links to the integrated About, not a separate site");
  const tiles = await p.$$eval(".tile", els => els.map(e => ({ slug: e.dataset.slug, href: e.querySelector("a").getAttribute("href"), shown: getComputedStyle(e).display !== "none" })));
  assert(tiles.length === slugs.length, `${tiles.length} catalogue entries rendered for ${slugs.length} project folders`);
  assert(tiles.every(t => t.href === t.slug + "/"), "every catalogue entry links to its own project folder");
  assert(tiles.every(t => t.shown), "no-JS: the whole catalogue is visible");
  assert(new Set(tiles.map(t => t.slug)).size === tiles.length, "no duplicate entries");
  assert(await p.$$eval("a[href$='resume.pdf']", as => as.length) >= 2, "résumé link present (nav and contact)");
  assert(await p.$$eval("a[href^='mailto:rishit.mathur@yahoo.com']", as => as.length) === 1, "verified e-mail link present");
  assert(await p.$eval("a[href*='linkedin.com/in/rishitrajmathur']", a => !!a), "verified LinkedIn link present");
  const hrefs = await p.$$eval("a[href]", as => as.map(a => a.getAttribute("href")));
  const internal = hrefs.filter(h => !/^(https?:|mailto:|#)/.test(h));
  const missing = internal.filter(h => { const f = path.join(root, h.split(/[?#]/)[0]); return !(fs.existsSync(f) && (fs.statSync(f).isFile() || fs.existsSync(path.join(f, "index.html")))); });
  assert(missing.length === 0, `all ${internal.length} internal links resolve on disk` + (missing.length ? ": missing " + missing.join(", ") : ""));
  await p.close();

  // 2. with JavaScript: scene live, content visible, motion control, keyboard order, chapters follow scroll
  p = await page();
  assert(await p.evaluate(() => document.documentElement.classList.contains("scene-live") && window.__scene.ready && window.__scene.N === document.querySelectorAll(".tile").length), "WebGL corridor initialises with every cover loaded (headless SwiftShader)");
  assert(await p.evaluate(() => getComputedStyle(document.querySelector(".hero-copy")).visibility === "visible" && document.documentElement.classList.contains("is-ready") && !document.getElementById("motion-toggle").hidden && document.querySelector(".hero h1").textContent === "Rishit Mathur"), "hero copy visible, the motion control is shown, the split name still reads as the name");
  assert(await p.evaluate(() => /Tampa \d\d:\d\d/.test(document.getElementById("nav-clock").textContent)), "the nav carries the live Tampa clock");
  await p.keyboard.press("Tab");
  assert(await p.evaluate(() => document.activeElement.className === "skip"), "first Tab lands on the skip link");
  await p.keyboard.press("Tab"); await p.keyboard.press("Tab");
  assert(await p.evaluate(() => document.activeElement.textContent === "Work"), "nav is reachable by keyboard");
  await p.click("#motion-toggle");
  assert(await p.$eval("#motion-toggle", b => b.getAttribute("aria-pressed") === "true" && b.textContent === "Motion off"), "motion control pauses and reports its state");
  await p.click("#motion-toggle");
  // the corridor: the camera flies through every ring with the chapter's own scroll, the statements take turns, the index counts the screens passed
  const zHero = await p.evaluate(() => window.__scene.z);
  await p.evaluate(() => { const r = document.getElementById("corridor").getBoundingClientRect(); scrollTo(0, r.top + scrollY + (r.height - innerHeight) * 0.5); }); await p.waitForTimeout(2500);
  const mid = await p.evaluate(() => [window.__scene.corridor, window.__scene.z, [...document.querySelectorAll("#statements li")].findIndex(l => l.classList.contains("is-on")), document.getElementById("corridor-n").textContent]);
  await p.evaluate(() => { const r = document.getElementById("corridor").getBoundingClientRect(); scrollTo(0, r.top + scrollY + (r.height - innerHeight) * 0.95); }); await p.waitForTimeout(2500);
  const end = await p.evaluate(() => [window.__scene.corridor, window.__scene.z, [...document.querySelectorAll("#statements li")].findIndex(l => l.classList.contains("is-on")), document.getElementById("corridor-n").textContent]);
  assert(zHero > 0 && Math.abs(mid[0] - 0.5) < 0.03 && mid[1] < zHero - 6 && mid[2] === 1 && end[1] < mid[1] - 4 && end[2] === 2 && +end[3] > +mid[3] && +mid[3] > 0, `the flight: hero z ${zHero.toFixed(1)}, mid-corridor z ${mid[1].toFixed(1)} with statement 2 (${mid[3]} screens), end z ${end[1].toFixed(1)} with statement 3 (${end[3]} screens)`);
  await p.evaluate(() => document.getElementById("experience").scrollIntoView({ block: "start", behavior: "instant" })); await p.waitForTimeout(1500);
  assert(await p.evaluate(() => window.__scene.covered), "the paper world covers the canvas and rendering is suspended there");
  await p.evaluate(() => document.getElementById("contact").scrollIntoView({ block: "start", behavior: "instant" })); await p.waitForTimeout(2500);
  assert(await p.evaluate(() => window.__scene.t > document.querySelectorAll("[data-scene]").length - 1.5 && +getComputedStyle(document.getElementById("scene")).opacity > 0.9), "the contact chapter shows the archive from outside at full opacity");
  await p.evaluate(() => scrollTo(0, 0)); await p.waitForTimeout(2500);
  assert(await p.evaluate(() => window.__scene.t < 0.1 && window.__scene.corridor === 0), "scrolling back up returns the camera to the mouth of the corridor (everything is a function of scroll)");
  // the flagship track: pinned and horizontal at this width; the rail follows; every panel passes through the viewport
  await p.evaluate(() => document.getElementById("work").parentElement.scrollIntoView({ block: "start", behavior: "instant" })); await p.waitForTimeout(1200);
  const trackStart = await p.evaluate(() => [document.documentElement.classList.contains("track-horizontal"), document.getElementById("work").parentElement.classList.contains("pin-spacer"), document.getElementById("rail-no").textContent, Math.round(document.querySelector(".panel-intro").getBoundingClientRect().left)]);
  await p.evaluate(() => { const sp = document.getElementById("work").parentElement; scrollTo(0, sp.offsetTop + sp.offsetHeight - innerHeight); });
  await p.waitForFunction(() => document.querySelectorAll(".feature")[3].querySelector(".feature-copy").getBoundingClientRect().right <= innerWidth, null, { timeout: 8000 }).catch(() => {});   // the scrub catches up in its own time (slow software frames)
  const trackEnd = await p.evaluate(() => { const r = document.querySelectorAll(".feature")[3].querySelector(".feature-copy").getBoundingClientRect(); return [document.getElementById("rail-no").textContent, Math.round(r.left), Math.round(r.right), innerWidth, document.querySelectorAll(".feature")[3].querySelector(".reading-value").textContent]; });
  assert(trackStart[0] && trackStart[1] && trackStart[2] === "00" && trackStart[3] === 0 && trackEnd[0] === "04" && trackEnd[1] >= 0 && trackEnd[2] <= trackEnd[3] && /^20 of 20$/.test(trackEnd[4]), `the flagship track is pinned and scrubbed horizontally: rail 00 at the start, 04 with the fourth flagship fully in view at the end (left ${trackEnd[1]}, right ${trackEnd[2]}, figure "${trackEnd[4]}")`);
  await p.evaluate(() => scrollTo(0, 0)); await p.waitForTimeout(1500);
  // a screen in the corridor can be picked and opened
  const picked = await p.evaluate(() => { for (const [x, y] of [[1300, 200], [1380, 700], [120, 160], [700, 110]]) { const id = window.__scene.pickAt(x, y); if (id >= 0) return id; } return -1; });
  assert(picked >= 0, `a screen under the cursor is picked in the hero (instance ${picked})`);
  await p.evaluate(id => dispatchEvent(new CustomEvent("portfolio:open", { detail: { slug: JSON.parse(document.getElementById("projects-data").textContent)[id].slug } })), picked); await p.waitForTimeout(400);
  assert(await p.evaluate(() => document.getElementById("detail").open && location.hash.length > 1 && history.state && history.state.pushed), "clicking a screen opens its project dialog with one owned history entry");
  await p.keyboard.press("Escape"); await p.waitForTimeout(500);
  assert(await p.evaluate(() => !document.getElementById("detail").open && location.hash === ""), "Escape closes it again and steps back over that entry");
  // the screenshot viewer: opens from the figure, shows the full image, closes on Escape and returns focus
  await p.evaluate(() => document.querySelector(".feature:nth-of-type(1) .inspect").click()); await p.waitForTimeout(500);   // the panel sits in the horizontal track: a synthetic click, the handler is the same
  const viewer = await p.evaluate(() => { const v = document.getElementById("viewer"), i = document.getElementById("viewer-img"); return [v.open, document.activeElement.id, i.getAttribute("src"), i.naturalWidth > 1000, i.getBoundingClientRect().width > 900, document.getElementById("viewer-caption").textContent.length > 20, document.getElementById("viewer-case").getAttribute("href")]; });
  assert(viewer[0] && viewer[1] === "viewer-close" && /florida-flight-delays\/cover\.jpg/.test(viewer[2]) && viewer[3] && viewer[4] && viewer[5] && viewer[6] === "florida-flight-delays/", `screenshot viewer opens with the full image, a caption and the case-study link (${JSON.stringify(viewer)})`);
  await p.keyboard.press("Escape"); await p.waitForTimeout(300);
  assert(await p.evaluate(() => !document.getElementById("viewer").open && document.activeElement === document.querySelector(".feature:nth-of-type(1) .inspect") && location.hash === ""), "Escape closes the viewer, focus returns to the enlarge control, the URL is untouched");
  const contrast = await p.evaluate(() => {
    const lum = c => { const v = c.match(/[\d.]+/g).slice(0, 3).map(x => x / 255).map(x => x <= .03928 ? x / 12.92 : ((x + .055) / 1.055) ** 2.4); return .2126 * v[0] + .7152 * v[1] + .0722 * v[2]; };
    const ink = lum(getComputedStyle(document.body).backgroundColor), paper = lum(getComputedStyle(document.querySelector(".reading-world")).backgroundColor);
    const r = (fg, b) => ((Math.max(fg, b) + .05) / (Math.min(fg, b) + .05));
    const dark = [".nav-links a", ".nav-clock", ".hero .eyebrow", ".lede", ".hero-aside", ".scroll-hint", ".marquee-set", ".statement p", ".step-no", ".corridor-hint", ".reading-label", ".facts dt", ".tools li", ".feature-figure figcaption", ".feature-meta", ".panel-intro .section-lede", ".track-rail", ".contact-link", ".copy-mail", ".contact-note", ".foot"];
    const light = [".about .eyebrow", ".about-facts dt", ".tl-when", ".timeline p", ".cap-list p", ".tile-kind", ".tile-no", ".count", ".kind-tab", ".field-label", ".catalog .section-lede"];
    const sample = (s, bg) => { const el = document.querySelector(s); const c = getComputedStyle(el).color; return [s, r(lum(c), bg).toFixed(2)]; };
    return [...dark.map(s => sample(s, ink)), ...light.map(s => sample(s, paper))];
  });
  assert(contrast.every(([, r]) => +r >= 4.5), "sampled text clears 4.5:1 on its own world (charcoal or limestone): " + contrast.map(x => x.join(" ")).join(", "));
  // cover previews: hovering an entry shows its cover from the atlas, no request per project
  await p.evaluate(() => document.getElementById("projects").scrollIntoView({ block: "start", behavior: "instant" })); await p.waitForTimeout(600);
  await p.hover(".tile:nth-child(3) a"); await p.waitForTimeout(300);
  assert(await p.evaluate(() => { const k = document.getElementById("peek"); return k.classList.contains("is-on") && /atlas-\d\.jpg/.test(k.style.backgroundImage); }), "hovering a catalogue entry floats its cover, cut from the atlas");
  await p.mouse.move(10, 10); await p.waitForTimeout(300);
  assert(await p.evaluate(() => !document.getElementById("peek").classList.contains("is-on")), "the preview leaves with the cursor");
  // the catalogue: progressive reveal, search, filter, detail dialog with history and focus restoration
  await p.evaluate(() => document.getElementById("projects").scrollIntoView({ block: "start", behavior: "instant" })); await p.waitForTimeout(600);
  const visibleTiles = () => p.$$eval(".tile", els => els.filter(e => getComputedStyle(e).display !== "none").length);
  const firstShown = await visibleTiles();
  assert(firstShown === 12 && !(await p.$eval("#more", b => b.hidden)) && await p.$eval("#shown", e => e.textContent) === `12 of ${slugs.length} shown`, `catalogue starts with ${firstShown} projects and an accurate count`);
  const cols = await p.evaluate(() => getComputedStyle(document.getElementById("tiles")).gridTemplateColumns.split(" ").length);
  assert(12 % cols === 0, `the first batch fills complete rows at this width (${cols} columns)`);
  await p.evaluate(() => document.getElementById("more").scrollIntoView({ block: "center", behavior: "instant" })); await p.evaluate(() => scrollBy(0, 300)); await p.waitForTimeout(800);
  assert(await visibleTiles() === 12, "scrolling near the end reveals nothing by itself");
  await p.click("#more"); await p.waitForTimeout(200);
  assert(await visibleTiles() === 24 && await p.$eval("#shown", e => e.textContent) === `24 of ${slugs.length} shown`, "Show more projects reveals twelve more (24) and the count follows");
  await p.fill("#search", "spark"); await p.waitForTimeout(150);
  const shown = await p.$$eval(".tile:not([hidden])", els => els.length);
  assert(shown > 0 && await p.$eval("#count-n", e => +e.textContent) === shown && shown === slugs.filter(s => fs.existsSync(path.join(root, s, "project.json")) && /spark/i.test(JSON.stringify(JSON.parse(fs.readFileSync(path.join(root, s, "project.json"), "utf8")), ["title", "kind", "tech"]))).length, `search for "spark" matches ${shown} across the whole dataset and the count agrees`);
  await p.selectOption("#kind", "SQL"); await p.waitForTimeout(150);
  assert(await p.$$eval(".tile:not([hidden])", els => els.every(e => e.dataset.kind === "SQL")) && await p.$eval(".kind-tab[data-kind='SQL']", b => b.getAttribute("aria-pressed") === "true"), "the kind filter keeps only that kind and the kind tab follows the select");
  await p.click(".kind-tab[data-kind='Python']"); await p.waitForTimeout(400);
  assert(await p.$eval("#kind", s => s.value) === "Python" && await p.$$eval(".tile:not([hidden])", els => els.every(e => e.dataset.kind === "Python")) && await p.evaluate(() => { const pill = document.querySelector(".kinds-pill"), tab = document.querySelector(".kind-tab[data-kind='Python']"); return pill.classList.contains("is-on") && Math.abs(pill.getBoundingClientRect().left - tab.getBoundingClientRect().left) < 2; }), "a kind tab filters, updates the select and the sliding mark lands under it");
  await p.selectOption("#kind", "SQL"); await p.waitForTimeout(150);
  await p.fill("#search", "zzzz-nothing"); await p.waitForTimeout(150);
  assert(await p.$eval("#empty", e => !e.hidden) && await p.$eval("#reset", b => b.textContent.trim()) === "Reset all filters", "zero results shows the empty state with a 'Reset all filters' action");
  await p.click("#clear"); await p.waitForTimeout(150);
  assert(await p.$eval("#search", i => i.value) === "" && await p.$eval("#kind", s => s.value) === "SQL" && await p.$$eval(".tile:not([hidden])", els => els.length > 0 && els.every(e => e.dataset.kind === "SQL")) && await p.evaluate(() => document.activeElement.id === "search"), "Clear search clears only the text and keeps the kind filter");
  await p.click("#reset-all"); await p.waitForTimeout(150);
  assert(await p.$eval("#kind", s => s.value) === "" && await p.$$eval(".tile:not([hidden])", els => els.length) === slugs.length && await p.$eval("#reset-all", b => b.hidden), "Reset all filters clears both and shows the whole collection");
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
  assert(stepped[1] === "#" + tiles[2].slug && stepped[2] === tiles[2].slug && stepped[3] === lenBefore && await p.$eval("#detail-open", a => a.getAttribute("href")) === tiles[2].slug + "/", `Previous / Next keep the hash, history state and links on the displayed project without growing history (${stepped[1]}, length ${stepped[3]})`);
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
  assert(await p.evaluate(async () => { const b = document.getElementById("copy-mail"); if (b.hidden) return false; b.click(); await new Promise(r => setTimeout(r, 500)); return b.textContent.trim() === "Copied" && b.classList.contains("is-done") && document.getElementById("copy-status").textContent.length > 0; }), "the optional copy-e-mail control copies and confirms visibly and to assistive tech");
  const prevented = await p.evaluate(() => { const a = document.querySelector(".tile:first-child a"); const seen = []; document.addEventListener("click", e => { seen.push(e.defaultPrevented); e.preventDefault(); }); const fire = init => { a.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, button: 0, ...init })); return seen.pop(); }; return { meta: fire({ metaKey: true }), plain: fire({}) }; });
  assert(!prevented.meta && prevented.plain, "cmd-click stays a native link; a plain click opens the detail");
  await p.close();

  // 3. deep link: #<slug> lands on the catalogue with that project open; the old archive address redirects there
  p = await page({}, null, KEEP + "#sec-10k-rag", 1500);
  assert(await p.evaluate(() => document.getElementById("detail").open) && await p.$eval("#detail-title", e => e.textContent) === "Ask the 10-K", "a direct link #sec-10k-rag opens that project");
  // history ownership: stepping from a direct link replaces state the page never pushed; Close must stay on the page
  const urlBefore = p.url().split("#")[0], lenDirect = await p.evaluate(() => history.length);
  await p.click("#detail-next"); await p.waitForTimeout(250);
  const steppedFrom = await p.evaluate(() => [location.hash, history.length, !!(history.state && history.state.pushed)]);
  await p.click("#detail-close"); await p.waitForTimeout(500);
  const afterClose = await p.evaluate(() => [document.getElementById("detail").open, location.hash, location.href]);
  assert(steppedFrom[1] === lenDirect && !steppedFrom[2] && !afterClose[0] && afterClose[1] === "" && afterClose[2].split("#")[0] === urlBefore, `a direct link, then Next (${steppedFrom[0]}), then Close stays on the page and closes in place (history ${lenDirect} -> ${steppedFrom[1]})`);
  await p.close();
  p = await page({}, null, BASE + "archive/?q=spark", 1500);
  assert(/\/#projects$/.test(p.url()) || /\/$/.test(p.url().split("#")[0]), `the archive address forwards to the portfolio (${p.url()})`);
  await p.close();
  p = await page({}, null, KEEP + "&kind=SQL", 1500);
  assert(await p.$eval("#kind", s => s.value) === "SQL" && await p.$eval(".kind-tab[data-kind='SQL']", b => b.getAttribute("aria-pressed") === "true") && await p.$$eval(".tile:not([hidden])", els => els.length > 0 && els.every(e => e.dataset.kind === "SQL")), "?kind= preselects the kind in the select and the tabs");
  await p.close();
  p = await page({}, null, BASE + featured[0].slug + "/", 0);
  const nav = await p.$$eval("header.bar nav a", as => as.map(a => a.getAttribute("href")));
  assert(nav.includes("../") && nav.includes("../#projects"), "case studies link back to the portfolio and the projects section");
  assert(await p.evaluate(() => getComputedStyle(document.querySelector(".cover img")).viewTransitionName === "cover" && getComputedStyle(document.querySelector(".hero h1")).viewTransitionName === "title") && /@view-transition\s*\{\s*navigation\s*:\s*auto/.test(fs.readFileSync(path.join(root, "portfolio.css"), "utf8")), "the case study names its cover and title for the cross-document transition the portfolio opts into");
  await p.close();

  // 3b. the intro: a count to the catalogue size while the covers arrive, then the curtain lifts; it runs once per session and can be skipped
  p = await page({}, null, BASE + "?scene=keep", 0);
  const introSeen = await p.evaluate(() => !!document.getElementById("intro") && document.documentElement.classList.contains("is-intro"));
  await p.waitForFunction(() => !document.getElementById("intro") && document.documentElement.classList.contains("is-ready"), null, { timeout: 12000 });
  const afterIntro = await p.evaluate(() => [scrollY, sessionStorage.getItem("portfolio-intro"), getComputedStyle(document.querySelector(".hero h1")).visibility, document.documentElement.classList.contains("is-intro")]);
  assert(introSeen && afterIntro[0] === 0 && afterIntro[1] === "1" && afterIntro[2] === "visible" && !afterIntro[3], "the intro runs on first visit, ends on the hero at the top and is remembered for the session");
  await p.reload({ waitUntil: "networkidle" }); await p.waitForTimeout(800);
  assert(await p.evaluate(() => !document.getElementById("intro") && document.documentElement.classList.contains("intro-off")), "a second load in the session goes straight to the hero");
  await p.close();
  p = await page({}, () => sessionStorage.clear(), BASE + "?scene=keep", 300);
  await p.keyboard.press("Space"); await p.waitForFunction(() => !document.getElementById("intro"), null, { timeout: 4000 });
  assert(await p.evaluate(() => document.documentElement.classList.contains("is-ready")), "any key skips the intro");
  await p.close();

  // 4. reduced motion: no intro, no smooth scroll, no pinned track, no motion control; content intact; the corridor sits still
  p = await page({ reducedMotion: "reduce" }, null, BASE + "?scene=keep", 2000);
  assert(await p.evaluate(() => document.getElementById("motion-toggle").hidden && !document.getElementById("intro") && !document.documentElement.classList.contains("lenis-on") && !document.documentElement.classList.contains("track-horizontal") && getComputedStyle(document.querySelector(".hero-copy")).visibility === "visible" && getComputedStyle(document.querySelector(".hero h1")).opacity === "1"), "reduced motion: no intro, no smooth scroll, no horizontal pin, no motion control; the hero copy is simply there");
  assert(await p.$$eval(".feature", els => els.every(e => e.getBoundingClientRect().left === 0 || e.getBoundingClientRect().left === els[0].getBoundingClientRect().left)) && await p.evaluate(() => document.querySelectorAll(".feature")[3].getBoundingClientRect().top > document.querySelectorAll(".feature")[0].getBoundingClientRect().top), "reduced motion: the four flagships run vertically");
  await p.close();

  // 5. WebGL unavailable: static capture, featured screenshots shown inline, all content and navigation intact
  p = await page({}, () => { const g = HTMLCanvasElement.prototype.getContext; HTMLCanvasElement.prototype.getContext = function (t, ...a) { return /webgl/.test(t) ? null : g.call(this, t, ...a); }; }, BASE, 1500);
  await p.waitForFunction(() => !document.getElementById("intro"), null, { timeout: 8000 }).catch(() => {});
  assert(await p.evaluate(() => document.documentElement.classList.contains("scene-static") && /corridor-poster/.test(getComputedStyle(document.querySelector(".hero")).backgroundImage) && !document.getElementById("intro")), "no WebGL: the hero shows the rendered corridor poster and the intro does not wait for covers that never come");
  assert(await p.$eval(".feature-figure", f => getComputedStyle(f).display !== "none") && await p.$$eval(".tile", els => els.length) === slugs.length, "no WebGL: flagship screenshots in place, catalogue intact");
  await p.close();

  // 5c. controls respond while the scene is still initialising (shaders compile in parallel; nothing blocks input)
  {
    const ctx = await b.newContext({ viewport: { width: 1440, height: 900 } }); p = await ctx.newPage();
    p.on("pageerror", e => errors.push(String(e))); p.on("console", m => { if (m.type() === "error") errors.push(m.text()); });
    await p.goto(KEEP, { waitUntil: "domcontentloaded" });
    const t0 = Date.now(); await p.fill("#search", "spark"); const typed = Date.now() - t0;
    await p.waitForTimeout(250);
    const live = await p.evaluate(() => document.documentElement.classList.contains("scene-live"));
    assert(await p.$$eval(".tile:not([hidden])", els => els.length) === 3 && typed < 1500, `search usable during initialisation (typed in ${typed} ms, scene live yet: ${live})`);
    await p.close();
  }

  // 6. no horizontal overflow at the required breakpoints
  for (const [w, h] of [[1440, 900], [1280, 800], [768, 1024], [390, 844], [360, 800]]) {
    p = await page({ viewport: { width: w, height: h } }, null, KEEP, 500);
    const sw = await p.evaluate(() => document.documentElement.scrollWidth);
    assert(sw <= w, `${w}x${h}: no horizontal overflow (scrollWidth ${sw})`);
    await p.close();
  }
  await b.close();
  assert(errors.length === 0, "no console errors or unhandled rejections" + (errors.length ? ": " + errors.join(" | ") : ""));
  console.log("all checks passed");
})().catch(e => { console.error(e); process.exit(1); });
