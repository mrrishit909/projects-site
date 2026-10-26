// The responsive conditions beyond the suite's five widths: 1024 and 1920 wide, phone landscape, 200% zoom (a 720 x 450
// layout viewport at 2x), short phones, plus a keyboard walk with focus-ring captures. Five pages: home, archive, a
// flagship, a long-title page, a thin page. Writes PNGs and responsive.json (overflow, hidden-content audit) to
// $EVIDENCE_OUT/responsive/. NODE_PATH=$(npm root -g) node tests/evidence/responsive.cjs
const OUT = process.env.EVIDENCE_OUT || require('path').join(require('os').homedir(), 'projects-site-evidence', 'atelier-2026-10-25');
const { chromium } = require('playwright'); const fs = require('fs'); const path = require('path');
const dir = path.join(OUT, 'responsive'); fs.mkdirSync(dir, { recursive: true });
const BASE = 'http://127.0.0.1:8800/';
const PAGES = [['home', ''], ['archive', 'all.html'], ['flagship', 'florida-flight-delays/'], ['long', 'workforce-scheduler/'], ['thin', 'iris-fisher/']];
const VIEWS = [['1024', { width: 1024, height: 768 }, 1, false], ['1920', { width: 1920, height: 1080 }, 1, false], ['landscape', { width: 844, height: 390 }, 2, true], ['zoom200', { width: 720, height: 450 }, 2, false], ['short', { width: 390, height: 640 }, 2, true]];
(async () => {
  const b = await chromium.launch({ args: ['--use-angle=metal', '--ignore-gpu-blocklist'] }); const out = {};
  for (const [vn, vp, dsf, mobile] of VIEWS) for (const [pn, url] of PAGES) {
    const ctx = await b.newContext({ viewport: vp, deviceScaleFactor: dsf, isMobile: mobile, hasTouch: mobile }); await ctx.addInitScript(() => { try { sessionStorage.setItem('seen', '1'); } catch (_) {} });
    const p = await ctx.newPage(); await p.goto(BASE + url, { waitUntil: 'networkidle' }); await p.waitForTimeout(1200);
    const key = `${pn}-${vn}`; await p.screenshot({ path: path.join(dir, key + '-top.png') });
    if (pn === 'home') { await p.evaluate(() => { const el = document.querySelector('#feature-florida-flight-delays'); const top = el.getBoundingClientRect().top + scrollY; scrollTo(0, top + Math.max(0, el.offsetHeight - innerHeight) * 0.8); }); await p.waitForTimeout(1200); await p.screenshot({ path: path.join(dir, key + '-chapter.png') }); }
    else { await p.evaluate(() => scrollTo(0, innerHeight * 1.2)); await p.waitForTimeout(600); await p.screenshot({ path: path.join(dir, key + '-body.png') }); }
    out[key] = await p.evaluate(() => { const hidden = [...document.querySelectorAll('h1, h2, .lead, .btn, .summary dd, .figure .def')].filter(e => { const s = getComputedStyle(e); return s.display === 'none' || s.visibility === 'hidden'; }).map(e => (e.className || e.tagName) + ':' + e.textContent.trim().slice(0, 30)); return { sw: document.documentElement.scrollWidth, vw: innerWidth, hidden }; });
    await ctx.close();
  }
  // keyboard walk on the home and a case page: the first eight tab stops with their focus rings
  for (const [pn, url, n] of [['home', '', 9], ['flagship', 'florida-flight-delays/', 7]]) {
    const ctx = await b.newContext({ viewport: { width: 1440, height: 900 } }); await ctx.addInitScript(() => { try { sessionStorage.setItem('seen', '1'); } catch (_) {} });
    const p = await ctx.newPage(); await p.goto(BASE + url, { waitUntil: 'networkidle' }); await p.waitForTimeout(800); const stops = [];
    for (let i = 0; i < n; i++) { await p.keyboard.press('Tab'); await p.waitForTimeout(120); stops.push(await p.evaluate(() => { const e = document.activeElement; const s = getComputedStyle(e); return (e.id ? '#' + e.id : e.tagName + '.' + e.className) + ' | ' + e.textContent.trim().slice(0, 24) + ' | outline ' + s.outlineStyle + ' ' + s.outlineWidth; })); if (i === 2 || i === n - 1) await p.screenshot({ path: path.join(dir, `${pn}-keyboard-${i + 1}.png`) }); }
    out[`${pn}-keyboard`] = stops; await ctx.close();
  }
  await b.close(); fs.writeFileSync(path.join(dir, 'responsive.json'), JSON.stringify(out, null, 2));
  const over = Object.entries(out).filter(([, v]) => v.sw && v.sw > v.vw).map(([k]) => k);
  console.log(Object.keys(out).length, 'entries;', over.length ? 'OVERFLOW: ' + over.join(', ') : 'no horizontal overflow');
  for (const [k, v] of Object.entries(out)) if (v.hidden && v.hidden.length) console.log('hidden at', k, v.hidden.join('; '));
})();
