// Main-thread cost with the GPU on and the CPU throttled 4x (CDP), to separate the instrument's real JavaScript cost from
// Lighthouse's software-GL rendering: long tasks (> 50 ms) during load plus the opening on the home, and during load on a
// case page, at a phone viewport. NODE_PATH=$(npm root -g) node throttled.cjs
// Output folder: $EVIDENCE_OUT, default ~/projects-site-evidence/atelier-2026-10-25 (outside the repository; packaged by tools/package.sh).
const OUT = process.env.EVIDENCE_OUT || require('path').join(require('os').homedir(), 'projects-site-evidence', 'atelier-2026-10-25');
const { chromium } = require('playwright'); const fs = require('fs'); const path = require('path');
(async () => {
  const b = await chromium.launch({ args: ['--use-angle=metal', '--ignore-gpu-blocklist'] }); const out = {};
  for (const [name, url, vp, mobile] of [['home-phone', 'index.html', { width: 390, height: 844 }, true], ['home-desktop', 'index.html', { width: 1440, height: 900 }, false], ['case-phone', 'florida-flight-delays/', { width: 390, height: 844 }, true]]) {
    const ctx = await b.newContext({ viewport: vp, deviceScaleFactor: mobile ? 3 : 2, isMobile: mobile, hasTouch: mobile }); const p = await ctx.newPage();
    const cdp = await ctx.newCDPSession(p); await cdp.send('Emulation.setCPUThrottlingRate', { rate: 4 });
    await p.addInitScript(() => { window.__long = []; new PerformanceObserver(l => { for (const e of l.getEntries()) window.__long.push([Math.round(e.startTime), Math.round(e.duration), (e.attribution && e.attribution[0] && e.attribution[0].containerSrc) || '']); }).observe({ type: 'longtask', buffered: true }); });
    const t0 = Date.now(); await p.goto('http://127.0.0.1:8800/' + url, { waitUntil: 'load' }); await p.waitForTimeout(4500);
    const r = await p.evaluate(() => ({ long: window.__long, tbtLike: window.__long.reduce((s, [, d]) => s + Math.max(0, d - 50), 0), glOn: document.documentElement.classList.contains('gl-on'), entered: document.documentElement.classList.contains('entered'), dpr: devicePixelRatio }));
    r.wallMs = Date.now() - t0; out[name] = r; console.log(name, JSON.stringify(r)); await ctx.close();
  }
  await b.close(); fs.writeFileSync(path.join(OUT, 'throttled.json'), JSON.stringify(out, null, 2));
})();
