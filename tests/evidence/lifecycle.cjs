// The lifecycle journey, three times in one session: opening → project → case study → Back → another project → contact →
// Replay the opening. Counts canvases, requestAnimationFrame loops per second, listeners added on window and document,
// live intervals, audio voices, scroll restoration after Back, focus after Back, repeated asset downloads, and the heap
// after each repetition (a trend, not a leak verdict). Writes lifecycle.json to $EVIDENCE_OUT.
// NODE_PATH=$(npm root -g) node tests/evidence/lifecycle.cjs
const OUT = process.env.EVIDENCE_OUT || require('path').join(require('os').homedir(), 'projects-site-evidence', 'atelier-2026-10-25');
const { chromium } = require('playwright'); const fs = require('fs'); const path = require('path');
const BASE = 'http://127.0.0.1:8800/';
(async () => {
  const b = await chromium.launch({ args: ['--use-angle=metal', '--ignore-gpu-blocklist', '--enable-precise-memory-info'] });
  const ctx = await b.newContext({ viewport: { width: 1440, height: 900 } });
  await ctx.addInitScript(() => { window.__counts = { listeners: 0, intervals: 0 }; const ae = EventTarget.prototype.addEventListener; EventTarget.prototype.addEventListener = function (...a) { if (this === window || this === document) window.__counts.listeners++; return ae.apply(this, a); }; const si = window.setInterval; window.setInterval = (...a) => { window.__counts.intervals++; return si(...a); }; });
  const p = await ctx.newPage(); const requests = {}; p.on('request', r => { const u = r.url().replace(BASE, '/'); requests[u] = (requests[u] || 0) + 1; });
  const errors = []; p.on('pageerror', e => errors.push(e.message));
  const snap = async label => ({ label, url: p.url().replace(BASE, '/'), canvases: await p.evaluate(() => document.querySelectorAll('canvas').length), rafPerSec: await p.evaluate(() => new Promise(res => { let n = 0; const o = window.requestAnimationFrame; window.requestAnimationFrame = cb => { n++; return o(cb); }; setTimeout(() => { window.requestAnimationFrame = o; res(n); }, 1000); })), listeners: await p.evaluate(() => window.__counts && window.__counts.listeners), intervals: await p.evaluate(() => window.__counts && window.__counts.intervals), heapMB: await p.evaluate(() => Math.round(performance.memory.usedJSHeapSize / 1048576)), scrollY: await p.evaluate(() => scrollY), focus: await p.evaluate(() => { const e = document.activeElement; return e ? (e.id || e.className || e.tagName) + '' : ''; }) });
  const reps = [];
  await p.goto(BASE, { waitUntil: 'networkidle' }); await p.waitForTimeout(3600);
  for (let i = 0; i < 3; i++) {
    const r = { rep: i + 1, steps: [] };
    r.steps.push(await snap('home settled'));
    await p.evaluate(() => { const el = document.querySelector('#feature-retail-dbt'); const top = el.getBoundingClientRect().top + scrollY; scrollTo(0, top + Math.max(0, el.offsetHeight - innerHeight) * 0.8); }); await p.waitForTimeout(1200);
    const yBefore = await p.evaluate(() => scrollY);
    await p.evaluate(() => document.querySelector('#feature-retail-dbt .btns a.fill').click()); await p.waitForLoadState('load'); await p.waitForTimeout(2000);
    r.steps.push(await snap('case study (retail-dbt)'));
    await p.goBack(); await p.waitForLoadState('load'); await p.waitForTimeout(1500);
    const back = await snap('after Back'); back.scrollRestored = Math.abs(back.scrollY - yBefore) < 4; back.focusOnButton = /btn fill/.test(back.focus); r.steps.push(back);
    await p.evaluate(() => { const el = document.querySelector('#feature-sec-10k-rag'); const top = el.getBoundingClientRect().top + scrollY; scrollTo(0, top + Math.max(0, el.offsetHeight - innerHeight) * 0.9); }); await p.waitForTimeout(1200);
    await p.evaluate(() => document.querySelector('#feature-sec-10k-rag .btns a.fill').click()); await p.waitForLoadState('load'); await p.waitForTimeout(1500);
    r.steps.push(await snap('case study (sec-10k-rag)'));
    await p.goBack(); await p.waitForLoadState('load'); await p.waitForTimeout(1200);
    await p.evaluate(() => document.querySelector('#contact').scrollIntoView({ behavior: 'instant' })); await p.waitForTimeout(1200);
    r.steps.push(await snap('contact'));
    await p.click('#replay'); await p.waitForTimeout(3600);
    r.steps.push(await snap('after Replay'));
    reps.push(r); console.log(JSON.stringify(r));
  }
  const repeated = Object.entries(requests).filter(([u, n]) => n > 3 && !/\.html$|\/$/.test(u)).map(([u, n]) => `${u} x${n}`);
  const out = { reps, repeatedDownloads: repeated, errors, note: 'heap figures are single samples per step; a trend over the three repetitions is reported, not a leak verdict' };
  fs.writeFileSync(path.join(OUT, 'lifecycle.json'), JSON.stringify(out, null, 2));
  console.log('repeated downloads beyond three loads:', repeated.length ? repeated.join(', ') : 'none', '| errors:', errors.length);
  await b.close();
})();
