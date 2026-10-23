/* Regression checks for the portfolio home (index.html). Run against a local server of the built site:
     python3 -m http.server 8800 --bind 127.0.0.1 &  NODE_PATH=$(npm root -g) node tests/portfolio-check.cjs
   Covers: content and links without JavaScript, every internal link resolving to a real file, the page order, the hero's
   toy blocks building with scroll, the stacking flagship cards and their counters, the complete catalogue and its search /
   filter / twelve-at-a-time reveal / detail dialog (#<slug>, Previous / Next keeping the URL and history in step), the
   screenshot viewer, cover previews, keyboard order, reduced motion, the archive redirect, case-study navigation, contrast
   from computed styles on every colour field, overflow at five breakpoints, console errors. */
const { chromium } = require("playwright");
const fs = require("fs"), path = require("path");
const BASE = process.env.BASE || "http://127.0.0.1:8800/";
const root = path.join(__dirname, "..");
const assert = (ok, msg) => { if (!ok) { console.error("FAIL:", msg); process.exit(1); } console.log("ok:", msg); };

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

  // 1. without JavaScript: identity, navigation, featured work, the whole catalogue, résumé and contact are plain HTML
  let p = await page({ javaScriptEnabled: false }, null, BASE, 0);
  assert(await p.$eval("h1", h => h.textContent.trim().replace(/\s+/g, " ")) === "Rishit Mathur", "name is the h1 without JavaScript");
  assert(await p.$$eval(".nav-links a", as => as.map(a => a.textContent)).then(t => ["Work", "Projects", "About", "Experience", "Résumé", "Contact"].every(x => t.includes(x))), "persistent nav: Work / About / Experience / Projects / Résumé / Contact");
  const order = await p.$$eval("main > section[id]", els => els.map(e => e.id));
  assert(JSON.stringify(order) === JSON.stringify(["top", "work", "about", "experience", "capabilities", "projects", "contact"]), `page order: hero, work, about, experience, capabilities, projects, contact (${order.join(" > ")})`);
  assert(await p.$eval(".blocks-still", i => i.naturalWidth > 0 && getComputedStyle(i).visibility === "visible"), "no-JS: the hero shows the blocks render as an image");
  assert(featured.length === 4 && await p.$$eval(".feature", els => els.length) === 4, "four flagship projects rendered as static HTML");
  assert(await p.$$eval(".feature-figure img", imgs => imgs.length === 4 && imgs.every(i => i.naturalWidth > 0)), "no-JS: every flagship screenshot is in the page");
  assert(await p.$$eval(".feature .inspect", as => as.every(a => /\.(jpg|png)$/.test(a.getAttribute("href")) && /Enlarge screenshot/.test(a.getAttribute("aria-label")))), "no-JS: the enlarge control is a real link to the full-size image");
  assert(await p.$$eval(".feature .reading-value", hs => hs.length === 4 && hs.every(h => /\d/.test(h.textContent))), "each flagship shows its qualified figure");
  assert(await p.$$eval(".feature", els => els.every(e => +e.dataset.value >= +e.dataset.min && +e.dataset.value <= +e.dataset.max && e.dataset.metric && /cover\.jpg$/.test(e.dataset.cover))), "every flagship carries its figure, its scale and its screenshot");
  assert(await p.$$eval(".tile", els => els.every(e => /^\d+,\d+,\d+$/.test(e.dataset.w))) && fs.existsSync(path.join(root, "assets", "wall", "atlas-0.jpg")), "every catalogue entry knows its place in the cover atlas, and the atlas files exist");
  assert(fs.readdirSync(path.join(root, "assets", "blocks")).filter(f => /^\d{3}\.webp$/.test(f)).length === 72, "the 72 block frames are on disk");
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

  // 2. with JavaScript: the blocks build with scroll, cards stack, counters land on the reported figure, keyboard order
  p = await page();
  await p.keyboard.press("Tab");
  assert(await p.evaluate(() => document.activeElement.className === "skip"), "first Tab lands on the skip link");
  await p.keyboard.press("Tab"); await p.keyboard.press("Tab");
  assert(await p.evaluate(() => document.activeElement.textContent === "Work"), "nav is reachable by keyboard");
  const blocksAt = async y => { await p.evaluate(v => scrollTo(0, v), y); await p.waitForTimeout(500); return p.evaluate(() => [document.documentElement.classList.contains("blocks-live"), +getComputedStyle(document.querySelector(".hero")).getPropertyValue("--p")]); };
  await p.waitForFunction(() => document.documentElement.classList.contains("blocks-live"), null, { timeout: 8000 });
  const b0 = await blocksAt(0), bMid = await blocksAt(500), bEnd = await blocksAt(2000);
  assert(b0[0] && b0[1] === 0 && bMid[1] > 0.3 && bMid[1] < 0.8 && bEnd[1] === 1, `the blocks follow the hero's scroll (p ${b0[1]} > ${bMid[1]} > ${bEnd[1]})`);
  assert(await p.evaluate(() => getComputedStyle(document.querySelector(".blocks-still")).visibility === "hidden"), "once the frames are live the still image steps aside");
  await jump(p, "#work"); await p.waitForTimeout(400);
  for (let i = 0; i < 4; i++) { await p.evaluate(n => scrollBy(0, n), 700); await p.waitForTimeout(900); }
  const readings = await p.$$eval(".feature .reading-value", hs => hs.map(h => h.textContent.trim()));
  const expected = featured.map(f => `${f.scale.value}${f.scale.unit}`);
  assert(readings.every((r, i) => r.replace(/\s/g, "") === expected[i].replace(/\s/g, "")), `the counters land on the figures in featured.json (${readings.join(", ")})`);
  assert(await p.$$eval(".feature", els => els.every(e => getComputedStyle(e).position === "sticky")), "flagship cards are sticky so they stack as you read");
  await jump(p, "#about"); await p.waitForTimeout(800);
  assert(await p.evaluate(() => document.querySelector(".nav").classList.contains("is-solid") && document.querySelector(".nav-links a[href='#about']").hasAttribute("aria-current")), "past the hero the nav turns solid and marks the current section");
  // the screenshot viewer: opens from the figure, shows the full image, closes on Escape and returns focus
  await jump(p, ".feature:nth-of-type(1)", "center"); await p.waitForTimeout(400);
  await p.evaluate(() => document.querySelector(".feature:nth-of-type(1) .inspect").click()); await p.waitForTimeout(600);
  const viewer = await p.evaluate(() => { const v = document.getElementById("viewer"), i = document.getElementById("viewer-img"); return [v.open, document.activeElement.id, i.getAttribute("src"), i.naturalWidth > 1000, document.getElementById("viewer-caption").textContent.length > 20, document.getElementById("viewer-case").getAttribute("href")]; });
  assert(viewer[0] && viewer[1] === "viewer-close" && /florida-flight-delays\/cover\.jpg/.test(viewer[2]) && viewer[3] && viewer[4] && viewer[5] === "florida-flight-delays/", `screenshot viewer opens with the full image, a caption and the case-study link (${viewer.join(", ")})`);
  await p.keyboard.press("Escape"); await p.waitForTimeout(300);
  assert(await p.evaluate(() => !document.getElementById("viewer").open && document.activeElement === document.querySelector(".feature:nth-of-type(1) .inspect") && location.hash === ""), "Escape closes the viewer, focus returns to the enlarge control, the URL is untouched");
  // contrast: sampled text against the colour field it sits on
  const contrast = await p.evaluate(() => {
    const lum = c => { const v = c.match(/[\d.]+/g).slice(0, 3).map(x => x / 255).map(x => x <= .03928 ? x / 12.92 : ((x + .055) / 1.055) ** 2.4); return .2126 * v[0] + .7152 * v[1] + .0722 * v[2]; };
    const r = (a, c) => ((Math.max(a, c) + .05) / (Math.min(a, c) + .05));
    const bgOf = el => { for (let e = el; e; e = e.parentElement) { const c = getComputedStyle(e).backgroundColor; if (!/rgba\(0, 0, 0, 0\)|transparent/.test(c) && !/, 0\)$/.test(c)) return c; } return "rgb(255,255,255)"; };
    const sel = [".hero-kicker", ".hero-lede", ".hero-creds span", ".blocks-caption", ".band-set", ".section-lede", ".feature-meta span", ".reading-label", ".facts dd", ".tools li", ".feature-figure figcaption", ".statement-big", ".about-copy", ".about-facts dt", ".about-facts dd", ".tl-when", ".timeline p:not(.tl-when)", ".cap-list p", ".cap-proof a", ".tile-kind", ".tile-title", ".tile:nth-child(4) .tile-kind", ".count", ".kind-tab[aria-pressed=false]", ".field-label", ".contact .section-lede", ".contact-mail", ".foot"];
    return sel.map(s => { const el = document.querySelector(s); return [s, r(lum(getComputedStyle(el).color), lum(bgOf(el))).toFixed(2)]; });
  });
  assert(contrast.every(([, v]) => +v >= 4.5), "sampled text clears 4.5:1 on its own colour field: " + contrast.map(x => x.join(" ")).join(", "));
  // cover previews: hovering an entry shows its cover from the atlas, no request per project
  await jump(p, "#projects"); await p.waitForTimeout(700);
  await p.hover(".tile:nth-child(3) a"); await p.waitForTimeout(300);
  assert(await p.evaluate(() => { const k = document.getElementById("peek"); return k.classList.contains("is-on") && /atlas-\d\.jpg/.test(k.style.backgroundImage); }), "hovering a catalogue entry floats its cover, cut from the atlas");
  await p.mouse.move(10, 10); await p.waitForTimeout(300);
  assert(await p.evaluate(() => !document.getElementById("peek").classList.contains("is-on")), "the preview leaves with the cursor");
  // the catalogue: progressive reveal, search, filter, detail dialog with history and focus restoration
  await jump(p, "#projects"); await p.waitForTimeout(600);
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
  assert(await p.$eval("#kind", s => s.value) === "Python" && await p.$$eval(".tile:not([hidden])", els => els.every(e => e.dataset.kind === "Python")) && await p.evaluate(() => { const pill = document.querySelector(".kinds-pill"), tab = document.querySelector(".kind-tab[data-kind='Python']"); return pill.classList.contains("is-on") && Math.abs(pill.offsetWidth - tab.offsetWidth) < 2; }), "a kind tab sets the select and the pill slides under it");
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
  assert(await p.evaluate(async () => { const btn = document.getElementById("copy-mail"); if (btn.hidden) return false; btn.click(); await new Promise(r => setTimeout(r, 500)); return btn.textContent.trim() === "Copied" && btn.classList.contains("is-done") && document.getElementById("copy-status").textContent.length > 0; }), "Copy e-mail copies and confirms");
  const prevented = await p.evaluate(() => { const a = document.querySelector(".tile:first-child a"); const seen = []; document.addEventListener("click", e => { seen.push(e.defaultPrevented); e.preventDefault(); }); const fire = init => { a.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, ...init })); }; fire({ metaKey: true }); const meta = seen.pop(); document.getElementById("detail").open && document.getElementById("detail").close(); fire({}); const plain = seen.pop(); return { meta, plain }; });
  assert(!prevented.meta && prevented.plain, "cmd-click stays a native link; a plain click opens the detail");
  await p.close();

  // 3. deep link: #<slug> lands on the catalogue with that project open; history ownership; archive redirect; ?kind=
  p = await page({}, null, BASE + "#sec-10k-rag", 1500);
  assert(await p.evaluate(() => document.getElementById("detail").open) && await p.$eval("#detail-title", e => e.textContent) === "Ask the 10-K", "a direct link #sec-10k-rag opens that project");
  const urlBefore = p.url().split("#")[0], lenDirect = await p.evaluate(() => history.length);
  await p.click("#detail-next"); await p.waitForTimeout(250);
  const steppedFrom = await p.evaluate(() => [location.hash, history.length, !!(history.state && history.state.pushed)]);
  await p.click("#detail-close"); await p.waitForTimeout(500);
  const afterClose = await p.evaluate(() => [document.getElementById("detail").open, location.hash, location.href]);
  assert(steppedFrom[1] === lenDirect && !steppedFrom[2] && !afterClose[0] && afterClose[1] === "" && afterClose[2].split("#")[0] === urlBefore, `a direct link, then Next (${steppedFrom[0]}), then Close stays on the page and closes in place (history ${lenDirect})`);
  await p.close();
  p = await page({}, null, BASE + "archive/?q=spark", 1500);
  assert(/\/#projects$/.test(p.url()) || /\/$/.test(p.url().split("#")[0]), `the archive address forwards to the portfolio (${p.url()})`);
  await p.close();
  p = await page({}, null, BASE + "?kind=SQL", 1500);
  assert(await p.$eval("#kind", s => s.value) === "SQL" && await p.$eval(".kind-tab[data-kind='SQL']", btn => btn.getAttribute("aria-pressed") === "true") && await p.$$eval(".tile:not([hidden])", els => els.length > 0 && els.every(e => e.dataset.kind === "SQL")), "?kind=SQL arrives filtered");
  await p.close();
  p = await page({}, null, BASE + featured[0].slug + "/", 0);
  const nav = await p.$$eval("header.bar nav a", as => as.map(a => a.getAttribute("href")));
  assert(nav.includes("../") && nav.includes("../#projects"), "case studies link back to the portfolio and the projects section");
  await p.close();

  // 4. reduced motion: no smooth scroll, no reveals hidden, no running animations, the finished chart shown still
  p = await page({ reducedMotion: "reduce" }, null, BASE, 1500);
  const still = await p.evaluate(() => [document.documentElement.classList.contains("lenis-on"), document.querySelectorAll(".reveal").length, document.getAnimations().filter(a => a.playState === "running").length, document.querySelector(".blocks-still").getAttribute("src"), getComputedStyle(document.querySelector(".hero")).height]);
  assert(!still[0] && still[1] === 0 && still[2] === 0 && /071\.webp$/.test(still[3]), `reduced motion: no smooth scroll, nothing waits to reveal, no running animation, the finished chart as a still (${still.join(", ")})`);
  await p.close();

  // 5. no horizontal overflow at the required breakpoints
  for (const [w, h] of [[1440, 900], [1280, 800], [768, 1024], [390, 844], [360, 800]]) {
    p = await page({ viewport: { width: w, height: h } }, null, BASE, 500);
    const sw = await p.evaluate(() => document.documentElement.scrollWidth);
    assert(sw <= w, `${w}x${h}: no horizontal overflow (scrollWidth ${sw})`);
    await p.close();
  }
  await b.close();
  assert(errors.length === 0, "no console errors or unhandled rejections" + (errors.length ? ": " + errors.join(" | ") : ""));
  console.log("all checks passed");
})().catch(e => { console.error(e); process.exit(1); });
