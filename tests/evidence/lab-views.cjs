// Views of the instrument from the lab (motion/instrument-lab.html) for comparison with the concept image: assembled,
// partly opened, exploded, the close-up of the dial (opening shot 1), the network at two hours, the explode mid-way with
// the lead order, front and side views. Writes <out>/<name>.png and a contact sheet listing.
// NODE_PATH=$(npm root -g) node tests/evidence/lab-views.cjs <outdir>
const OUT = process.argv[2] || require('path').join(require('os').homedir(), 'projects-site-evidence', 'atelier-2026-10-25', 'refine', 'lab');
const { chromium } = require('playwright'); const fs = require('fs'); const path = require('path');
fs.mkdirSync(OUT, { recursive: true });
const BASE = 'http://127.0.0.1:8800/motion/instrument-lab.html?poster=1&';
const VIEWS = {
  'assembled': 'state=closed&ry=-0.5&rx=0.16',
  'partly-open': 'state=closed&next=open&u=0.5&lead=1&ry=-0.5&rx=0.16',
  'exploded': 'state=closed&next=open&u=1&ry=-0.5&rx=0.16',
  'exploded-front': 'state=closed&next=open&u=1&ry=0&rx=0.08',
  'exploded-side': 'state=closed&next=open&u=1&ry=-1.45&rx=0.1',
  'closeup-dial-start': 'state=closed&k=0&d=0&ry=-0.95&rx=0.05&ss=2.3&sx=0.7&sy=0.38',
  'closeup-dial-aligned': 'state=closed&k=0.5&d=1&ry=-0.95&rx=0.05&ss=2.3&sx=0.7&sy=0.38',
  'closeup-seated': 'state=closed&k=1&d=1&ry=-0.95&rx=0.05&ss=2.3&sx=0.7&sy=0.38',
  'closeup-head': 'state=closed&ry=-0.3&rx=0.1&ss=1.9&sx=0.72&sy=0.8',
  'network-8am': 'state=network&arg=8&arg2=0.11&ry=-0.22&rx=0.14&ss=0.95',
  'network-8pm': 'state=network&arg=20&arg2=0.6&ry=-0.22&rx=0.14&ss=0.95',
  'network-forming': 'state=closed&next=network&u=0.45&arg=8&nextArg=8&ry=-0.22&rx=0.14&ss=0.95',
  'explode-lead-035': 'state=closed&next=open&u=0.35&lead=1&ry=-0.6&rx=0.12&ss=1.3',
  'explode-lead-070': 'state=closed&next=open&u=0.7&lead=1&ry=-0.6&rx=0.12&ss=1.3',
};
(async () => {
  const b = await chromium.launch({ args: ['--use-angle=metal', '--ignore-gpu-blocklist'] });
  const ctx = await b.newContext({ viewport: { width: 1200, height: 900 }, deviceScaleFactor: 2 });
  const p = await ctx.newPage(); const errors = []; p.on('pageerror', e => errors.push(e.message)); p.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  for (const [name, q] of Object.entries(VIEWS)) {
    await p.goto(BASE + q + '&ground=green', { waitUntil: 'networkidle' }); await p.waitForTimeout(1500);
    await p.evaluate(() => { document.body.style.background = '#071d16'; }); await p.waitForTimeout(200);
    await p.screenshot({ path: path.join(OUT, name + '.png') });
    const info = await p.evaluate(() => window.inst && window.inst.info()); console.log(name, JSON.stringify(info));
  }
  console.log('errors:', errors.length ? errors.join(' | ') : 'none');
  await b.close();
})();
