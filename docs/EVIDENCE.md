# Gate matrix: Precision Atelier review candidate

Statuses: **VERIFIED PASS** (the specified behaviour was exercised and evidence exists), **FAIL** (exercised, did not
meet the requirement), **PARTIAL** (only part of the required scope was checked), **NOT TESTED** (not exercised),
**BLOCKED** (a named dependency prevented checking), **NOT APPLICABLE** (a documented scope reason). "Code inspected"
is recorded separately from runtime verification and never counts as a pass. Rows marked PENDING are being re-run on
the candidate commit and are updated from the raw outputs named in each row (all under
`~/projects-site-evidence/atelier-2026-10-25/`, packaged as `evidence/` in the review archive).

Owner acceptance of the visual and interactive direction: **PENDING** (gate D). No internal score substitutes for it.

Conditions: Apple M3 Pro, macOS; Playwright Chromium with ANGLE Metal (behaviour, pacing, recordings); Chrome 156
through the extension (interactive transition checks on 2969d25); Lighthouse 12.8.2 headless Chrome (software GL);
local `http.server` on 8800 and `serve` with gzip on 8801. Tested build: the candidate commit named in
docs/ATELIER_PROGRESS.md; rows last exercised on 2969d25 say so.

## A. Evidence and baseline

| Check | Status | Evidence | Note |
|---|---|---|---|
| Current pages captured, defects named | VERIFIED PASS (2969d25) | baseline/, docs/DEFECTS.md | ten defects recorded from the 2026-10-26 audit, D-01 to D-10 |
| Audio inventory | VERIFIED PASS | docs/AUDIO.md | a synthesised manager, off by default; failure handling corrected (D-04) |
| Repository, routes, sources, instructions | VERIFIED PASS | docs/ROUTES.md | |

## B. Direction and the instrument package

| Check | Status | Evidence | Note |
|---|---|---|---|
| Arrangements, opening frames, materials rendered and inspected | VERIFIED PASS (2969d25) | spike/, spike2/, r2/zoom-*.png | |
| Front, side and three-quarter views; protected-region drawings | NOT TESTED | | the v2 package items are not yet produced; the lab can render them |
| Posters clean (no lab controls, transparent ground, object present) | PENDING (suite poster-pixel check) | tools/poster.cjs output, portfolio-check.txt | FAIL on 2969d25 (D-01): controls and an opaque ground baked in |

## C. First technical slice

| Check | Status | Evidence | Note |
|---|---|---|---|
| Real WebGL rendering on the home (champagne pixels on the canvas) | PENDING (suite section 3) | portfolio-check.txt | VERIFIED PASS on 2969d25 |
| Assembly, one transformation, controls, keyboard | PENDING | recordings, suite, responsive.json keyboard walk | VERIFIED PASS on 2969d25 for assembly and transformations |
| Mobile composition in the slice | PENDING | r4/m-*, fallbacks/ | PARTIAL on 2969d25 (emulation only) |
| Graphics fallback on the home | PENDING (fallbacks.cjs: six conditions, four aspects) | fallbacks/ | VERIFIED PASS on 2969d25 for no-WebGL and context loss, but the poster itself was defective (D-01) |

## D. Representative journey and owner acceptance

| Check | Status | Evidence | Note |
|---|---|---|---|
| Opening → hero → first transformation → case page → return, recorded | PENDING (record.cjs on the candidate) | recordings/final | VERIFIED PASS on 2969d25 in Playwright and Chrome 156 |
| Route transition in a real browser (viewTransition present, Back restores scroll and focus) | VERIFIED PASS (2969d25, Chrome 156) | docs/ATELIER_PROGRESS.md notes; suite section 10 | not re-run interactively on the candidate; the suite's Back check re-runs |
| Owner's explicit acceptance | PENDING | | the real gate |

## E. Full content and all pages

| Check | Status | Evidence | Note |
|---|---|---|---|
| Every portfolio-owned route on the shared system with the required fields | PENDING (suite section 9, 223 routes) | portfolio-check.txt | VERIFIED PASS on 2969d25 |
| Case-page graphics fallback (the arrangement still) | PENDING (suite section 8; fallbacks.cjs on four page types) | fallbacks/case-* | FAIL on 2969d25 (D-03): an empty hero region |
| Archive: an editorial index, searchable, keyboard-accessible, with status | PENDING (suite sections 2, 11, 12) | portfolio-check.txt | FAIL on 2969d25 (D-02): a thumbnail wall |
| Manual review sample of pages | PARTIAL | r4 and fallbacks captures of the flagship, long-title, thin and CRM pages | not every one of the 223 pages opened by eye; all validated programmatically |

## F. Responsive, access and failure

| Check | Status | Evidence | Note |
|---|---|---|---|
| Widths 360, 390, 768, 1280, 1440 (suite) | PENDING | portfolio-check.txt | VERIFIED PASS on 2969d25 |
| 1024, 1920, phone landscape, 200% zoom, short phones | PENDING (responsive.cjs) | responsive/ | NOT TESTED on 2969d25 (D-10) |
| Keyboard navigation and focus visibility | PENDING (responsive.cjs keyboard walk; suite Tab order) | responsive/*-keyboard-*.png | |
| Screen-reader walkthrough | BLOCKED | | no screen-reader automation in this environment; VoiceOver was not run by hand |
| Automated accessibility scan | PENDING (Lighthouse accessibility) | lh-*.json | 100 on every page at 2969d25 |
| Reduced motion | PENDING (suite section 7; fallbacks reduced captures) | | VERIFIED PASS on 2969d25 |
| Context loss and recovery; network failure; missing assets | PENDING (gl-loss.cjs) | gl-loss.json | VERIFIED PASS on 2969d25 (five cycles) |
| Touch targets, no overflow | PENDING (suite; fallbacks narrow and short) | | |
| Physical device | NOT TESTED | | no real phone was available; every phone figure is viewport emulation |

## G. Performance and lifecycle

| Check | Status | Evidence | Note |
|---|---|---|---|
| Frame pacing per journey, desktop and phone emulation | PENDING (pace.cjs) | pace.json | on 2969d25: p50 16.7 / p99 16.8 ms everywhere, one compile frame of 100 to 200 ms (D-07) |
| Throttled start-up cost with the GPU on | PENDING (throttled.cjs) | throttled.json | 250 ms blocking on 2969d25 |
| Lighthouse mobile LCP <= 2.5 s | PENDING (lighthouse.sh) | lh-*-mobile.json | FAIL on 2969d25: 3.0 to 4.1 s (D-06) |
| Lighthouse desktop | PENDING | lh-*-desktop.json | 99 to 100 on 2969d25 |
| First-view transfer <= 1.5 MB | PENDING | Lighthouse total-byte-weight | 506 to 531 KiB on 2969d25 |
| Lifecycle journey x3 with counters | NOT TESTED | | not yet scripted; pace.json records one loop count and the heap once per run |
| Recordings inspected for blank intervals, snapping, overlap, pacing | PENDING (sheets inspected by eye) | recordings/final/*-sheet.jpg | |

## H. Delivery

| Check | Status | Evidence | Note |
|---|---|---|---|
| Review package self-contained, checksummed, matching the tested source | PENDING (tools/package.sh) | the archive and its .sha256 | the 2026-10-26 zip referenced outside evidence (D-09) |
| Publication | NOT APPLICABLE | | private branch only; the owner publishes |
| Audio gate | see docs/AUDIO.md | | numeric checks only; AUDITORY REVIEW NOT PERFORMED; sound off by default |
