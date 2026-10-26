// Stills of the instrument in each arrangement, with alpha, for the case-study hero before WebGL and without it
// (assets/config-<state>.webp). Rendered from the lab at the case page's camera; the same clean-export checks as the
// home poster. NODE_PATH=$(npm root -g) node tools/config-posters.cjs   (needs the local server on 8800 and cwebp)
const { chromium } = require('playwright'); const { execSync } = require('child_process'); const path = require('path');
const STATES = { closed: 'ry=-0.45&ss=0.95', open: 'ry=-0.45&ss=0.95', network: 'ry=-0.2&ss=0.95', pipeline: 'ry=-0.45&ss=0.78', timeline: 'ry=-0.45&ss=0.78', documents: 'ry=-0.45&ss=0.95&u=0.5' };
(async () => {
  const b = await chromium.launch({ args: ['--use-angle=metal', '--ignore-gpu-blocklist'] });
  const ctx = await b.newContext({ viewport: { width: 900, height: 640 }, deviceScaleFactor: 1 });
  for (const [state, q] of Object.entries(STATES)) {
    const p = await ctx.newPage();
    await p.goto(`http://127.0.0.1:8800/motion/instrument-lab.html?state=${state}&arg=31&poster=1&sx=0.5&sy=0.5&rx=0.14&${q}`, { waitUntil: 'networkidle' }); await p.waitForTimeout(2800);
    const clean = await p.evaluate(() => getComputedStyle(document.querySelector('.ui')).display === 'none' && getComputedStyle(document.documentElement).backgroundColor === 'rgba(0, 0, 0, 0)');
    if (!clean) { console.error(state + ': export refused, the lab is not in poster mode'); process.exit(1); }
    const png = path.join(__dirname, '..', 'assets', `config-${state}.png`); await p.screenshot({ path: png, omitBackground: true });
    execSync(`cwebp -quiet -q 80 -alpha_q 90 "${png}" -o "${png.replace('.png', '.webp')}"`); execSync(`rm "${png}"`); await p.close(); console.log('wrote', state);
  }
  await b.close();
})();
