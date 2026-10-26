// Six-frame contact sheets from the Playwright recordings, without ffmpeg: the installed Chrome plays each .webm (the
// files have no seek index, so seeking is unreliable; the frames are taken as playback crosses six evenly spaced times),
// draws them to a canvas and screenshots it. NODE_PATH=$(npm root -g) node sheets.cjs [tag]
// Output folder: $EVIDENCE_OUT, default ~/projects-site-evidence/atelier-2026-10-25 (outside the repository; packaged by tools/package.sh).
const OUT = process.env.EVIDENCE_OUT || require('path').join(require('os').homedir(), 'projects-site-evidence', 'atelier-2026-10-25');
const { chromium } = require('playwright'); const path = require('path'); const fs = require('fs');
const dir = path.join(OUT, 'recordings', process.argv[2] || 'final');
(async () => {
  const b = await chromium.launch({ channel: 'chrome' }); const ctx = await b.newContext({ viewport: { width: 1800, height: 420 } }); const p = await ctx.newPage();
  let current = null; await p.route('**/vid.webm*', r => r.fulfill({ body: current, contentType: 'video/webm' }));
  await p.goto('http://127.0.0.1:8800/404.html');
  for (const f of fs.readdirSync(dir).filter(f => f.endsWith('.webm'))) {
    current = fs.readFileSync(path.join(dir, f));
    const ok = await p.evaluate(async () => { document.body.innerHTML = ''; document.body.style.margin = '0'; document.body.style.background = '#111';
      const v = document.createElement('video'); v.src = '/vid.webm?' + Math.random(); v.muted = true; v.preload = 'auto'; document.body.append(v);
      await new Promise((res, rej) => { v.onloadedmetadata = res; v.onerror = () => rej(new Error('video error ' + (v.error && v.error.code))); });
      let d = v.duration; if (!isFinite(d)) { v.currentTime = 1e6; await new Promise(res => { v.ontimeupdate = () => res(); }); d = v.duration; v.currentTime = 0; await new Promise(res => { v.onseeked = res; setTimeout(res, 500); }); }
      const W = 300, H = Math.round(W * v.videoHeight / v.videoWidth), c = document.createElement('canvas'); c.width = W * 6; c.height = H + 24; const g = c.getContext('2d'); g.fillStyle = '#111'; g.fillRect(0, 0, c.width, c.height); g.fillStyle = '#ddd'; g.font = '12px system-ui';
      const targets = Array.from({ length: 6 }, (_, i) => 0.2 + i * (d - 0.5) / 5); let i = 0;
      await new Promise(res => { const tick = () => { if (i < 6 && v.currentTime >= targets[i]) { g.drawImage(v, i * W, 0, W, H); g.fillText(v.currentTime.toFixed(1) + ' s', i * W + 6, H + 16); i++; } if (i >= 6 || v.ended) res(); else v.requestVideoFrameCallback(tick); }; v.play().then(() => v.requestVideoFrameCallback(tick)).catch(() => res()); setTimeout(res, (d + 3) * 1000); });
      v.pause(); v.remove(); c.id = 'sheet'; document.body.append(c); return [d, i]; });
    const el = await p.$('#sheet'); await el.screenshot({ path: path.join(dir, f.replace('.webm', '-sheet.jpg')), type: 'jpeg', quality: 80 });
    console.log(f, 'duration', ok[0].toFixed(1), 'frames', ok[1]);
  }
  await b.close();
})();
