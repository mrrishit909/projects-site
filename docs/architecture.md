# ATELIER X Architecture (Frontend Architect draft, 2026-11-03)

Labels used throughout: VERIFIED (I read the code or file tonight), INFERRED (deduced from what I read, not directly confirmed), PROPOSED (a decision offered for owner review). Written under a hard stop; sections are complete but terse.

## 1. Current state (verified)

Inspected read-only 2026-11-03 21:51 EST: `projects-site/CLAUDE.md`, `build.py` (grep of definitions), `publish.sh` (head), `featured.json` (head), `cashcompass/project.json` (head), `tests/`, `tools/`, `vendor/`, git remotes, `docs/NEXT_REBUILD_PLAN.md`, and `projects-next/package.json`, `src/lib`, `src/components`.

- VERIFIED: `projects-site` is a stdlib-only Python generator. `build.py` has `REQUIRED = ["title","tagline","kind","tech","date","repo","problem","built","steps","results","next"]`, a `FROZEN_OK = {"trading-bot"}` exception, `load()` that fails on missing required fields or a new frozen project, `project_page()`, `home_page()`, `all_page()`, a `KIND_STATE` map from project kind to the instrument arrangement, and a `contrast()` / `low_contrast_text()` palette check. Text fields are trusted HTML fragments (CLAUDE.md states this; the build rejects `style=`, `<style>`, `<script>`, `<link>`, `<font>` inside them).
- VERIFIED: 236 `*/project.json` files exist on disk (`ls */project.json | wc -l`). Generated HTML is committed; GitHub never builds. The site lives at `mrrishit909.github.io/projects/`. Current branch is `atelier-x`; remotes are `origin` (public `mrrishit909/projects`) and `private` (`mrrishit909/projects-site`, default branch `unified-portfolio`). CLAUDE.md forbids pushing `origin` without the owner.
- VERIFIED: there is no `package.json`, no `.github/` directory, and no CI in `projects-site`. Node tooling is global (`NODE_PATH=$(npm root -g)`), used by `tests/portfolio-check.cjs` (Playwright, Chromium on Metal) and `tests/evidence/*` (fallbacks, gl-loss, journey-frames, lab-views, lifecycle, lighthouse.sh, pace, record, responsive, sheets, shots, throttled). `tools/` has `config-posters.cjs`, `github.sh`, `og.cjs`, `package.sh`, `poster.cjs`.
- VERIFIED: `vendor/` holds `fonts`, `gsap`, `lenis` (CLAUDE.md says unused by the home), `three` (tree-shaken r170, rebuilt per `docs/BUILD-THREE.md`). Front-end files are vanilla: `atelier.css`, `home.js`, `case.js`, `catalog.js`, `instrument.js`, templates `index.template.html` and `all.template.html`. View Transitions into case studies already exist (CLAUDE.md).
- VERIFIED: `publish.sh` scans tracked files and full git history for `.env`, secret patterns (Anthropic, OpenAI, GitHub PAT, AWS AKIA, private keys) and files over 49 MB before any push.
- VERIFIED: `projects-next` is Next.js 15.5.28 + React 19.1 + three 0.186 + lenis, with `src/lib/{cube,data,timeline}.ts` and `src/components/{FilmStage,Index,Split}.tsx`. Its plan (`docs/NEXT_REBUILD_PLAN.md`) targeted Supabase + ImageKit + Vercel with an admin portal; memory notes say its designs (prism, THE CUBE) were rejected and the backend needs owner accounts that do not exist.
- INFERRED: the motion tiles (`loop.mp4`/`loop.webm`, ~71 MB total per the Next plan) are the largest asset class and will dominate repo size and LCP risk on list pages.
- INFERRED: a11y, link checking and visual regression exist only as parts of `portfolio-check.cjs` and the evidence scripts, not as separable CI gates.

## 2. Requirements that drive the choice

