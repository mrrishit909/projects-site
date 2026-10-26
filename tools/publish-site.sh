#!/usr/bin/env bash
# Publish one project's built static site into the Pages branch of projects-site.
# Usage: tools/publish-site.sh <slug> <path-to-dist> <portfolio-checkout-on-unified-portfolio>
# The site is served at https://mrrishit909.github.io/projects-site/labs/<slug>/ once the
# legacy "pages build and deployment" run for unified-portfolio completes. The commit on
# unified-portfolio is the release ref; the previous commit is the rollback ref (master 21).
set -euo pipefail
slug="$1"; dist="$2"; portfolio="$3"
test -f "$dist/index.html" && test -f "$dist/routes.json"
grep -q "/projects-site/labs/$slug/" "$dist/index.html" || { echo "dist was not built with --base=/projects-site/labs/$slug/"; exit 1; }
cd "$portfolio"
test "$(git rev-parse --abbrev-ref HEAD)" = "unified-portfolio"
rm -rf "labs/$slug"; mkdir -p "labs/$slug"; cp -R "$dist/." "labs/$slug/"
sha=$(sha256sum $(find "labs/$slug" -type f | sort) | sha256sum | cut -c1-64)
echo "labs/$slug published-tree-sha256=$sha files=$(find "labs/$slug" -type f | wc -l)"
