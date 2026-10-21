/* Builds the cover-wall texture atlases for scene.js: every <slug>/cover.jpg cropped to 320x183 and packed, 66 per 2048x2048
   JPEG, into assets/wall/atlas-N.jpg plus assets/wall/atlas.json ({slug: [atlas, column, row]} with the tile size and grid).
   Run after adding projects:  NODE_PATH=$(npm root -g) node tools/wall-atlas.cjs   (needs sips (macOS) and Playwright's Chromium). */
const { execFileSync } = require("child_process");
const fs = require("fs"), path = require("path"), os = require("os");
const { chromium } = require("playwright");
const ROOT = path.join(__dirname, ".."), OUT = path.join(ROOT, "assets", "wall");
const TW = 320, TH = 183, SIZE = 2048, COLS = Math.floor(SIZE / TW), ROWS = Math.floor(SIZE / TH), PER = COLS * ROWS;
(async () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "wall-"));
  const slugs = fs.readdirSync(ROOT).filter(d => fs.existsSync(path.join(ROOT, d, "project.json")) && fs.existsSync(path.join(ROOT, d, "cover.jpg"))).sort();
  for (const s of slugs) execFileSync("sips", ["-s", "format", "jpeg", "--resampleWidth", String(TW), "--cropToHeightWidth", String(TH), String(TW), path.join(ROOT, s, "cover.jpg"), "--out", path.join(tmp, s + ".jpg")], { stdio: "ignore" });
  const map = {}, n = Math.ceil(slugs.length / PER);
  const browser = await chromium.launch(); const page = await browser.newPage();
  for (let a = 0; a < n; a++) {
    const batch = slugs.slice(a * PER, (a + 1) * PER);
    const urls = batch.map(s => "data:image/jpeg;base64," + fs.readFileSync(path.join(tmp, s + ".jpg")).toString("base64"));
    const data = await page.evaluate(async ({ urls, TW, TH, SIZE, COLS }) => {
      const c = document.createElement("canvas"); c.width = SIZE; c.height = SIZE; const ctx = c.getContext("2d");
      ctx.fillStyle = "#211E1B"; ctx.fillRect(0, 0, SIZE, SIZE);
      await Promise.all(urls.map((u, i) => new Promise(res => { const im = new Image(); im.onload = () => { ctx.drawImage(im, (i % COLS) * TW, Math.floor(i / COLS) * TH, TW, TH); res(); }; im.src = u; })));
      return c.toDataURL("image/jpeg", 0.8);
    }, { urls, TW, TH, SIZE, COLS });
    fs.writeFileSync(path.join(OUT, `atlas-${a}.jpg`), Buffer.from(data.split(",")[1], "base64"));
    batch.forEach((s, i) => { map[s] = [a, i % COLS, Math.floor(i / COLS)]; });
  }
  await browser.close();
  fs.writeFileSync(path.join(OUT, "atlas.json"), JSON.stringify({ tile: [TW, TH], size: SIZE, cols: COLS, rows: ROWS, atlases: n, tiles: map }));
  fs.rmSync(tmp, { recursive: true });
  console.log(`${slugs.length} covers in ${n} atlases`);
})();