1. Static hosting on GitHub Pages under `mrrishit909.github.io/<repo>/`: every URL, asset and `<link rel=canonical>` must respect a per-repo base path; one base for the portfolio, a different one per microsite.
2. 220+ case pages generated from structured data, with the data as the single source of truth for the portfolio AND for any microsite's "about this project" block.
3. A cinematic WebGL intro with a poster-first paint and a reduced-motion / no-WebGL fallback that is a real page, not a blank.
4. Each microsite has its own visual identity (type, palette, object, motion signature) but shares engineering (tokens API, a11y utilities, animation helpers, QA harness, deploy workflow).
5. Strict validation that fails the build: no private leaks (secrets, local paths, private repo URLs, emails other than the public one), no dead internal links, no duplicate IDs, no missing images or media, no unverified claims (every number traces to an evidence entry).
6. Lighthouse 90+ performance, 95+ accessibility, 95+ best practices, 95+ SEO; LCP <= 2.5 s; CLS <= 0.1; measured on the production build, not a dev server.
7. TypeScript for anything with logic. Tests: unit, component, e2e, axe, link check, visual regression. GitHub Actions CI on every push and PR.
8. GitHub Pages deploy with preview isolation per branch and a rollback that takes one command.
9. Free infrastructure only, built and maintained by Claude Code agents, so conventions must be machine-checkable and boring.

## 3. Options compared

| Option | Pros | Cons | Risks | Migration cost |
|---|---|---|---|---|
| (a) Keep `build.py` + vanilla ES modules | Zero new deps; the 236 records and templates already work; GPU evidence harness exists; agents know it | No TypeScript, no component tests, no schema types, string-templated HTML, one global stylesheet for 220 pages, no CI today | Validation drifts (it is ad hoc Python asserts); each microsite reinvents plumbing; typed shared packages cannot be consumed from Python | Lowest (0 for portfolio), but every microsite pays full price |
| (b) Astro, islands + content collections with zod | Static-first; `base` config solves repo subpaths; content collections give typed, validated JSON at build time (zod errors fail the build); islands keep WebGL off the critical path; ships zero JS by default; View Transitions built in; vanilla, Svelte, React or Solid islands all work; GSAP and Three fit as plain modules | New framework for the agents; a `node_modules` install step; island hydration directives must be learned | Over-use of framework islands bloats JS; `astro:transitions` needs explicit fallbacks; version churn | Medium: `project.json` files move into `src/content/projects/*.json` unchanged, templates port from Python f-strings to `.astro` files, CSS ports as-is |
| (c) Vite multi-page TypeScript | Minimal, fast, TS native, full control; good fit for a single microsite | No content layer; 220 pages means writing our own generator again (same as (a) but in TS); routing, SEO and base path handled by hand | Rebuilding build.py in TS with no gain in validation unless we add zod ourselves; two generators to maintain during migration | Medium-high: all templating rewritten, no framework help |
| (d) Next.js static export | Already a repo (`projects-next`); React ecosystem; familiar | `output: "export"` disallows ISR, image optimisation, middleware and route handlers, which is exactly what `NEXT_REBUILD_PLAN.md` wanted; `basePath` works but is global; heaviest runtime JS; React 19 + three + lenis bundle hurts LCP on 220 content pages; the designs built there were rejected | Pulls toward Vercel and a backend the owner has not provisioned; largest Lighthouse risk | High: React components for everything, and the data layer design assumed Supabase |

PROPOSED recommendation: (b) Astro with content collections and islands, for the portfolio and for every microsite, as one monorepo (section 4). Reasons: it is the only option where "220 pages from validated structured data" is a built-in feature (content collections + zod) rather than something we write; `base` and `site` config give correct subpaths per repo with no hand-written URL joins; static HTML by default protects Lighthouse and LCP; islands put Three.js and GSAP exactly where depth is required and nowhere else; View Transitions and `<ClientRouter>` are first class with a documented fallback; the existing vanilla `home.js`, `case.js`, `instrument.js` and `atelier.css` port as plain `<script>`/`<style>` modules with little change. Option (a) stays the fallback: if the owner rejects a Node toolchain, keep `build.py` and add the validator (section 5) in Python plus the CI from section 9; everything else here still applies.

## 4. Repo shape and shared packages

