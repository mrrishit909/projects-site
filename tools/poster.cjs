// The art-directed poster: the block in its hero pose, rendered by the real scene and saved with transparency, so the
// first paint and browsers without WebGL show the same object. Writes assets/block-poster.webp (1440x900) and
// assets/block-poster-m.webp (390x844). Needs the local server on 8800, Playwright's Chromium and cwebp.
// NODE_PATH=$(npm root -g) node tools/poster.cjs
const { chromium } = require('playwright'); const { execFileSync } = require('child_process'); const path = require('path'); const fs = require('fs');
const ROOT = path.join(__dirname, '..');
(async () => {
  const b = await chromium.launch({ args: ['--use-angle=metal', '--ignore-gpu-blocklist'] });
  for (const [name, vp, mobile] of [['block-poster', { width: 1440, height: 900 }, false], ['block-poster-m', { width: 390, height: 844 }, true]]) {
    const ctx = await b.newContext({ viewport: vp, deviceScaleFactor: 1, isMobile: mobile, hasTouch: mobile });
    const p = await ctx.newPage();
    await p.addInitScript(() => { try { sessionStorage.setItem('seen', '1'); } catch (_) {} });
    await p.goto('http://127.0.0.1:8800/index.html', { waitUntil: 'load' }); await p.waitForTimeout(2600);
    await p.addStyleTag({ content: 'html, body { background: transparent !important; } main, header, footer, .hud-chapter, .skip-intro, .poster { visibility: hidden !important; }' });
    await p.waitForTimeout(400);
    const png = path.join(ROOT, 'assets', name + '.png'), webp = path.join(ROOT, 'assets', name + '.webp');
    await p.screenshot({ path: png, omitBackground: true });
    execFileSync('cwebp', ['-q', '82', '-alpha_q', '90', '-quiet', png, '-o', webp]); fs.unlinkSync(png);
    console.log(name, fs.statSync(webp).size, 'bytes');
    await ctx.close();
  }
  await b.close();
})();
