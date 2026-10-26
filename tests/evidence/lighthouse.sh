#!/bin/zsh
# Lighthouse 12 (mobile and desktop presets) on the production build served with gzip by `serve` on 8801.
# Run from ~/projects-site with nothing else loading the machine: zsh tests/evidence/lighthouse.sh   (output: $EVIDENCE_OUT)
set -e
cd ~/projects-site
E=${EVIDENCE_OUT:-$HOME/projects-site-evidence/atelier-2026-10-25}
npx -y serve@14.2.4 -l 8801 -s . > $E/serve.log 2>&1 &
SP=$!
sleep 3
for t in "home:index.html" "case:florida-flight-delays/" "case-long:workforce-scheduler/" "archive:all.html"; do
  name=${t%%:*}; url=${t#*:}
  npx -y lighthouse@12.8.2 "http://127.0.0.1:8801/$url" --quiet --chrome-flags="--headless=new --use-angle=metal --ignore-gpu-blocklist" --output=json --output-path=$E/lh-$name-mobile.json --only-categories=performance,accessibility,best-practices,seo > /dev/null 2>&1 || echo "lighthouse $name mobile failed"
  npx -y lighthouse@12.8.2 "http://127.0.0.1:8801/$url" --quiet --preset=desktop --chrome-flags="--headless=new --use-angle=metal --ignore-gpu-blocklist" --output=json --output-path=$E/lh-$name-desktop.json --only-categories=performance,accessibility > /dev/null 2>&1 || echo "lighthouse $name desktop failed"
done
kill $SP
node -e '
const fs=require("fs"),E=process.argv[1];
for (const f of fs.readdirSync(E).filter(f=>/^lh-.*\.json$/.test(f)).sort()) { const r=JSON.parse(fs.readFileSync(E+"/"+f)); const c=r.categories, a=r.audits;
  console.log(f.padEnd(28), Object.keys(c).map(k=>k.slice(0,4)+" "+Math.round(c[k].score*100)).join("  "), "| LCP", a["largest-contentful-paint"].displayValue, "CLS", a["cumulative-layout-shift"].displayValue, "TBT", a["total-blocking-time"].displayValue, "bytes", Math.round(a["total-byte-weight"].numericValue/1024)+"KiB", "LCP el:", (a["largest-contentful-paint-element"].details&&a["largest-contentful-paint-element"].details.items[0]&&a["largest-contentful-paint-element"].details.items[0].items&&a["largest-contentful-paint-element"].details.items[0].items[0].node.snippet||"").slice(0,60)); }
' $E
