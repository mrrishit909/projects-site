#!/bin/zsh
# The review package: the site source and runtime assets (no git history, caches or dependency folders), the evidence
# folder (captures, recordings with contact sheets, pacing, context loss, throttled, fallbacks, responsive, Lighthouse
# JSON, suite output), the scripts that produced them (tests/evidence), a manifest, tool versions and checksums.
# Run from ~/projects-site after the evidence has been produced on the committed candidate:
#   zsh tools/package.sh <commit>      -> ~/Downloads/precision-atelier-review-<date>-<commit>.zip (+ .sha256)
set -e
cd ~/projects-site
COMMIT=${1:-$(git rev-parse --short HEAD)}
DATE=$(date +%Y-%m-%d)
E=${EVIDENCE_OUT:-$HOME/projects-site-evidence/atelier-2026-10-25}
STAGE=$(mktemp -d)/precision-atelier-review-$DATE-$COMMIT
mkdir -p "$STAGE/site" "$STAGE/evidence"
# 1. the site at the tested commit (the working tree must be clean and at that commit)
test -z "$(git status --short)" || { echo "working tree not clean; commit first"; exit 1; }
test "$(git rev-parse --short HEAD)" = "$COMMIT" || { echo "HEAD is not $COMMIT"; exit 1; }
git archive --format=tar HEAD | tar -x -C "$STAGE/site"
# 2. the evidence
rsync -a --exclude '.DS_Store' "$E/" "$STAGE/evidence/"
# 3. tool versions and conditions
{
  echo "tested commit: $COMMIT ($(git log -1 --format=%cI HEAD))"
  echo "packaged: $(date -Iseconds)"
  echo "machine: $(sysctl -n machdep.cpu.brand_string), macOS $(sw_vers -productVersion)"
  echo "node: $(node -v); playwright: $(node -e "console.log(require(require('path').join(require('child_process').execSync('npm root -g').toString().trim(),'playwright/package.json')).version)")"
  echo "chromium (playwright): $(ls ~/Library/Caches/ms-playwright 2>/dev/null | grep chromium | tail -1)"
  echo "chrome (owner's browser, extension checks): 156"
  echo "lighthouse: 12.8.2 via npx; serve: 14.2.4 via npx; esbuild: 0.24.0 via npx; python: $(python3 --version); cwebp: $(cwebp -version 2>/dev/null | head -1)"
  echo "display: 60 Hz; GPU: Apple M3 Pro via ANGLE Metal in Playwright Chromium; Lighthouse headless Chrome renders WebGL in software"
  echo "network: local http.server 8800 (behaviour), serve with gzip on 8801 (Lighthouse, simulated slow 4G on the mobile preset)"
} > "$STAGE/CONDITIONS.txt"
cp docs/REVIEW-PACKAGE.md "$STAGE/README.md"
# 4. checksums of every file, then the archive and its checksum
( cd "$STAGE" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 shasum -a 256 > SHA256SUMS )
OUT=~/Downloads/precision-atelier-review-$DATE-$COMMIT.zip
rm -f "$OUT" "$OUT.sha256"
( cd "$(dirname "$STAGE")" && zip -qr "$OUT" "$(basename "$STAGE")" -x '*/.DS_Store' )
shasum -a 256 "$OUT" > "$OUT.sha256"
shasum -a 256 -c "$OUT.sha256"
# 5. verify the packaged site matches the tested source
TMP=$(mktemp -d); ( cd "$TMP" && unzip -q "$OUT" "$(basename "$STAGE")/site/*" )
git archive --format=tar HEAD | tar -x -C "$TMP/ref" 2>/dev/null || { mkdir -p "$TMP/ref"; git archive --format=tar HEAD | tar -x -C "$TMP/ref"; }
diff -rq "$TMP/ref" "$TMP/$(basename "$STAGE")/site" && echo "packaged site matches commit $COMMIT"
ls -lh "$OUT" | awk '{print $5, $9}'
