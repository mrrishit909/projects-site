/* Regression checks for the portfolio home (index.html) and the catalogue (all.html). Run against a local server of the built site:
     python3 -m http.server 8800 --bind 127.0.0.1 &  NODE_PATH=$(npm root -g) node tests/portfolio-check.cjs
   Covers THE HALL home: content and links without JavaScript on both pages, every internal link resolving to a real file, the
   home's page order (hero, then a title card and a room per flagship, method, about, index, contact), the atlas data, the HUD,
   the gate (loading ring and byte counter to the total, ready, Enter in silence, the 4.6 s camera flight, a wheel skipping it,
   none back from a case study, Enter without a flight under reduced motion), the WebGL world rendering (screenshot pixels), the
   chapter number per section, rooms toggling is-in, each room's number landing on the figure in featured.json, the three method
   beats taking turns, the sound toggle, the pick label, the still fallback only without WebGL, palette contrast from
   portfolio.css tokens, the nav stepping away on scroll down and back on scroll up, the catalogue's sharp thumbnails (one lazy image per project, at least twice its displayed width) and its search / filter /
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
  // the hall is a WebGL world: render it on the machine's GPU (headless Chromium otherwise falls back to SwiftShader, a CPU
  // renderer that stalls the page for seconds to minutes under load). SOFTGL=1 keeps the software renderer.
  const b = await chromium.launch(process.env.SOFTGL ? {} : { args: ["--use-angle=metal", "--enable-gpu"] });
  const errors = [];
  const page = async (opts = {}, init, url = BASE, settle = 1200, waitUntil = "networkidle") => {
    const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, permissions: ["clipboard-write"], ...opts });   // the copy-e-mail check needs the clipboard
    if (init) await ctx.addInitScript(init);
    const p = await ctx.newPage();
    p.on("pageerror", e => errors.push(String(e)));
    p.on("console", m => { if (m.type() === "error") errors.push(m.text()); });
    await p.goto(url, { waitUntil });
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
  const has = (p, c) => p.evaluate(k => document.documentElement.classList.contains(k), c);
  // the opening flight is the one GSAP timeline that is not scroll-driven and lasts longer than 4 s (4.6 s)
  const flightOn = p => p.evaluate(() => typeof gsap !== "undefined" && gsap.globalTimeline.getChildren(false, false, true).some(t => !t.scrollTrigger && t.duration() > 4 && t.isActive()));
  const enterQuiet = async p => { await p.waitForFunction(() => document.documentElement.classList.contains("ready"), null, { timeout: 15000 }); await p.waitForTimeout(700);
    // a real mouse click at the button's centre once its 600 ms reveal has finished (Playwright's own stability wait counts
    // animation frames, which a busy software-WebGL renderer can starve)
    const r = await p.$eval("#enter-quiet", b => { const q = b.getBoundingClientRect(); return [q.x + q.width / 2, q.y + q.height / 2]; }); await p.mouse.click(r[0], r[1]); return Date.now(); };
  const chapter = p => p.$eval("#chapter-n", e => e.textContent);

  // 1. home without JavaScript: identity, navigation, the hall's sections in order, the four rooms, about, index, contact
  let p = await page({ javaScriptEnabled: false }, null, BASE, 0);
  assert(await p.$eval("#hero-title", h => h.tagName === "H1" && /checked against/.test(h.textContent) && !!h.closest(".scene.hero#top[data-cam=hero]")), "the hero scene carries the statement h1");
  assert(await p.evaluate(() => !document.documentElement.classList.contains("gated") && getComputedStyle(document.getElementById("gate")).display === "none"), "no-JS: no gate, the page is open");
  assert(await p.$$eval(".nav-links a", as => as.map(a => a.textContent)).then(t => ["Work", "Index", "Contact"].every(x => t.includes(x))), "nav: Work / Index / Contact");
  const order = await p.$$eval("main .scene", els => els.map(e => e.dataset.cam + (e.dataset.n || "") + (e.id ? "#" + e.id : "")));
  const want = ["hero#top", ...featured.flatMap((f, i) => [`card${i + 1}`, `room${i + 1}#feature-${f.slug}`]), "method#method", "about#about", "index#index", "contact#contact"];
  assert(JSON.stringify(order) === JSON.stringify(want), `page order: hero > card 1 > room 1 > ... > card 4 > room 4 > method > about > index > contact (${order.join(" > ")})`);
  assert(featured.length === 4 && await p.$$eval(".scene.room", els => els.map(e => [e.dataset.slug, e.dataset.side, +e.dataset.value, e.dataset.unit])).then(r => r.every((x, i) => x[0] === featured[i].slug && x[1] === (i % 2 ? "left" : "right") && x[2] === featured[i].scale.value && x[3] === featured[i].scale.unit)), "four rooms in featured.json order, sides alternating, data-value / data-unit from featured.json");
  assert(await p.$$eval(".scene.card", els => els.map(e => [e.getAttribute("aria-hidden"), e.querySelector(".card-line").textContent])).then(c => c.length === 4 && c.every((x, i) => x[0] === "true" && x[1] === featured[i].card)), "a title card before each room, aria-hidden, with its line from featured.json");
  assert(await p.$$eval(".scene.room", els => els.every(e => e.querySelector(".num-v") && e.querySelector(".display") && e.querySelector("h3 a") && e.querySelector(".btns a") && e.querySelector("h3 a").getAttribute("href") === e.dataset.slug + "/" && e.dataset.title === e.querySelector("h3 a").textContent)), "each room has its number, headline, title link to its case study and buttons");
  assert(await p.$$eval(".scene", els => els.every(e => getComputedStyle(e).color === "rgb(255, 255, 255)")), "no-JS: every scene is readable white on ink");
  assert(await p.$$eval(".room .scene-in > *, .beat", els => els.every(e => getComputedStyle(e).opacity === "1")), "no-JS: room copy and all three method beats are visible");
  assert(await p.$$eval(".room", els => els.map(e => (e.querySelector(".num-v").textContent + e.querySelector(".num-u").textContent).replace(/\s/g, ""))).then(t => t.every((x, i) => x === `${featured[i].scale.value}${featured[i].scale.unit}`.replace(/\s/g, ""))), "each room shows the figure in featured.json");
  assert(await p.$$eval(".room .display", els => els.map(e => e.textContent)).then(t => t.every((x, i) => x === featured[i].word)), "each room carries its one-word headline");
  assert(await p.$$eval(".scene.room .still", is => is.length === 4 && is.every(i => getComputedStyle(i).display !== "none" && i.getAttribute("src") === i.closest(".room").dataset.slug + "/cover-800.webp")) && featured.every(f => fs.existsSync(path.join(root, f.slug, "cover-800.webp"))), "no-JS (no WebGL): each room shows its still, <slug>/cover-800.webp, and the file exists");
  assert(await p.$$eval("#method .beat", bs => bs.length === 3), "the method has three beats");
  const atlas = JSON.parse((await p.$eval("#atlas-data", e => e.textContent)).replace("/*ATLAS*/", ""));
  assert(atlas.items.length === slugs.length && atlas.cols > 0 && atlas.rows > 0 && atlas.items.every(it => it.slug && it.title && typeof it.a === "number" && typeof it.c === "number" && typeof it.r === "number" && it.c < atlas.cols && it.r < atlas.rows && fs.existsSync(path.join(root, `assets/atlas/atlas-${it.a}.webp`))) && new Set(atlas.items.map(it => it.slug)).size === slugs.length, `the atlas carries one screen per case study (${atlas.items.length}, ${atlas.cols}x${atlas.rows} per sheet)`);
  assert(await p.evaluate(n => { const $ = id => document.getElementById(id); return $("gate-n").textContent === "000" && $("gate").querySelector(".of").textContent.replace(/\D/g, "") === String(n) && !!$("ring") && !!$("gate-label") && $("enter-sound").tagName === "BUTTON" && $("enter-quiet").tagName === "BUTTON"; }, atlas.items.length), "the gate: ring, counter 000 of the total, label, Enter with sound / in silence");
  assert(await p.evaluate(() => { const $ = id => document.getElementById(id); return $("chapter-n").textContent === "00" && $("chapter-name").textContent === "Entrance" && $("hint").textContent.trim() === "Scroll to walk" && $("sound").tagName === "BUTTON" && $("sound").getAttribute("aria-pressed") === "false" && $("pick").tagName === "P" && $("pick").getAttribute("aria-hidden") === "true" && !!$("cursor") && !!document.querySelector("#nav .wordmark") && !!document.querySelector("#nav .strip"); }), "the HUD: wordmark and strip, chapter 00 Entrance, 'Scroll to walk', a sound button (off), the pick label, the cursor ring");
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

  // 2b. the gate: loading (ring, a real byte counter to the total), ready, Enter; the 4.6 s camera flight; a wheel skips it;
  // none coming back from a case study; under reduced motion the gate still asks but nothing flies
  const TOTAL = String(slugs.length).padStart(3, "0");
  p = await page({}, null, BASE, 0, "domcontentloaded");
  const gate0 = await p.evaluate(() => { const h = document.documentElement.classList; return [h.contains("gated"), h.contains("ready"), h.contains("entered"), getComputedStyle(document.getElementById("gate")).display !== "none"]; });
  assert(gate0[0] && !gate0[1] && !gate0[2] && gate0[3], `first load: html.gated, the gate is up, not ready, not entered (${gate0})`);
  await p.waitForFunction(() => document.documentElement.classList.contains("ready"), null, { timeout: 15000 });
  const ready = await p.evaluate(() => [document.getElementById("gate-n").textContent, document.getElementById("gate-label").textContent, document.getElementById("ring").style.strokeDashoffset, document.getElementById("enter-quiet").getBoundingClientRect().width > 0]);
  assert(ready[0] === TOTAL && /screens ready/.test(ready[1]) && +ready[2] === 0 && ready[3], `the counter reaches ${TOTAL}, the ring closes, html.ready shows the Enter buttons (${ready})`);
  let t0 = await enterQuiet(p);
  await p.waitForTimeout(300);
  const flying = await p.evaluate(() => [document.documentElement.classList.contains("entered"), document.getElementById("sound").getAttribute("aria-pressed")]);
  assert(flying[0] && flying[1] === "false" && await flightOn(p), `Enter in silence: html.entered, sound stays off, the flight runs (${flying})`);
  await p.waitForFunction(() => !document.documentElement.classList.contains("gated"), null, { timeout: 2000 });
  assert(Date.now() - t0 < 2000, "html.gated is removed about 1 s after Enter");
  await p.waitForFunction(() => !(gsap.globalTimeline.getChildren(false, false, true).some(t => !t.scrollTrigger && t.duration() > 4 && t.isActive())), null, { timeout: 7000, polling: 50 });
  const flew = Date.now() - t0;
  await p.waitForTimeout(400);
  const landedHud = await p.evaluate(() => [getComputedStyle(document.getElementById("hint")).opacity, getComputedStyle(document.getElementById("hint")).visibility, document.getElementById("chapter-n").textContent, getComputedStyle(document.getElementById("gate")).display]);
  assert(flew > 4000 && flew < 6500 && +landedHud[0] > 0.9 && landedHud[1] === "visible" && landedHud[2] === "00" && landedHud[3] === "none", `the flight ends within ~6 s (${flew} ms): #hint visible, chapter 00, the gate gone (${landedHud})`);
  await p.mouse.move(720, 450); await p.mouse.wheel(0, 600); await p.waitForTimeout(1200);
  assert(await p.evaluate(() => scrollY) > 0, "after the flight, the wheel walks the page");
  // the WebGL world renders: hide the page copy and HUD, screenshot, and count pixels clearly brighter than ink (#07070c plus grain)
  await p.evaluate(() => scrollTo(0, 0)); await p.waitForTimeout(1500);
  assert(await p.evaluate(() => { const c = document.getElementById("world"), h = document.documentElement.classList; return c.matches("canvas.world") && h.contains("gl-on") && c.width > 0 && getComputedStyle(c).display !== "none"; }), "the world is live: canvas.world, html.gl-on");
  assert(await p.$$eval(".scene.room .still", is => is.every(i => getComputedStyle(i).display === "none")), "with WebGL on, the still fallback images stay hidden");
  await p.addStyleTag({ content: "main, .hud, .foot, .cursor, .gate { visibility: hidden !important; }" }); await p.waitForTimeout(300);
  const shot = (await p.screenshot()).toString("base64");
  const lit = await p.evaluate(async b64 => { const img = new Image(); img.src = "data:image/png;base64," + b64; await img.decode(); const c = document.createElement("canvas"); c.width = img.width; c.height = img.height; const x = c.getContext("2d"); x.drawImage(img, 0, 0); const d = x.getImageData(0, 0, c.width, c.height).data; let n = 0; for (let i = 0; i < d.length; i += 4) if (Math.max(d[i], d[i + 1], d[i + 2]) > 60) n++; return n / (d.length / 4); }, shot);
  assert(lit > 0.01, `after entering, the rendered hall is visible: ${(lit * 100).toFixed(1)}% of pixels are brighter than ink`);
  await p.evaluate(() => document.querySelectorAll("style").forEach(s => /visibility: hidden !important/.test(s.textContent) && s.remove()));

  // 3. the walk (same page, after the flight): the chapter number per section, rooms is-in, each number lands, the beats, sound, pick
  const seen = [];
  for (const [k, id] of (await p.$$eval("main .scene", els => els.map((e, k) => [k, e.id]))).entries()) {
    await p.evaluate(k => document.querySelectorAll("main .scene")[k].scrollIntoView({ block: "start", behavior: "instant" }), id[0]); await p.waitForTimeout(400);
    seen.push(await chapter(p));
  }
  const wantCh = ["00", "01", "01", "02", "02", "03", "03", "04", "04", "05", "06", "07", "08"];
  assert(JSON.stringify(seen) === JSON.stringify(wantCh), `the chapter number follows every section (${seen.join(" ")})`);
  await jump(p, "#top"); await p.waitForTimeout(500);
  for (let i = 0; i < 4; i++) {
    await jump(p, "#feature-" + featured[i].slug); await p.waitForTimeout(1900);
    const wantN = `${featured[i].scale.value}${featured[i].scale.unit}`.replace(/\s/g, "");
    const [num, inRooms, ch] = await p.evaluate(k => [(r => (r.querySelector(".num-v").textContent + r.querySelector(".num-u").textContent).replace(/\s/g, ""))(document.querySelectorAll(".room")[k]), [...document.querySelectorAll(".room")].map(r => r.classList.contains("is-in")), document.getElementById("chapter-n").textContent], i);
    assert(num === wantN && inRooms.every((v, j) => v === (j === i)) && ch === String(i + 1).padStart(2, "0"), `room ${i + 1}: the number lands on ${wantN} (${num}), only this room is-in (${inRooms}), chapter ${ch}`);
  }
  await jump(p, "#method"); await p.waitForTimeout(600);
  assert(await p.$$eval(".room", rs => rs.every(r => !r.classList.contains("is-in"))), "leaving the rooms clears is-in");
  const beatsAt = [];
  for (const u of [0.15, 0.5, 0.85]) {
    await p.evaluate(u => { const m = document.getElementById("method"); scrollTo({ top: m.offsetTop + u * (m.offsetHeight - innerHeight), behavior: "instant" }); }, u); await p.waitForTimeout(700);
    beatsAt.push(await p.$$eval(".beat", bs => bs.map(b => b.classList.contains("is-on") ? 1 : 0).join("")));
  }
  assert(JSON.stringify(beatsAt) === JSON.stringify(["100", "010", "001"]), `the three beats take turns through #method (${beatsAt.join(" ")})`);
  await jump(p, "#index"); await p.waitForTimeout(800);
  assert(await p.evaluate(() => document.querySelector("#index").getBoundingClientRect().top <= 1) && await chapter(p) === "07", "#index is reachable by anchor and shows chapter 07");
  const snd = [];
  for (let i = 0; i < 2; i++) { await p.click("#sound"); await p.waitForTimeout(150); snd.push(await p.$eval("#sound", b => b.getAttribute("aria-pressed") + "/" + b.textContent.trim())); }
  assert(snd[0] === "true/Sound on" && snd[1] === "false/Sound off", `the sound button toggles aria-pressed and its label (${snd.join(", ")})`);
  assert(await p.$eval("#pick", e => e.tagName === "P" && getComputedStyle(e).position === "fixed"), "the pick label is in place for screens under the pointer");
  await jump(p, "#contact"); await p.waitForTimeout(900);
  assert(await p.evaluate(async () => { const btn = document.getElementById("copy-mail"); if (btn.hidden) return false; btn.click(); await new Promise(r => setTimeout(r, 500)); return btn.textContent.trim() === "Copied" && document.getElementById("copy-status").textContent.length > 0; }), "Copy e-mail copies and confirms");
  await p.close();

  // a wheel during the flight skips it: the timeline ends at once and the walk is free well before 4.6 s
  p = await page({}, null, BASE, 0, "domcontentloaded");
  t0 = await enterQuiet(p);
  await p.waitForTimeout(400);
  const before = await flightOn(p);
  await p.mouse.move(720, 450); await p.mouse.wheel(0, 120); await p.waitForTimeout(150);
  const after = await flightOn(p);
  await p.waitForFunction(() => !document.documentElement.classList.contains("gated"), null, { timeout: 2000 });
  await p.mouse.wheel(0, 600); await p.waitForTimeout(800);
  const freeAt = Date.now() - t0, y = await p.evaluate(() => scrollY);
  assert(before && !after && y > 0 && freeAt < 4000, `a wheel during the flight skips it (running ${before}, then ${after}); the page scrolls ${y}px at ${freeAt} ms`);
  await p.close();

  // coming back from a case study (sessionStorage vt): no gate at all; keyboard order from the top
  p = await page({}, () => { try { sessionStorage.setItem("vt", "retail-dbt"); } catch (_) {} }, BASE, 0, "domcontentloaded");
  assert(await p.evaluate(() => { const h = document.documentElement.classList; return !h.contains("gated") && getComputedStyle(document.getElementById("gate")).display === "none"; }), "with sessionStorage vt set before load there is no gate");
  await p.waitForFunction(() => document.documentElement.classList.contains("entered") && document.documentElement.classList.contains("quick"), null, { timeout: 10000 });
  assert(!(await flightOn(p)), "coming back from a case study: html.entered quick, no flight");
  await p.keyboard.press("Tab");
  assert(await p.evaluate(() => document.activeElement.className === "skip"), "first Tab lands on the skip link");
  await p.keyboard.press("Tab"); await p.keyboard.press("Tab");
  assert(await p.evaluate(() => document.activeElement.textContent === "Work"), "nav is reachable by keyboard");
  await p.close();

  // reduced motion: the gate still appears and Enter works, but nothing flies; no smooth scroll; the world still on
  p = await page({ reducedMotion: "reduce" }, null, BASE, 0, "domcontentloaded");
  assert(await has(p, "gated"), "reduced motion: the gate still appears");
  await enterQuiet(p);
  await p.waitForTimeout(50);
  const rm = await p.evaluate(() => [document.documentElement.classList.contains("entered"), document.documentElement.classList.contains("quick")]);
  const rmFlight = await flightOn(p);
  await p.waitForTimeout(1500);
  const still = await p.evaluate(() => [document.documentElement.classList.contains("gated"), document.documentElement.classList.contains("lenis-on"), document.documentElement.classList.contains("gl-on"), document.getAnimations().filter(a => a.playState === "running").length]);
  assert(rm[0] && rm[1] && !rmFlight && !still[0] && !still[1] && still[2] && still[3] === 0, `reduced motion: Enter adds entered quick, no flight, the gate lifts, no smooth scroll, the world on, no running animation (${rm}, ${rmFlight}, ${still})`);
  await p.close();
  // contrast from the palette in portfolio.css: ink, white, hot, dim (white at alpha, composited over its background)
  const css = fs.readFileSync(path.join(root, "portfolio.css"), "utf8");
  const tok = name => { const m = css.match(new RegExp(`--${name}:\\s*([^;]+);`)); return m && m[1].trim(); };
  const rgb = v => v.startsWith("#") ? [1, 3, 5].map(i => parseInt(v.slice(i, i + 2), 16)).concat(1) : v.match(/[\d.]+/g).map(Number).concat(1).slice(0, 4);
  const over = (fg, bg) => fg.slice(0, 3).map((c, i) => c * fg[3] + bg[i] * (1 - fg[3]));
  const L = c => { const v = c.map(x => x / 255).map(x => x <= .03928 ? x / 12.92 : ((x + .055) / 1.055) ** 2.4); return .2126 * v[0] + .7152 * v[1] + .0722 * v[2]; };
  const ratio = (fg, bg) => { const b = rgb(tok(bg)), a = L(over(rgb(tok(fg)), b)), c = L(b); return (Math.max(a, c) + .05) / (Math.min(a, c) + .05); };
  assert(tok("ink") === "#07070c" && tok("white") === "#ffffff" && tok("hot") === "#ff4d00", `palette tokens: ink ${tok("ink")}, white ${tok("white")}, hot ${tok("hot")}`);
  const pairs = [["white", "ink"], ["dim", "ink"], ["dim", "ink-2"], ["hot", "ink"], ["ink", "hot"], ["ink", "white"], ["white", "ink-2"]].map(([f, g]) => [f + " on " + g, ratio(f, g)]);
  assert(pairs.every(([, v]) => v >= 4.5), "every text pairing in the palette clears 4.5:1: " + pairs.map(([k, v]) => k + " " + v.toFixed(2)).join(", "));

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
  assert(nav.includes("../#feature-" + featured[0].slug) && nav.includes("../all.html"), "a flagship's case study links back to its own room on the home and to the index");
  assert(await p.$eval(".facts-strip", d => d.textContent.includes("Commits") && d.textContent.includes("Last push")), "the case study carries the repository facts strip");
  await p.close();

  // 6. (reduced motion is checked with the gate, in 2b)
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
