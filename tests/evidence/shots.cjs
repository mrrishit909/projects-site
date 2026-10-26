// Every stop of the Precision Atelier home at desktop and phone, plus a case study and the archive.
// NODE_PATH=$(npm root -g) node shots.cjs <outdir>
// Output folder: $EVIDENCE_OUT, default ~/projects-site-evidence/atelier-2026-10-25 (outside the repository; packaged by tools/package.sh).
const OUT = process.env.EVIDENCE_OUT || require('path').join(require('os').homedir(), 'projects-site-evidence', 'atelier-2026-10-25');
const { chromium } = require('playwright'); const path = require('path'); const fs = require('fs');
const out = path.join(OUT, process.argv[2] || 'shots'); fs.mkdirSync(out, { recursive: true });
(async () => {
  const b = await chromium.launch({ args: ['--use-angle=metal', '--ignore-gpu-blocklist'] });
  const report = {};
  for (const [name, vp, mobile] of [['d', { width: 1440, height: 900 }, false], ['m', { width: 390, height: 844 }, true]]) {
    const ctx = await b.newContext({ viewport: vp, deviceScaleFactor: mobile ? 2 : 1, isMobile: mobile, hasTouch: mobile });
    const p = await ctx.newPage(); const errs = []; p.on('pageerror', e => errs.push(e.message)); p.on('console', m => { if (m.type() === 'error') errs.push(m.text().slice(0, 300)); });
    const failed = []; p.on('requestfailed', r => failed.push(r.url()));
    await p.goto('http://127.0.0.1:8800/index.html', { waitUntil: 'commit' });
    await p.waitForTimeout(120); await p.screenshot({ path: `${out}/${name}-00-first.png` });
    let last = 120; for (const ms of [600, 1200, 1900, 2500, 3200]) { await p.waitForTimeout(ms - last); last = ms; await p.screenshot({ path: `${out}/${name}-01-open-${ms}.png` }); }
    await p.waitForTimeout(900); await p.screenshot({ path: `${out}/${name}-02-hero.png` });
    const stops = [['orient', '#work', 0], ['ch1a', '[data-chapter="work-1"]', 0.15], ['ch1b', '[data-chapter="work-1"]', 0.75], ['ch2a', '[data-chapter="work-2"]', 0.3], ['ch2b', '[data-chapter="work-2"]', 0.85], ['ch3', '[data-chapter="work-3"]', 0.8], ['ch4a', '[data-chapter="work-4"]', 0.45], ['ch4b', '[data-chapter="work-4"]', 0.98], ['system', '#system', 0], ['about', '#about', 0], ['archive', '#archive', 0], ['contact', '#contact', 0]];
    for (const [key, sel, f] of stops) { await p.evaluate(([s, f]) => { const el = document.querySelector(s); const top = el.getBoundingClientRect().top + scrollY; scrollTo(0, top + Math.max(0, el.offsetHeight - innerHeight) * f); }, [sel, f]); await p.waitForTimeout(2000); await p.screenshot({ path: `${out}/${name}-${key}.png` }); }
    report[name] = { height: await p.evaluate(() => document.body.scrollHeight), errors: errs.slice(0, 8), failed: failed.slice(0, 8), html: await p.evaluate(() => document.documentElement.className + ' ' + document.documentElement.dataset.field), info: await p.evaluate(() => (window.__inst ? window.__inst.info() : null)) };
    for (const [key, url] of [['case-flagship', 'florida-flight-delays/'], ['case-long', 'workforce-scheduler/'], ['case-thin', 'iris-fisher/'], ['archive-page', 'all.html']]) {
      await p.goto('http://127.0.0.1:8800/' + url, { waitUntil: 'networkidle' }); await p.waitForTimeout(2200); await p.screenshot({ path: `${out}/${name}-${key}.png` });
      if (key === 'case-flagship') { await p.evaluate(() => scrollTo(0, innerHeight * 1.1)); await p.waitForTimeout(900); await p.screenshot({ path: `${out}/${name}-case-flagship-2.png` }); } }
    console.log(name, JSON.stringify(report[name]));
    await ctx.close();
  }
  await b.close(); fs.writeFileSync(path.join(out, 'report.json'), JSON.stringify(report, null, 2));
})();