PROPOSED: one monorepo `atelier-x` (private, like `projects-site` today) using npm workspaces (no Turborepo, no pnpm; stdlib-level tooling first). Public GitHub Pages repos stay one per site because Pages serves one site per repo; the monorepo publishes into them via the deploy workflow (section 9). Rejected: one repo per microsite with copied packages (drift), and publishing npm packages (overhead for one consumer).

```
atelier-x/
  apps/
    portfolio/            Astro site -> mrrishit909.github.io/projects/
    <microsite>/          one Astro site per microsite -> mrrishit909.github.io/<repo>/
  packages/
    tokens/               design tokens: CSS custom properties per site theme + a TS export; a base scale (space, type, radius, z, motion) and per-site palette files
    a11y/                 focus trap, roving tabindex, live-region announcer, skip link, prefers-reduced-motion and prefers-contrast hooks, visually-hidden utility
    motion/               animation helpers: CSS keyframe and easing registry (section 1 of motion-system.md), GSAP timeline and ScrollTrigger wrappers with mandatory cleanup, Three.js scene lifecycle (adaptive DPR, visibility pause, context-loss recovery), Remotion lives in a separate workspace folder `render/` because it renders video offline, never in the browser
    layout/               responsive primitives: container, stack, cluster, grid with the 8 breakpoints the QA harness screenshots, fluid type clamp helpers
    seo/                  metadata component (title, description, canonical with base path, OG image path, JSON-LD for CreativeWork), sitemap and robots helpers honouring base
    content/              the project inventory zod schema, the validator CLI (section 5), the loader shared by portfolio and microsites
    deploy/               reusable GitHub Actions workflow templates (build, QA, preview publish, production publish, rollback)
    qa/                   the evidence harness: Playwright screenshots at 320/375/390/768/1024/1280/1440/1920, reduced-motion pass, keyboard-only pass, 200% zoom pass, axe, link check, Lighthouse CI, frame pacing recorder (ported from tests/evidence/pace.cjs), contact sheets
  content/
    projects/*.json       the 236 records, moved verbatim then migrated field by field
    evidence/             evidence manifests (section 5)
  render/                 Remotion compositions for tiles and recordings (separate install, optional)
```

Rule: `apps/*` import from `packages/*` only; packages never import from apps; `tokens` and `content` have zero runtime dependencies.

## 5. Content model and validation rules

