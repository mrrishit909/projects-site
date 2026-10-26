// Recordings of the Precision Atelier home (Playwright video, GPU via ANGLE Metal): a fresh-session opening, Skip,
// Replay, each chapter's transformation scrubbed slowly, the arrangement controls and a drag, a case-study entry and
// return, a phone walk, and the reduced-motion composition. Writes .webm files into recordings/<tag>/ with a six-frame
// contact sheet each (ffmpeg). NODE_PATH=$(npm root -g) node record.cjs [tag]
// Output folder: $EVIDENCE_OUT, default ~/projects-site-evidence/atelier-2026-10-25 (outside the repository; packaged by tools/package.sh).
const OUT = process.env.EVIDENCE_OUT || require('path').join(require('os').homedir(), 'projects-site-evidence', 'atelier-2026-10-25');
const { chromium } = require('playwright'); const path = require('path'); const fs = require('fs'); const { execSync } = require('child_process');
const tag = process.argv[2] || 'final', out = path.join(OUT, 'recordings', tag); fs.mkdirSync(out, { recursive: true });
const BASE = 'http://127.0.0.1:8800/index.html';
const smooth = (p, from, to, ms) => p.evaluate(([a, b, ms]) => new Promise(res => { const t0 = performance.now(); const step = now => { const u = Math.min(1, (now - t0) / ms); scrollTo(0, a + (b - a) * (u * u * (3 - 2 * u))); if (u < 1) requestAnimationFrame(step); else res(); }; requestAnimationFrame(step); }), [from, to, ms]);
const top = (p, sel) => p.evaluate(s => document.querySelector(s).getBoundingClientRect().top + scrollY, sel);
const height = (p, sel) => p.evaluate(s => document.querySelector(s).offsetHeight, sel);
const ONLY = process.argv[3] || '';
const clip = async (b, name, vp, mobile, run, init) => { if (ONLY && !name.includes(ONLY)) return;
  const ctx = await b.newContext({ viewport: vp, deviceScaleFactor: 1, isMobile: mobile, hasTouch: mobile, recordVideo: { dir: out, size: vp }, reducedMotion: name.includes('reduced') ? 'reduce' : 'no-preference' });
  if (init) await ctx.addInitScript(init);
  const p = await ctx.newPage(); await run(p); const v = p.video(); await ctx.close(); const f = await v.path(); const dst = path.join(out, name + '.webm'); fs.renameSync(f, dst);
  try { execSync(`ffmpeg -loglevel error -y -i "${dst}" -vf "select='not(mod(n\\,max(1\\,floor(n_frames/6))))',scale=${Math.round(vp.width / 3)}:-1,tile=6x1" -frames:v 1 "${path.join(out, name + '-sheet.jpg')}"`); } catch (e) { try { execSync(`ffmpeg -loglevel error -y -i "${dst}" -vf "fps=1/2,scale=${Math.round(vp.width / 3)}:-1,tile=6x1" -frames:v 1 "${path.join(out, name + '-sheet.jpg')}"`); } catch (_) {} }
  console.log('wrote', name);
};
(async () => {
  const b = await chromium.launch({ args: ['--use-angle=metal', '--ignore-gpu-blocklist'] });
  const D = { width: 1440, height: 900 }, M = { width: 390, height: 844 };
  await clip(b, 'opening-fresh', D, false, async p => { await p.goto(BASE, { waitUntil: 'commit' }); await p.waitForTimeout(4600); });
  await clip(b, 'opening-skip', D, false, async p => { await p.goto(BASE, { waitUntil: 'commit' }); await p.waitForTimeout(900); await p.click('#skip'); await p.waitForTimeout(1500); });
  await clip(b, 'opening-replay', D, false, async p => { await p.goto(BASE, { waitUntil: 'networkidle' }); await p.waitForTimeout(600); await p.click('#replay'); await p.waitForTimeout(4200); }, () => { try { sessionStorage.setItem('seen', '1'); } catch (_) {} });
  await clip(b, 'opening-reduced', D, false, async p => { await p.goto(BASE, { waitUntil: 'networkidle' }); await p.waitForTimeout(2000); await smooth(p, 0, 2600, 3000); await p.waitForTimeout(800); });
  for (const [i, slug] of ['florida-flight-delays', 'retail-dbt', 'us-retail-forecast', 'sec-10k-rag'].entries()) {
    await clip(b, `chapter${i + 1}-${slug}`, D, false, async p => { await p.goto(BASE, { waitUntil: 'networkidle' }); const t = await top(p, '#feature-' + slug), h = await height(p, '#feature-' + slug); await p.evaluate(y => scrollTo(0, y), t - 700); await p.waitForTimeout(600); await smooth(p, t - 700, t + h - 900, 7000); await p.waitForTimeout(1200); }, () => { try { sessionStorage.setItem('seen', '1'); } catch (_) {} });
  }
  await clip(b, 'reverse-scroll', D, false, async p => { await p.goto(BASE, { waitUntil: 'networkidle' }); const t = await top(p, '#feature-us-retail-forecast'), h = await height(p, '#feature-us-retail-forecast'); await p.evaluate(y => scrollTo(0, y), t + h - 900); await p.waitForTimeout(800); await smooth(p, t + h - 900, t - 2200, 5000); await p.waitForTimeout(800); }, () => { try { sessionStorage.setItem('seen', '1'); } catch (_) {} });
  await clip(b, 'system-controls-drag', D, false, async p => { await p.goto(BASE + '#system', { waitUntil: 'networkidle' }); await p.waitForTimeout(800); for (const c of ['closed', 'network', 'pipeline', 'timeline', 'documents', 'open']) { await p.click(`[data-config=${c}]`); await p.waitForTimeout(1300); } for (let i = 0; i <= 10; i++) { await p.evaluate(v => { const s = document.getElementById('separate'); s.value = v; s.dispatchEvent(new Event('input', { bubbles: true })); }, (10 - i) / 10); await p.waitForTimeout(90); } await p.waitForTimeout(600); for (let i = 0; i <= 10; i++) { await p.evaluate(v => { const s = document.getElementById('separate'); s.value = v; s.dispatchEvent(new Event('input', { bubbles: true })); }, i / 10); await p.waitForTimeout(90); } await p.mouse.move(1000, 420); await p.mouse.down(); for (let i = 0; i < 40; i++) { await p.mouse.move(1000 + i * 9, 420); await p.waitForTimeout(30); } await p.mouse.up(); await p.waitForTimeout(1000); await p.click('#turn-reset'); await p.waitForTimeout(1200); });
  await clip(b, 'case-entry-return', D, false, async p => { await p.goto(BASE, { waitUntil: 'networkidle' }); const t = await top(p, '#feature-retail-dbt'), h = await height(p, '#feature-retail-dbt'); await p.evaluate(y => scrollTo(0, y), t + h * 0.7 - 900); await p.waitForTimeout(1200); await p.click('#feature-retail-dbt .btns a.fill'); await p.waitForLoadState('load'); await p.waitForTimeout(2500); await smooth(p, 0, 900, 2000); await p.waitForTimeout(500); await p.goBack(); await p.waitForLoadState('load'); await p.waitForTimeout(2000); }, () => { try { sessionStorage.setItem('seen', '1'); } catch (_) {} });
  await clip(b, 'closing', D, false, async p => { await p.goto(BASE + '#system', { waitUntil: 'networkidle' }); await p.waitForTimeout(500); const t = await top(p, '#contact'); await smooth(p, await p.evaluate(() => scrollY), t, 6000); await p.waitForTimeout(2000); }, () => { try { sessionStorage.setItem('seen', '1'); } catch (_) {} });
  await clip(b, 'pause-resume', D, false, async p => { await p.goto(BASE + '#system', { waitUntil: 'networkidle' }); await p.waitForTimeout(600); await p.click('[data-config=pipeline]'); await p.waitForTimeout(500); await p.click('#pause'); await p.waitForTimeout(1500); await p.evaluate(() => scrollBy(0, 300)); await p.waitForTimeout(800); await p.click('#pause'); await p.waitForTimeout(1800); });
  await clip(b, 'context-loss', D, false, async p => { await p.goto(BASE, { waitUntil: 'networkidle' }); await p.waitForTimeout(800); await p.evaluate(() => { const gl = document.getElementById('instrument').getContext('webgl2'); window.__lose = gl.getExtension('WEBGL_lose_context'); window.__lose.loseContext(); }); await p.waitForTimeout(1500); await p.evaluate(() => window.__lose.restoreContext()); await p.waitForTimeout(2000); }, () => { try { sessionStorage.setItem('seen', '1'); } catch (_) {} });
  await clip(b, 'phone-opening', M, true, async p => { await p.goto(BASE, { waitUntil: 'commit' }); await p.waitForTimeout(4500); });
  await clip(b, 'phone-walk', M, true, async p => { await p.goto(BASE, { waitUntil: 'networkidle' }); const H = await p.evaluate(() => document.body.scrollHeight - innerHeight); await smooth(p, 0, H, 18000); await p.waitForTimeout(800); }, () => { try { sessionStorage.setItem('seen', '1'); } catch (_) {} });
  // the representative journey (design/journey.md): a fresh opening, the hero, Selected work, the first project forming and
  // settling, its hour control, View project, the case page's hero and reading, Back; desktop and phone
  const journey = async (p, tall) => { await p.goto(BASE, { waitUntil: 'commit' }); await p.waitForTimeout(3600);
    const t1 = await top(p, '#feature-florida-flight-delays'), h1 = await height(p, '#feature-florida-flight-delays');
    await smooth(p, 0, t1 + (h1 - tall) * 0.62, 6500); await p.waitForTimeout(900);
    await p.evaluate(() => { const i = document.getElementById('hour'); for (const v of [12, 16, 20]) { i.value = v; i.dispatchEvent(new Event('input', { bubbles: true })); } }); await p.waitForTimeout(1400);
    await p.evaluate(() => document.querySelector('#feature-florida-flight-delays .btns a.fill').click()); await p.waitForLoadState('load'); await p.waitForTimeout(2200);
    await smooth(p, 0, tall * 1.1, 2200); await p.waitForTimeout(600); await p.goBack(); await p.waitForLoadState('load'); await p.waitForTimeout(2200); };
  await clip(b, 'journey-desktop', D, false, p => journey(p, 900));
  await clip(b, 'journey-phone', M, true, p => journey(p, 844));
  await b.close();
})();
