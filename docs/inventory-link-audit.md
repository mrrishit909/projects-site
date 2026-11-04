# Inventory link audit (2026-11-03, run 21:53 to 21:56 EST)

All checks run with curl (HEAD-less GET, status code only, 20s timeout) or gh api. No browser, no files touched besides this one.

## Summary

| Metric | Value |
|---|---|
| Checks run | 255 (20 gh api Pages calls + 10 live Pages recurls + 213 case study URLs + 12 featured links) |
| 200s | 236 |
| Failures | 19 (10 live Pages 404s + 5 case study 404s + 4 featured failures) |
| Pages diagnoses | 10 of 10, all the same root cause (VERIFIED, see section 1) |

Not finished: nothing in scope was skipped. Caveat: featured.json carries no demo or repo URL fields (only slug), so section 3 derives demo from the inventory pages_url/homepage and repo from github.com/mrrishit909/<slug>.

## 1. Ten 404 Pages repos (gh api)

| Repo | Pages enabled | Source | Build type | Latest build | Build error | Live URL now | Root index.html on main |
|---|---|---|---|---|---|---|---|
| cascade | yes, status built | branch main, path / | legacy | built 2026-10-08T06:44:54Z | none | 404 | absent |
| eidolon | yes, status built | branch main, path / | legacy | built 2026-10-08T07:07:51Z | none | 404 | absent |
| ember | yes, status built | branch main, path / | legacy | built 2026-10-08T07:47:49Z | none | 404 | absent |
| aurelia | yes, status built | branch main, path / | legacy | built 2026-10-08T06:40:45Z | none | 404 | absent |
| lucent | yes, status built | branch main, path / | legacy | built 2026-10-08T07:33:14Z | none | 404 | absent |
| tessera | yes, status built | branch main, path / | legacy | built 2026-10-08T08:00:22Z | none | 404 | absent |
| vantage | yes, status built | branch main, path / | legacy | built 2026-10-08T08:30:37Z | none | 404 | absent |
| phantom | yes, status built | branch main, path / | legacy | built 2026-10-08T06:55:03Z | none | 404 | absent |
| rift | yes, status built | branch main, path / | legacy | built 2026-10-08T06:40:44Z | none | 404 | absent |
| citadel | yes, status built | branch main, path / | legacy | built 2026-10-08T07:18:25Z | none | 404 | absent |

Common root contents of main in all ten: .claude, .github, .gitignore, CLAUDE.md, Dockerfile, Makefile, apps, data, design, docker-compose.yml, docs, model, package.json, packages, playwright.config (monorepo source, no static site at root).

Diagnosis (VERIFIED by gh api contents + Pages API): Pages is enabled on every one of the ten with the legacy branch deploy from main:/ and the last build on 2026-10-08 reports status built with no error. The deploy succeeded, but main has no index.html at the root (and no docs/ site folder is configured), so Pages serves its own 404 page. The source is a monorepo (apps/, packages/) whose site must be built; nothing built is committed where Pages looks. Fix is the same for all ten: either switch Pages to GitHub Actions and add a build workflow that uploads the built app, or publish the built output to a gh-pages branch or docs/ folder and point Pages at it. INFERRED: the .github folder may already hold a workflow that was never adopted as the Pages source (build_type is still legacy); not opened before the stop time.

## 2. Case study URLs (has_case_study true)

Checked 213 URLs of the form https://mrrishit909.github.io/projects/<name>/ with xargs -P 8.

| Result | Count |
|---|---|
| 200 | 208 |
| other | 5 |

Non-200:

| Name | Code | URL |
|---|---|---|
| data-refinery | 404 | https://mrrishit909.github.io/projects/data-refinery/ |
| incident-loom | 404 | https://mrrishit909.github.io/projects/incident-loom/ |
| minimal-motion-studio | 404 | https://mrrishit909.github.io/projects/minimal-motion-studio/ |
| policy-forge | 404 | https://mrrishit909.github.io/projects/policy-forge/ |
| quant-foundry | 404 | https://mrrishit909.github.io/projects/quant-foundry/ |

## 3. featured.json demo and repo links

featured.json has 4 entries (florida-flight-delays, retail-dbt, us-retail-forecast, sec-10k-rag) and no URL fields of any kind; links were derived as stated in the summary caveat. Case study URL added as a third check per entry. For all four, the inventory has no pages_url and no homepage, so the demo URL is the github.io/<slug>/ fallback; its 404 means there is no standalone demo site, not that a published link is broken. The case study and repo links, which are what the portfolio actually points at, all return 200.

| Slug | Kind | URL | Code |
|---|---|---|---|
| retail-dbt | case | https://mrrishit909.github.io/projects/retail-dbt/ | 200 |
| florida-flight-delays | case | https://mrrishit909.github.io/projects/florida-flight-delays/ | 200 |
| retail-dbt | demo | https://mrrishit909.github.io/retail-dbt/ | 404 |
| us-retail-forecast | case | https://mrrishit909.github.io/projects/us-retail-forecast/ | 200 |
| florida-flight-delays | demo | https://mrrishit909.github.io/florida-flight-delays/ | 404 |
| us-retail-forecast | demo | https://mrrishit909.github.io/us-retail-forecast/ | 404 |
| sec-10k-rag | demo | https://mrrishit909.github.io/sec-10k-rag/ | 404 |
| sec-10k-rag | case | https://mrrishit909.github.io/projects/sec-10k-rag/ | 200 |
| retail-dbt | repo | https://github.com/mrrishit909/retail-dbt | 200 |
| us-retail-forecast | repo | https://github.com/mrrishit909/us-retail-forecast | 200 |
| florida-flight-delays | repo | https://github.com/mrrishit909/florida-flight-delays | 200 |
| sec-10k-rag | repo | https://github.com/mrrishit909/sec-10k-rag | 200 |

## Broken links (all sections)

- https://mrrishit909.github.io/cascade/ (404, Pages built from main:/ with no index.html)
- https://mrrishit909.github.io/eidolon/ (404, Pages built from main:/ with no index.html)
- https://mrrishit909.github.io/ember/ (404, Pages built from main:/ with no index.html)
- https://mrrishit909.github.io/aurelia/ (404, Pages built from main:/ with no index.html)
- https://mrrishit909.github.io/lucent/ (404, Pages built from main:/ with no index.html)
- https://mrrishit909.github.io/tessera/ (404, Pages built from main:/ with no index.html)
- https://mrrishit909.github.io/vantage/ (404, Pages built from main:/ with no index.html)
- https://mrrishit909.github.io/phantom/ (404, Pages built from main:/ with no index.html)
- https://mrrishit909.github.io/rift/ (404, Pages built from main:/ with no index.html)
- https://mrrishit909.github.io/citadel/ (404, Pages built from main:/ with no index.html)
- https://mrrishit909.github.io/projects/data-refinery/ (404)
- https://mrrishit909.github.io/projects/incident-loom/ (404)
- https://mrrishit909.github.io/projects/minimal-motion-studio/ (404)
- https://mrrishit909.github.io/projects/policy-forge/ (404)
- https://mrrishit909.github.io/projects/quant-foundry/ (404)
- https://mrrishit909.github.io/retail-dbt/ (404, featured retail-dbt demo)
- https://mrrishit909.github.io/florida-flight-delays/ (404, featured florida-flight-delays demo)
- https://mrrishit909.github.io/us-retail-forecast/ (404, featured us-retail-forecast demo)
- https://mrrishit909.github.io/sec-10k-rag/ (404, featured sec-10k-rag demo)
