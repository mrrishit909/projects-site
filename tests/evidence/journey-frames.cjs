// Representative paused frames of the whole journey in a WebGL browser (Playwright Chromium on the GPU), desktop and phone:
// the opening at fixed times, the hero settled, each chapter at its reading state, the system chapter, the ivory sections,
// the first case page (top and reading), the archive, and the home after Back. The same script is run before and after a
// refinement so the frames compare like for like. Writes <out>/<d|m>-<name>.png and frames.json.
// NODE_PATH=$(npm root -g) node tests/evidence/journey-frames.cjs <outdir>
const OUT = process.argv[2] || require('path').join(require('os').homedir(), 'projects-site-evidence', 'atelier-2026-10-25', 'refine', 'frames');
const { chromium } = require('playwright'); const fs = require('fs'); const path = require('path');
fs.mkdirSync(OUT, { recursive: true });
const BASE = 'http://127.0.0.1:8800/';
(async () => {
  const b = await chromium.launch({ args: ['--use-angle=metal', '--ignore-gpu-blocklist'] });
  const log = [];
  for (const [tag, vp, mobile] of [['d', { width: 1440, height: 900 }, false], ['m', { width: 390, height: 844 }, true]]) {
    const ctx = await b.newContext({ viewport: vp, deviceScaleFactor: 2, isMobile: mobile, hasTouch: mobile });
    const p = await ctx.newPage(); const shot = async name => { await p.screenshot({ path: path.join(OUT, `${tag}-${name}.png`) }); log.push(`${tag}-${name}`); };
    await p.goto(BASE, { waitUntil: 'commit' });
    const t0 = Date.now(); for (const ms of [300, 900, 1500, 2200, 2800, 3600]) { const wait = ms - (Date.now() - t0); if (wait > 0) await p.waitForTimeout(wait); await shot(`opening-${ms}`); }
    await p.waitForTimeout(800); await shot('hero');
    // each chapter at its reading state (u about 0.6) and, for the first, the development state (u about 0.25)
    const at = async (sel, u) => { await p.evaluate(([s, u]) => { const el = document.querySelector(s); const top = el.getBoundingClientRect().top + scrollY; scrollTo(0, top + Math.max(0, el.offsetHeight - innerHeight) * u); }, [sel, u]); await p.waitForTimeout(1600); };
    await at('#work', 0.3); await shot('orient');
    for (const [slug, i] of [['florida-flight-delays', 1], ['retail-dbt', 2], ['store-sales-forecast', 3], ['sec-10k-rag', 4]]) {
      const sel = `#feature-${slug}`; if (!(await p.$(sel))) continue;
      if (i === 1) { await at(sel, 0.22); await shot(`chapter${i}-develop`); }
      await at(sel, 0.62); await shot(`chapter${i}`); }
    await at('#system', 0.3); await shot('system');
    await at('#about', 0.1); await shot('about');
    await at('#archive', 0.1); await shot('archive-home');
    await at('#contact', 0.2); await shot('contact');
    // into the first case page and back
    await at('#feature-florida-flight-delays', 0.62);
    await p.evaluate(() => document.querySelector('#feature-florida-flight-delays .btns a.fill').click()); await p.waitForLoadState('load'); await p.waitForTimeout(2600); await shot('case-top');
    await p.evaluate(() => scrollTo(0, innerHeight * 1.2)); await p.waitForTimeout(1200); await shot('case-reading');
    await p.evaluate(() => scrollTo(0, document.body.scrollHeight - innerHeight)); await p.waitForTimeout(1200); await shot('case-end');
    await p.goBack(); await p.waitForLoadState('load'); await p.waitForTimeout(1800); await shot('back');
    await p.goto(BASE + 'all.html', { waitUntil: 'load' }); await p.waitForTimeout(1200); await shot('archive');
    await ctx.close();
  }
  fs.writeFileSync(path.join(OUT, 'frames.json'), JSON.stringify({ when: new Date().toISOString(), frames: log }, null, 2));
  console.log(log.length, 'frames in', OUT);
  await b.close();
})();
