// The hero poster: the instrument in its exploded hero arrangement, rendered with alpha from the lab at the home's stage
// (desktop 1440x900 at 70% / 52%, phone 390x844 at 50% / 27%), for the first paint and for browsers without WebGL.
// NODE_PATH=$(npm root -g) node tools/poster.cjs   (needs the local server on 8800 and cwebp)
const { chromium } = require('playwright'); const { execSync } = require('child_process'); const path = require('path');
(async () => {
  const b = await chromium.launch({ args: ['--use-angle=metal', '--ignore-gpu-blocklist'] });
  for (const [name, vp, q] of [['atelier-poster', { width: 1440, height: 900 }, 'sx=0.71&sy=0.52&ss=1'], ['atelier-poster-m', { width: 390, height: 844 }, 'sx=0.5&sy=0.27&ss=0.62']]) {
    const ctx = await b.newContext({ viewport: vp, deviceScaleFactor: 1 }); const p = await ctx.newPage();
    await p.goto(`http://127.0.0.1:8800/motion/instrument-lab.html?state=open&poster=1&${q}`, { waitUntil: 'networkidle' }); await p.waitForTimeout(3000);
    const png = path.join(__dirname, '..', 'assets', name + '.png'); await p.screenshot({ path: png, omitBackground: true });
    execSync(`cwebp -q 82 -alpha_q 90 "${png}" -o "${png.replace('.png', '.webp')}"`); execSync(`rm "${png}"`); await ctx.close();
  }
  await b.close(); console.log('posters written');
})();