PROPOSED inventory schema (zod in `packages/content/schema.ts`; today's `project.json` fields map onto it, see the migration table in section 10):

```
Project {
  id: slug string, ^[a-z0-9]+(-[a-z0-9]+)*$, unique
  name: string 3..90
  summary: string 40..320, plain text (no HTML)
  category: enum (bi, ml, data-engineering, analytics, product, creative, ops, research, other)
  repos: [{ url, visibility: public|private, role: source|demo|fork }]  (private ones never rendered)
  demos: [{ url, kind: static|recorded|hosted, status: live|archived|unverified, last_checked: date }]
  stack: string[] (from a controlled vocabulary file; unknown entries fail)
  status: enum (live, archived, in-progress, concept)
  capabilities: string[] (what it does, verb phrases)
  evidence: [{ claim: string, source: url|path, kind: measured|repo-reported|backtest|recorded|synthetic, checked: date }]
  privacy: { public_ok: boolean, redactions: string[], contains_client_data: boolean }
  portfolio_eligible: boolean
  standalone_eligible: boolean
  media: { cover: path, loop_mp4?: path, loop_webm?: path, poster?: path }
  dates: { started?: date, published: date }
  legacy: { tagline, kind, tech, problem, built, steps, results, next, note, demo_label, order }  (the current fields, kept until each page is remodelled)
}
```

Validation rules that FAIL the build (exit non-zero, CI red):

1. Schema parse failure on any record (zod).
2. Duplicate `id`, duplicate `name` (case-insensitive), duplicate DOM `id` within a rendered page (checked post-build on the HTML).
3. `privacy.public_ok == false` or `contains_client_data == true` while `portfolio_eligible` or `standalone_eligible` is true.
4. Any rendered string matching the secret regex set from `publish.sh`, a `/Users/` path, a `localhost` or `127.0.0.1` URL, an email other than the allowlisted public one, or a `github.com/mrrishit909/<private repo>` URL from the private list.
5. Any internal link, image, video, font or script whose target is not on disk in `dist/` (link check over the built output, base path aware).
6. Any `<img>` or `<video>` without width and height (CLS) or without `alt` (empty alt allowed only when `role=presentation`).
7. Any numeric claim in `summary` or body copy (regex for digits with %, x, ms, s, MB, rows, or currency) that does not appear in an `evidence[].claim`; `evidence.kind` is rendered next to the figure (measured / repo-reported / backtest / recorded / synthetic), which is the current CLAUDE.md rule made mechanical.
8. `demos[].status == live` with `last_checked` older than 30 days (warning locally, failure in the production workflow, which runs a real HTTP check).
9. Missing `media.cover`, or a cover under 1200 px wide, or a loop without both formats when one is present.
10. HTML in a plain-text field, or `<script>`, `<style>`, `style=`, `<link>`, `<font>` in an HTML field (same list build.py enforces today, VERIFIED).
11. Palette contrast under WCAG AA for any token pair the theme declares as text-on-surface (port of `contrast()` in build.py).

Warnings (do not fail): no motion tile yet, `status == in-progress` older than 180 days, summary over 240 chars.

## 6. Routing, navigation, page transitions

PROPOSED:
- URLs stay identical to today: `/projects/` home, `/projects/<slug>/` case, `/projects/all.html` archive (keep the file name so old links hold; add `/projects/archive/` as the canonical and have `all.html` be a meta-refresh plus link). Microsites: `/<repo>/` plus their own sub-routes. Each app sets Astro `site` and `base`; no component ever concatenates `/projects/` by hand; a `url()` helper in `packages/seo` is the only place that joins base + path.
- Navigation is real `<a>` links rendered server-side; the archive's query bar and kind tabs update `?q=` and `?kind=` with `history.replaceState`, and the `<dialog>` deep link `#<slug>` owns one `pushState` entry with a `popstate` handler that closes it (VERIFIED this exists in `catalog.js` per CLAUDE.md; keep that behaviour).
- Page transitions use the View Transitions API through Astro `<ClientRouter>` with `transition:name` on the case title and cover (the existing title transition, VERIFIED in CLAUDE.md, becomes declarative). Browsers without the API get a normal full navigation (Astro falls back automatically); there is no JS-driven fake transition in the fallback. Back/forward: the browser owns history; `transition:persist` is used for the audio manager and the WebGL canvas on the home only; every other island re-initialises on `astro:page-load` and tears down on `astro:before-swap`.
- Scroll restoration: native (`history.scrollRestoration = "auto"`); never override except to scroll to a hash target after a transition.
- Focus: after a transition, focus moves to the new page's `<h1>` (tabindex -1) and the route change is announced through the live region in `packages/a11y`.

## 7. Rendering and performance strategy

PROPOSED:
- Poster first: every WebGL surface renders a `<picture>` poster (webp, sized, `fetchpriority=high` on the home) as the LCP element; the canvas is inserted behind it and cross-faded only when the first frame has drawn. The poster pipeline is `tools/poster.cjs` ported into `packages/qa` (VERIFIED it exists today).
- Lazy WebGL: Three.js loads as a dynamic `import()` from an island that mounts on `client:visible` for case pages and `client:idle` for the home, never on `client:load`. No WebGL on the archive at all.
- Adaptive quality: DPR cap 1.5 on the home, 1.25 on case pages (quality lite, VERIFIED concept in `case.js`), 1.0 under `saveData`, 4 or fewer logical cores, or a battery below 20 percent when the API exists; a frame-time governor drops DPR by 0.25 steps when p95 frame time exceeds 20 ms over 60 frames and raises it back after 300 good frames (port of the adaptive pixel ratio in `instrument.js`, VERIFIED mentioned in CLAUDE.md).
- Visibility pause: `document.visibilitychange` and an IntersectionObserver on the canvas stop the render loop; `requestAnimationFrame` is never left running off-screen.
- Context loss: `webglcontextlost` calls `preventDefault`, shows the poster, and `webglcontextrestored` rebuilds materials and textures from a registry; after two losses in one session the page stays on the poster (VERIFIED: `tests/evidence/gl-loss.cjs` already exercises this).
- Reduced motion: `prefers-reduced-motion: reduce` serves the poster with a single 400 ms opacity reveal and no intro, no parallax, no autoplaying loops (loops become their poster frame with a play control).
- Budgets per page: HTML <= 60 KB, CSS <= 40 KB, JS on first load <= 90 KB gzip excluding lazily imported Three (<= 160 KB gzip, tree-shaken as today), fonts <= 3 files subset woff2 with `font-display: swap` and size-adjusted fallbacks to hold CLS under 0.1. Lighthouse CI asserts these budgets (section 9).
- Images: covers served as webp with an AVIF variant where the build can produce one, three widths, `sizes` attribute, explicit dimensions. Loops: `preload=none`, poster frame set, `muted playsinline loop`, start only when in view.

## 8. Security and privacy rules for public builds

PROPOSED, enforced by the validator and the workflows:
1. The monorepo stays private; only `dist/` of each app is pushed to a public Pages repo. Source maps are not published.
2. The secret and leak scan from `publish.sh` runs on the built `dist/` and on the diff of every PR (VERIFIED the patterns exist; they move into `packages/deploy/scan.sh`).
3. No analytics, no third-party scripts, no CDN fonts or libraries (everything vendored or bundled); a Content Security Policy `<meta http-equiv>` with `default-src 'self'`, `img-src 'self' data:`, `media-src 'self'`, no `unsafe-inline` scripts (inline event handlers forbidden; a lint rule enforces it).
4. Content records with `privacy.public_ok == false` are excluded from every public build and from the sitemap; a private project may be referenced only by name and summary if `redactions` list what was removed.
5. The résumé rule stays: professional claims come only from the résumé record; the validator holds a `claims.allow` list and fails on unlisted professional claims in the about page.
6. External links get `rel="noopener"`; `target=_blank` only on demos. The link checker fetches external demo URLs in the production workflow with a 10 s timeout and marks failures as `unverified` rather than publishing a dead "live" badge.
7. No form posts to third parties; the contact action is `mailto:` plus a copy button (VERIFIED the copy e-mail control exists today).
8. Media never carries EXIF; the image pipeline strips metadata.

## 9. CI/CD, preview isolation, cutover, rollback

PROPOSED (GitHub Actions, free tier; `node_modules` cached by lockfile hash):

Workflow `ci.yml` on push and PR: `npm ci`, lint (eslint + stylelint), `tsc --noEmit`, `vitest` (unit + component via Astro container API), validator (`content validate`), `astro build` for each changed app, post-build link check and duplicate-ID check, Playwright e2e + axe on the built `dist/` served by `astro preview`, Lighthouse CI (`lhci autorun`, 3 runs, budgets asserted: perf 90, a11y 95, BP 95, SEO 95, LCP 2500, CLS 0.1), visual regression against committed baselines (Playwright `toHaveScreenshot` at the 8 widths, reduced-motion variant, 0.2 percent threshold; baselines update only through a labelled PR).

Preview isolation: Pages serves one branch per repo, so previews go to a separate public repo `mrrishit909/atelier-previews` whose `gh-pages` branch holds one folder per app and branch: `/<app>/<branch-slug>/`. The preview workflow builds with `base=/atelier-previews/<app>/<branch-slug>/` (this is why no hand-written base joins are allowed), pushes the folder with `peaceiris/actions-gh-pages` using `keep_files: true` and `destination_dir`, posts the URL on the PR, and a nightly job deletes folders for merged or deleted branches. Previews include `<meta name="robots" content="noindex">`. The evidence harness runs against the preview URL and attaches screenshots and the pacing JSON as workflow artifacts.

Production cutover: `release.yml` is `workflow_dispatch` only, with a GitHub Environment `production` that has a required reviewer (the owner). It builds with the production base, runs the full QA again, then force-pushes `dist/` to the public repo's `gh-pages` branch (for the portfolio: `mrrishit909/projects`, which replaces today's manual merge to `main`; switch the Pages source to `gh-pages` once, at cutover). Every release is tagged `release/<app>/<YYYYMMDD-HHMM>` in the monorepo and the deployed commit hash is written to `dist/version.json` and checked with `curl` after deploy, plus one real screenshot.

