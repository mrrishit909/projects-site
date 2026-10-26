// Frame pacing of the Precision Atelier home on this Mac (Playwright Chromium, GPU via ANGLE Metal): the opening, a slow
// 14 s scroll down, a fast flick, a reverse scroll, a drag, the arrangement controls, a case-study entry and Back, a
// resize. Reports frame-time distributions (p50/p95/p99, max, long frames) and the JS heap, at desktop 2x and a phone
// viewport (viewport emulation, not a real device). NODE_PATH=$(npm root -g) node pace.cjs
// Output folder: $EVIDENCE_OUT, default ~/projects-site-evidence/atelier-2026-10-25 (outside the repository; packaged by tools/package.sh).
const OUT = process.env.EVIDENCE_OUT || require('path').join(require('os').homedir(), 'projects-site-evidence', 'atelier-2026-10-25');
const { chromium } = require('playwright'); const fs = require('fs'); const path = require('path');
const stats = d => { d = d.slice().sort((a, b) => a - b); const q = f => +d[Math.min(d.length - 1, Math.floor(d.length * f))].toFixed(1); return { frames: d.length, p50: q(0.5), p95: q(0.95), p99: q(0.99), max: +d[d.length - 1].toFixed(1), over20: d.filter(x => x > 20).length, over33: d.filter(x => x > 33).length, over50: d.filter(x => x > 50).length }; };
const sample = (p, ms) => p.evaluate(ms => new Promise(res => { const d = []; let last = performance.now(); const t0 = last; const step = now => { d.push(now - last); last = now; if (now - t0 < ms) requestAnimationFrame(step); else res(d); }; requestAnimationFrame(step); }), ms);
const smooth = (p, from, to, ms) => p.evaluate(([a, b, ms]) => new Promise(res => { const d = []; let last = performance.now(); const t0 = last; const step = now => { d.push(now - last); last = now; const u = Math.min(1, (now - t0) / ms); scrollTo(0, a + (b - a) * (u * u * (3 - 2 * u))); if (u < 1) requestAnimationFrame(step); else res(d); }; requestAnimationFrame(step); }), [from, to, ms]);
const heap = p => p.evaluate(() => performance.memory ? Math.round(performance.memory.usedJSHeapSize / 1048576) : null);
(async () => {
  const b = await chromium.launch({ args: ['--use-angle=metal', '--ignore-gpu-blocklist', '--enable-precise-memory-info'] }); const out = { machine: 'Apple M3 Pro, macOS, Chromium via Playwright, ANGLE Metal, 60 Hz display', date: new Date().toISOString() };
  for (const [name, vp, mobile, dsf] of [['desktop-1440x900@2x', { width: 1440, height: 900 }, false, 2], ['phone-390x844@3x-emulated', { width: 390, height: 844 }, true, 3]]) {
    const ctx = await b.newContext({ viewport: vp, deviceScaleFactor: dsf, isMobile: mobile, hasTouch: mobile }); const p = await ctx.newPage(); const r = {};
    await p.goto('http://127.0.0.1:8800/index.html', { waitUntil: 'commit' });
    r.opening = stats(await sample(p, 3400)); r.heapAfterOpening = await heap(p);
    const H = await p.evaluate(() => document.body.scrollHeight - innerHeight);
    r.slowScrollDown = stats(await smooth(p, 0, H, 14000));
    r.flickUp = stats(await smooth(p, H, 0, 700));
    r.reverseScroll = stats(await smooth(p, 0, H * 0.6, 4000).then(a => smooth(p, H * 0.6, H * 0.2, 2500).then(b => a.concat(b))));
    if (!mobile) { await p.evaluate(() => scrollTo(0, 0)); await p.waitForTimeout(400); await p.mouse.move(1000, 450); await p.mouse.down(); const dragP = sample(p, 1500); for (let i = 0; i < 30; i++) { await p.mouse.move(1000 + i * 8, 450 + Math.sin(i / 5) * 20); await p.waitForTimeout(40); } await p.mouse.up(); r.drag = stats(await dragP); }
    await p.evaluate(() => document.getElementById('system').scrollIntoView({ behavior: 'instant' })); await p.waitForTimeout(300);
    const cfgP = sample(p, 3000); for (const c of ['network', 'pipeline', 'timeline', 'documents', 'open']) { await p.click(`[data-config=${c}]`); await p.waitForTimeout(550); } r.arrangementControls = stats(await cfgP);
    const sepP = sample(p, 1500); for (let i = 0; i <= 10; i++) { await p.evaluate(v => { const s = document.getElementById('separate'); s.value = v; s.dispatchEvent(new Event('input', { bubbles: true })); }, (10 - i) / 10); await p.waitForTimeout(120); } r.separateSlider = stats(await sepP);
    await p.evaluate(() => document.getElementById('feature-florida-flight-delays').scrollIntoView({ behavior: 'instant' })); await p.waitForTimeout(600);
    const t0 = Date.now(); await p.evaluate(() => document.querySelector('#feature-florida-flight-delays .btns a.fill').click()); await p.waitForLoadState('load'); r.caseEntryMs = Date.now() - t0; await p.waitForTimeout(1500); r.caseInstrument = stats(await sample(p, 2000)); r.heapOnCase = await heap(p);
    const t1 = Date.now(); await p.goBack(); await p.waitForLoadState('load'); r.backMs = Date.now() - t1; await p.waitForTimeout(600); r.afterBack = stats(await sample(p, 2000)); r.heapAfterBack = await heap(p);
    const rsP = sample(p, 1500); for (const w of [1200, 1000, 1300, vp.width]) { await p.setViewportSize({ width: w, height: vp.height }); await p.waitForTimeout(300); } r.resize = stats(await rsP);
    r.loops = await p.evaluate(() => new Promise(res => { let n = 0; const t0 = performance.now(); const o = requestAnimationFrame; let cnt = 0; const id = setInterval(() => { }, 1000); const step = () => { cnt++; if (performance.now() - t0 < 1000) o(step); else { clearInterval(id); res(cnt); } }; o(step); }));
    r.dpr = await p.evaluate(() => devicePixelRatio);
    out[name] = r; console.log(name, JSON.stringify(r)); await ctx.close();
  }
  await b.close(); fs.writeFileSync(path.join(OUT, 'pace.json'), JSON.stringify(out, null, 2)); console.log('pace.json written');
})();
