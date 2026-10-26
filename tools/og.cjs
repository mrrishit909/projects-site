// The social preview image: the home's settled hero at 1200x630 (the exploded instrument beside the statement), written to
// assets/og-index.jpg. NODE_PATH=$(npm root -g) node tools/og.cjs   (needs the local server on 8800)
const { chromium } = require('playwright'); const path = require('path');
(async () => {
  const b = await chromium.launch({ args: ['--use-angle=metal', '--ignore-gpu-blocklist'] });
  const ctx = await b.newContext({ viewport: { width: 1200, height: 630 }, deviceScaleFactor: 1 }); await ctx.addInitScript(() => { try { sessionStorage.setItem('seen', '1'); } catch (_) {} });
  const p = await ctx.newPage(); await p.goto('http://127.0.0.1:8800/index.html', { waitUntil: 'networkidle' }); await p.waitForTimeout(2500);
  await p.addStyleTag({ content: '.top, .skip-intro, .hero .foot-lines { visibility: hidden !important; }' }); await p.waitForTimeout(200);
  await p.screenshot({ path: path.join(__dirname, '..', 'assets', 'og-index.jpg'), type: 'jpeg', quality: 86 });
  await b.close(); console.log('og-index.jpg written');
})();