Rollback: `rollback.yml` (`workflow_dispatch`, same environment approval) takes a previous release tag, rebuilds nothing, and re-pushes that tag's stored `dist/` (kept as a workflow artifact for 90 days and as a commit on the public `gh-pages` history), then verifies `version.json`. Manual fallback: `git push -f public <previous gh-pages sha>:gh-pages`.

## 10. Phased migration plan

Phase 0 (one evening): create `atelier-x` monorepo, `npm init -w`, copy `content/projects` from the 236 `project.json` files unchanged, write the zod schema with every legacy field accepted as `legacy.*`, run the validator and record the failure list without fixing anything. This yields the real backlog.

Phase 1: port the archive (`all.html`) to Astro first because it has no WebGL: content collection, layout, `catalog.js` as a plain script island, visual baselines, CI green. Deploy to the preview repo only.

Phase 2: port case pages (`project_page()` to a `[slug].astro` route), with `case.js` and the lite instrument as a `client:visible` island; keep `atelier.css` whole; run Lighthouse on 10 sampled pages plus the 3 heaviest.

Phase 3: port the home (the opening, chapters, audio) with `transition:persist` on the canvas; poster pipeline; the full evidence harness; owner visual QA against real screenshots.

Phase 4: first microsite scaffold from `apps/_template` using the shared packages, with a distinct token file; proves the "shared engineering, distinct identity" claim before any further microsite.

