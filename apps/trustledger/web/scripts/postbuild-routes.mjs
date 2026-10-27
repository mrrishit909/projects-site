// Copy dist/index.html into every route directory so that direct entry and reload work on
// GitHub Pages under a nested base path without a 404 fallback (P01-UI-*-R03, master 21).
import { mkdirSync, copyFileSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

export const ROUTES = [
  "catalog", "glossary", "scorecard", "rules", "issues", "lineage",
  "duplicates", "merges", "impact", "evidence", "case-study",
];
const dist = new URL("../dist/", import.meta.url).pathname;
for (const r of ROUTES) {
  mkdirSync(join(dist, r), { recursive: true });
  copyFileSync(join(dist, "index.html"), join(dist, r, "index.html"));
}
const manifest = { routes: ["", ...ROUTES.map((r) => r + "/")], generated_at: new Date().toISOString() };
writeFileSync(join(dist, "routes.json"), JSON.stringify(manifest, null, 2));
console.log(`routes: ${ROUTES.length + 1} index.html copies written; base in html: ${/href="([^"]*assets)/.exec(readFileSync(join(dist, "index.html"), "utf8"))?.[1] ?? "?"}`);
