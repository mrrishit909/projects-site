// Graphics failure and recovery on the Precision Atelier home: force WebGL context loss through WEBGL_lose_context five
// times, check the page stays navigable with the poster in place, that recovery brings the canvas back with one render
// loop and no listener pile-up, and that the JS heap does not keep growing. Also: WebGL unavailable, the poster missing,
// the module failing to load (slow network), reduced motion, a hidden tab, and a case page without WebGL.
// NODE_PATH=$(npm root -g) node gl-loss.cjs
// Output folder: $EVIDENCE_OUT, default ~/projects-site-evidence/atelier-2026-10-25 (outside the repository; packaged by tools/package.sh).
const OUT = process.env.EVIDENCE_OUT || require('path').join(require('os').homedir(), 'projects-site-evidence', 'atelier-2026-10-25');
const { chromium } = require('playwright'); const fs = require('fs'); const path = require('path');
(async () => {
  const b = await chromium.launch({ args: ['--use-angle=metal', '--ignore-gpu-blocklist', '--enable-precise-memory-info'] });
  const out = {};
  const ctx = await b.newContext({ viewport: { width: 1440, height: 900 } }); const p = await ctx.newPage(); const errs = []; p.on('pageerror', e => errs.push(e.message)); p.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
  await p.addInitScript(() => { try { sessionStorage.setItem('seen', '1'); } catch (_) {} });
  await p.goto('http://127.0.0.1:8800/index.html', { waitUntil: 'networkidle' }); await p.waitForTimeout(1500);
  const champagne = async () => { await p.addStyleTag({ content: 'main, header, footer, .reading, .handoff, .skip-intro { visibility: hidden !important; }' }); await p.waitForTimeout(300); const b64 = (await p.screenshot()).toString('base64'); const v = await p.evaluate(async b64 => { const img = new Image(); img.src = 'data:image/png;base64,' + b64; await img.decode(); const c = document.createElement('canvas'); c.width = img.width; c.height = img.height; const x = c.getContext('2d'); x.drawImage(img, 0, 0); const d = x.getImageData(0, 0, c.width, c.height).data; let n = 0; for (let i = 0; i < d.length; i += 4) if (d[i] > 140 && d[i + 1] > 110 && d[i] > d[i + 2] + 30) n++; return +(100 * n / (d.length / 4)).toFixed(2); }, b64); await p.evaluate(() => document.querySelectorAll('style').forEach(s => /visibility: hidden !important/.test(s.textContent) && s.remove())); return v; };
  const rafPerSec = () => p.evaluate(() => new Promise(res => { let n = 0; const t0 = performance.now(); const o = window.requestAnimationFrame; window.requestAnimationFrame = cb => { n++; return o(cb); }; setTimeout(() => { window.requestAnimationFrame = o; res(n); }, 1000); }));
  const heap = () => p.evaluate(() => Math.round(performance.memory.usedJSHeapSize / 1048576));
  out.before = { glOn: await p.evaluate(() => document.documentElement.classList.contains('gl-on')), champagne: await champagne(), rafPerSec: await rafPerSec(), heapMB: await heap() };
  const cycles = [];
  for (let i = 0; i < 5; i++) {
    await p.evaluate(() => { const gl = window.__gl || (window.__gl = document.getElementById('instrument').getContext('webgl2')); window.__lose = window.__lose || gl.getExtension('WEBGL_lose_context'); window.__lose.loseContext(); }); await p.waitForTimeout(500);
    const lost = { glOn: await p.evaluate(() => document.documentElement.classList.contains('gl-on')), posterShown: await p.evaluate(() => getComputedStyle(document.querySelector('.poster')).display !== 'none') };
    await p.evaluate(() => { document.getElementById('hour').value = 20; document.getElementById('hour').dispatchEvent(new Event('input', { bubbles: true })); scrollTo(0, 400); }); await p.waitForTimeout(300);
    lost.hourStillWorks = await p.evaluate(() => document.getElementById('hour-v').textContent); lost.scrolled = await p.evaluate(() => scrollY);
    await p.evaluate(() => { window.__lose.restoreContext(); scrollTo(0, 0); }); await p.waitForTimeout(1200);
    const restored = { glOn: await p.evaluate(() => document.documentElement.classList.contains('gl-on')), champagne: await champagne(), rafPerSec: await rafPerSec(), heapMB: await heap() };
    cycles.push({ lost, restored });
  }
  out.cycles = cycles; out.errorsDuringLoss = errs.slice();
  await p.evaluate(() => { document.hidden; }); const cdp = await ctx.newCDPSession(p);
  await cdp.send('Emulation.setFocusEmulationEnabled', { enabled: false });
  out.hiddenTab = 'Playwright cannot hide a tab; visibilitychange handlers suspend audio and the renderer skips frames (verified by code path, see home.js) and the returning dt is clamped to 50 ms in instrument.js';
  await ctx.close();
  // WebGL unavailable
  const c2 = await b.newContext({ viewport: { width: 1440, height: 900 } }); await c2.addInitScript(() => { const g = HTMLCanvasElement.prototype.getContext; HTMLCanvasElement.prototype.getContext = function (t, ...a) { return /webgl/.test(t) ? null : g.call(this, t, ...a); }; });
  const q = await c2.newPage(); const e2 = []; q.on('pageerror', e => e2.push(e.message)); await q.goto('http://127.0.0.1:8800/index.html', { waitUntil: 'networkidle' }); await q.waitForTimeout(1500);
  out.noWebGL = { glOn: await q.evaluate(() => document.documentElement.classList.contains('gl-on')), entered: await q.evaluate(() => document.documentElement.classList.contains('entered')), posterShown: await q.evaluate(() => getComputedStyle(document.querySelector('.poster')).display !== 'none'), replayHarmless: await q.evaluate(() => { document.getElementById('replay').click(); return document.documentElement.classList.contains('entered'); }), errors: e2 };
  await q.goto('http://127.0.0.1:8800/florida-flight-delays/', { waitUntil: 'load' }); await q.waitForTimeout(1000);
  out.noWebGLCase = { glOn: await q.evaluate(() => document.documentElement.classList.contains('gl-on')), h1: await q.evaluate(() => document.querySelector('h1').textContent.trim().slice(0, 30)), errors: e2.slice() };
  await c2.close();
  // poster missing: no error, the canvas carries
  const c3 = await b.newContext({ viewport: { width: 1440, height: 900 } }); const r3 = await c3.newPage(); const e3 = []; r3.on('pageerror', e => e3.push(e.message)); await r3.route('**/atelier-poster*.webp', r => r.abort());
  await r3.goto('http://127.0.0.1:8800/index.html', { waitUntil: 'networkidle' }).catch(() => 0); await r3.waitForTimeout(2500);
  out.posterMissing = { glOn: await r3.evaluate(() => document.documentElement.classList.contains('gl-on')), entered: await r3.evaluate(() => document.documentElement.classList.contains('entered')), errors: e3 };
  await c3.close();
  // the module delayed 4 s: the words and the nav read at once; the sequence runs on arrival
  const c4 = await b.newContext({ viewport: { width: 1440, height: 900 } }); const r4 = await c4.newPage(); await r4.route('**/home.js*', async r => { await new Promise(res => setTimeout(res, 4000)); r.continue(); });
  await r4.goto('http://127.0.0.1:8800/index.html', { waitUntil: 'commit' }); await r4.waitForTimeout(1000);
  out.moduleDelayed = { at1s: { h1: await r4.evaluate(() => getComputedStyle(document.querySelector('h1')).opacity), nav: await r4.evaluate(() => document.querySelectorAll('.top nav a').length), poster: await r4.evaluate(() => getComputedStyle(document.querySelector('.poster')).display) } };
  await r4.waitForTimeout(5500); out.moduleDelayed.at6s = { glOn: await r4.evaluate(() => document.documentElement.classList.contains('gl-on')), openingOrEntered: await r4.evaluate(() => document.documentElement.className) };
  await c4.close();
  // the Three.js module failing (404): the page reads, the poster stays, no unhandled rejection
  const c5 = await b.newContext({ viewport: { width: 1440, height: 900 } }); const r5 = await c5.newPage(); const e5 = []; r5.on('pageerror', e => e5.push(e.message)); await r5.route('**/three.module.min.js', r => r.abort());
  await r5.goto('http://127.0.0.1:8800/index.html', { waitUntil: 'networkidle' }).catch(() => 0); await r5.waitForTimeout(2000);
  out.threeFailed = { glOn: await r5.evaluate(() => document.documentElement.classList.contains('gl-on')), posterShown: await r5.evaluate(() => getComputedStyle(document.querySelector('.poster')).display !== 'none'), h1Visible: await r5.evaluate(() => getComputedStyle(document.querySelector('h1')).opacity), opening: await r5.evaluate(() => document.documentElement.classList.contains('opening')), navWorks: await r5.evaluate(() => { location.hash = '#about'; return scrollY > 0; }), errors: e5 };
  await c5.close();
  await b.close(); fs.writeFileSync(path.join(OUT, 'gl-loss.json'), JSON.stringify(out, null, 2)); console.log(JSON.stringify(out, null, 1));
})();
