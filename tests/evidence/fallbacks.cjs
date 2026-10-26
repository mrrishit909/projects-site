// Fallback presentations, captured: the home under cold load, a delayed module, no JavaScript, no WebGL, context loss and a
// missing poster, at desktop, phone and two intermediate aspects; four case pages (flagship, long title, thin, archive
// project) under no WebGL, a failed instrument import, slow assets, no JavaScript, reduced motion, and narrow / short
// viewports. Writes PNGs plus fallbacks.json (overflow, the still's natural size, the canvas state) to $EVIDENCE_OUT/fallbacks/.
// NODE_PATH=$(npm root -g) node tests/evidence/fallbacks.cjs
const OUT = process.env.EVIDENCE_OUT || require('path').join(require('os').homedir(), 'projects-site-evidence', 'atelier-2026-10-25');
const { chromium } = require('playwright'); const fs = require('fs'); const path = require('path');
const dir = path.join(OUT, 'fallbacks'); fs.mkdirSync(dir, { recursive: true });
const BASE = 'http://127.0.0.1:8800/';
const noGl = () => { const g = HTMLCanvasElement.prototype.getContext; HTMLCanvasElement.prototype.getContext = function (t, ...a) { return /webgl/.test(t) ? null : g.call(this, t, ...a); }; };
(async () => {
  const b = await chromium.launch({ args: ['--use-angle=metal', '--ignore-gpu-blocklist'] }); const out = {};
  const state = p => p.evaluate(() => ({ sw: document.documentElement.scrollWidth, cls: document.documentElement.className.trim(), poster: (() => { const i = document.querySelector('.poster img, .object-still'); return i ? [getComputedStyle(i).display, i.naturalWidth, i.complete] : null; })(), canvas: (() => { const c = document.querySelector('canvas.instrument, .case-canvas'); return c ? [getComputedStyle(c).display, c.width] : null; })(), h1: getComputedStyle(document.querySelector('h1')).opacity }));
  const shot = async (p, name) => { await p.screenshot({ path: path.join(dir, name + '.png') }); out[name] = await state(p); };
  const VIEWS = [['d', { width: 1440, height: 900 }], ['m', { width: 390, height: 844 }], ['sq', { width: 1024, height: 1024 }], ['wide', { width: 1920, height: 820 }]];
  // the home, six conditions
  for (const [v, vp] of VIEWS) {
    const mk = async (opts = {}, init = null, route = null) => { const ctx = await b.newContext({ viewport: vp, isMobile: v === 'm', hasTouch: v === 'm', ...opts }); if (init) await ctx.addInitScript(init); const p = await ctx.newPage(); if (route) await route(p); return [ctx, p]; };
    let [ctx, p] = await mk(); await p.goto(BASE, { waitUntil: 'commit' }); await p.waitForTimeout(200); await shot(p, `home-${v}-cold-200ms`); await p.waitForTimeout(4000); await shot(p, `home-${v}-cold-settled`); await ctx.close();
    [ctx, p] = await mk({}, null, p => p.route('**/home.js*', async r => { await new Promise(res => setTimeout(res, 3500)); r.continue(); })); await p.goto(BASE, { waitUntil: 'commit' }); await p.waitForTimeout(1200); await shot(p, `home-${v}-module-delayed-1s`); await ctx.close();
    [ctx, p] = await mk({ javaScriptEnabled: false }); await p.goto(BASE, { waitUntil: 'load' }); await p.waitForTimeout(600); await shot(p, `home-${v}-nojs`); await p.evaluate(() => scrollTo(0, document.body.scrollHeight * 0.55)); await p.waitForTimeout(300); await shot(p, `home-${v}-nojs-mid`); await ctx.close();
    [ctx, p] = await mk({}, noGl); await p.goto(BASE, { waitUntil: 'networkidle' }); await p.waitForTimeout(1200); await shot(p, `home-${v}-nowebgl`); await ctx.close();
    [ctx, p] = await mk({}, () => { try { sessionStorage.setItem('seen', '1'); } catch (_) {} }); await p.goto(BASE, { waitUntil: 'networkidle' }); await p.waitForTimeout(1200);
    await p.evaluate(() => { const gl = document.getElementById('instrument').getContext('webgl2'); window.__lose = gl.getExtension('WEBGL_lose_context'); window.__lose.loseContext(); }); await p.waitForTimeout(500); await shot(p, `home-${v}-context-lost`);
    await p.evaluate(() => window.__lose.restoreContext()); await p.waitForTimeout(1500); await shot(p, `home-${v}-context-restored`); await ctx.close();
    [ctx, p] = await mk({}, noGl, p => p.route('**/atelier-poster*.webp', r => r.abort())); await p.goto(BASE, { waitUntil: 'networkidle' }).catch(() => 0); await p.waitForTimeout(1200); await shot(p, `home-${v}-poster-missing-nowebgl`); await ctx.close();
  }
  // four case pages, seven conditions
  const PAGES = [['flagship', 'florida-flight-delays/'], ['long', 'workforce-scheduler/'], ['thin', 'iris-fisher/'], ['archive', 'twenty-crm/']];
  for (const [k, url] of PAGES) for (const [v, vp] of [['d', { width: 1440, height: 900 }], ['m', { width: 390, height: 844 }], ['short', { width: 390, height: 640 }], ['narrow', { width: 320, height: 700 }]]) {
    const mk = async (opts = {}, init = null, route = null) => { const ctx = await b.newContext({ viewport: vp, isMobile: v !== 'd', hasTouch: v !== 'd', ...opts }); if (init) await ctx.addInitScript(init); const p = await ctx.newPage(); if (route) await route(p); return [ctx, p]; };
    let [ctx, p] = await mk({}, noGl); await p.goto(BASE + url, { waitUntil: 'load' }); await p.waitForTimeout(1200); await shot(p, `case-${k}-${v}-nowebgl`); await ctx.close();
    if (v === 'd' || v === 'm') {
      [ctx, p] = await mk({}, null, p => p.route('**/instrument.js*', r => r.abort())); await p.goto(BASE + url, { waitUntil: 'load' }).catch(() => 0); await p.waitForTimeout(1500); await shot(p, `case-${k}-${v}-import-failed`); await ctx.close();
      [ctx, p] = await mk({}, null, p => p.route('**/*.{webp,jpg,js}', async r => { await new Promise(res => setTimeout(res, 1500)); r.continue(); })); await p.goto(BASE + url, { waitUntil: 'commit' }).catch(() => 0); await p.waitForTimeout(700); await shot(p, `case-${k}-${v}-slow-700ms`); await ctx.close();
      [ctx, p] = await mk({ javaScriptEnabled: false }); await p.goto(BASE + url, { waitUntil: 'load' }); await p.waitForTimeout(500); await shot(p, `case-${k}-${v}-nojs`); await ctx.close();
      [ctx, p] = await mk({ reducedMotion: 'reduce' }); await p.goto(BASE + url, { waitUntil: 'networkidle' }); await p.waitForTimeout(1500); await shot(p, `case-${k}-${v}-reduced`); await ctx.close();
    }
  }
  await b.close(); fs.writeFileSync(path.join(dir, 'fallbacks.json'), JSON.stringify(out, null, 2));
  const over = Object.entries(out).filter(([k, v]) => v.sw > ({ d: 1440, m: 390, sq: 1024, wide: 1920, short: 390, narrow: 320 })[k.split('-').find(x => ['d', 'm', 'sq', 'wide', 'short', 'narrow'].includes(x))]);
  console.log(Object.keys(out).length, 'captures;', over.length ? 'OVERFLOW: ' + over.map(([k]) => k).join(', ') : 'no horizontal overflow');
})();