Phase 5: production cutover of the portfolio with owner approval; `build.py` kept in the old repo as frozen history, not deleted until one release cycle has passed.

First three concrete tasks:
1. `packages/content/schema.ts` + `bin/validate.ts`: zod schema in section 5, run over the 236 files, print a per-rule failure count. Acceptance: runs in under 5 s, exit code reflects failures, output committed as `docs/validation-baseline.md`.
2. `apps/portfolio` Astro scaffold with `site`/`base` set, the archive route rendering all records, link checker over `dist/`, and `ci.yml` running lint, tsc, vitest, build, link check. Acceptance: CI green on a PR, preview URL posted.
3. `packages/qa/evidence.ts`: port `tests/evidence/responsive.cjs` + `pace.cjs` + `shots.cjs` to a single Playwright script taking a URL, writing screenshots at the 8 widths (plus reduced-motion and 200 percent zoom variants) and `pace.json`. Acceptance: runs against the preview, images opened and read by a human or an independent QA agent before anything is called done (CLAUDE.md rule).

## 11. Open questions for the owner

1. Is a Node toolchain and `node_modules` acceptable in the portfolio build (today it is stdlib Python by design)? If not, option (a) with the Python validator and CI is the plan.
2. Public Pages source: may `mrrishit909/projects` switch from `main` to a `gh-pages` branch for deploys, or must `main` stay the published tree?
3. May a public `atelier-previews` repo exist (previews are public URLs with `noindex`)? Alternative: Cloudflare Pages preview deployments, which memory notes you already use for `portfolio-concepts` behind Access.
4. Which projects are `standalone_eligible` for microsites first, and how many microsites in total this quarter? The template is phase 4; identities are per site and need a brief each.
5. Does `projects-next` get archived now? Nothing in it is reused here except the lesson that the backend path needs accounts you have not created.
6. The archive URL: keep `all.html` forever or redirect to `/archive/` after one release?
7. Evidence kinds: do you accept `synthetic` and `recorded` being printed next to figures on public pages (it is the honest label; it also changes how some case studies read)?
8. Remotion: keep it for tiles and recordings only (offline), or drop it in favour of the existing Playwright + ffmpeg `motion/render.cjs` pipeline, which is already VERIFIED to work?
