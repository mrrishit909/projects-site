// The hero poster: the instrument in its exploded hero arrangement, rendered with alpha from the lab at the home's stage
// (desktop 1440x900 at 70% / 52%, phone 390x844 at 50% / 27%), for the first paint and for browsers without WebGL.
// NODE_PATH=$(npm root -g) node tools/poster.cjs   (needs the local server on 8800 and cwebp)
const { chromium } = require('playwright'); const { execSync } = require('child_process'); const path = require('path');
(async () => {
  const b = await chromium.launch({ args: ['--use-angle=metal', '--ignore-gpu-blocklist'] });
  for (const [name, vp, q] of [['atelier-poster', { width: 1440, height: 900 }, 'sx=0.71&sy=0.52&ss=1'], ['atelier-poster-m', { width: 390, height: 844 }, 'sx=0.5&sy=0.27&ss=0.62']]) {
    const ctx = await b.newContext({ viewport: vp, deviceScaleFactor: 1 }); const p = await ctx.newPage();
    await p.goto(`http://127.0.0.1:8800/motion/instrument-lab.html?state=open&poster=1&${q}`, { waitUntil: 'networkidle' }); await p.waitForTimeout(3000);
    // the lab's controls must be gone and the ground transparent before capture; refuse to export otherwise
    const clean = await p.evaluate(() => getComputedStyle(document.querySelector('.ui')).display === 'none' && getComputedStyle(document.documentElement).backgroundColor === 'rgba(0, 0, 0, 0)' && getComputedStyle(document.body).backgroundColor === 'rgba(0, 0, 0, 0)');
    if (!clean) { console.error(name + ': the lab still shows its controls or a ground; export refused'); process.exit(1); }
    const png = path.join(__dirname, '..', 'assets', name + '.png'); await p.screenshot({ path: png, omitBackground: true });
    // pixel check: the bottom-left strip (where the lab's controls sit) must be fully transparent, and the object must be present
    const sharp = require('child_process').execSync(`python3 -c "import struct,zlib,sys\nd=open(sys.argv[1],'rb').read();i=8;w=h=0;idat=b''\nwhile i<len(d):\n  n=struct.unpack('>I',d[i:i+4])[0];t=d[i+4:i+8];c=d[i+8:i+8+n]\n  if t==b'IHDR': w,h=struct.unpack('>II',c[:8])\n  if t==b'IDAT': idat+=c\n  i+=12+n\nraw=zlib.decompress(idat);s=w*4+1;rows=[raw[r*s+1:(r+1)*s] for r in range(h)]\nprev=bytearray(w*4);out=[]\nfor r in range(h):\n  f=raw[r*s];row=bytearray(rows[r])\n  for x in range(w*4):\n    a=row[x-4] if x>=4 else 0;b=prev[x];c=prev[x-4] if x>=4 else 0\n    if f==1: row[x]=(row[x]+a)&255\n    elif f==2: row[x]=(row[x]+b)&255\n    elif f==3: row[x]=(row[x]+(a+b)//2)&255\n    elif f==4:\n      p=a+b-c;pa=abs(p-a);pb=abs(p-b);pc=abs(p-c);row[x]=(row[x]+(a if pa<=pb and pa<=pc else b if pb<=pc else c))&255\n  out.append(bytes(row));prev=row\nstrip=sum(1 for r in range(int(h*0.9),h) for x in range(0,int(w*0.3)) if out[r][x*4+3]>0)\nopaque=sum(1 for r in range(0,h,4) for x in range(0,w,4) if out[r][x*4+3]>200)\nprint(strip,opaque)" "${png}"`).toString().trim().split(' ').map(Number);
    if (sharp[0] > 0 || sharp[1] < (vp.width * vp.height / 16) * 0.02) { console.error(name + ': poster pixel check failed (strip ' + sharp[0] + ', opaque samples ' + sharp[1] + ')'); process.exit(1); }
    console.log(name, 'clean: strip transparent, opaque samples', sharp[1]);
    execSync(`cwebp -q 82 -alpha_q 90 "${png}" -o "${png.replace('.png', '.webp')}"`); execSync(`rm "${png}"`); await ctx.close();
  }
  await b.close(); console.log('posters written');
})();
