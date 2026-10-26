# Gate matrix: Precision Atelier review candidate

Statuses: **VERIFIED PASS** (the specified behaviour was exercised and evidence exists), **FAIL** (exercised, did not
meet the requirement), **PARTIAL** (only part of the required scope was checked), **NOT TESTED** (not exercised),
**BLOCKED** (a named dependency prevented checking), **NOT APPLICABLE** (a documented scope reason). "Code inspected"
is recorded separately from runtime verification and never counts as a pass. Every row was updated from the raw outputs named in it after the run on the candidate commit (all under
`~/projects-site-evidence/atelier-2026-10-25/`, packaged as `evidence/` in the review archive).

Owner acceptance of the visual and interactive direction: **PENDING** (gate D). No internal score substitutes for it.

Conditions: Apple M3 Pro, macOS; Playwright Chromium with ANGLE Metal (behaviour, pacing, recordings); Chrome 156
through the extension (interactive transition checks on 2969d25); Lighthouse 12.8.2 headless Chrome (software GL);
local `http.server` on 8800 and `serve` with gzip on 8801. Tested build: the candidate commit named in
docs/ATELIER_PROGRESS.md; the candidate is **9ecf79b** (suite: 113 checks, all passed; evidence/portfolio-check.txt).

## A. Evidence and baseline

| Check | Status | Evidence | Note |
|---|---|---|---|
| Current pages captured, defects named | VERIFIED PASS | baseline/, docs/DEFECTS.md | ten defects from the 2026-10-26 audit, D-01 to D-10, each with a retest |
| Audio inventory | VERIFIED PASS | docs/AUDIO.md | a synthesised manager, off by default; failure handling corrected (D-04) |
| Repository, routes, sources, instructions | VERIFIED PASS | docs/ROUTES.md | |

## B. Direction and the instrument package

| Check | Status | Evidence | Note |
|---|---|---|---|
| Arrangements, opening frames, materials rendered and inspected | VERIFIED PASS | spike/, spike2/, r2/zoom-*.png, r4/ | |
| Front, side and three-quarter views; protected-region drawings | NOT TESTED | | the v2 package items are not yet produced; the lab can render them |
| Posters clean (no lab controls, transparent ground, object present) | VERIFIED PASS | portfolio-check.txt (the pixel check on 8 images), tools/poster.cjs log, fallbacks/*-nowebgl.png | FAIL on 2969d25 (D-01); the export tool now refuses unclean exports |

## C. First technical slice

| Check | Status | Evidence | Note |
|---|---|---|---|
| Real WebGL rendering on the home (champagne pixels on the canvas) | VERIFIED PASS | portfolio-check.txt (section 3), gl-loss.json before: 4.85% champagne | the live scene, not the poster |
| Assembly, one transformation, controls, keyboard | VERIFIED PASS | recordings/final (opening-fresh, chapter1 to 4, system-controls-drag), suite section 4, responsive.json keyboard walks | |
| Mobile composition in the slice | PARTIAL | r4/m-*, fallbacks/, responsive/ (landscape, short), phone-walk recording | emulation only; no physical phone |
| Graphics fallback on the home | VERIFIED PASS | fallbacks/home-* (cold, delayed module, no JavaScript, no WebGL, context lost and restored, poster missing; desktop, phone, 1024 square, 1920 wide), fallbacks.json | 84 captures, no overflow |

## D. Representative journey and owner acceptance

| Check | Status | Evidence | Note |
|---|---|---|---|
| Opening → hero → first transformation → case page → return, recorded | VERIFIED PASS | recordings/final/opening-fresh, chapter1-florida-flight-delays, case-entry-return (+ sheets); lifecycle.json | |
| Route transition in a real browser (viewTransition present, Back restores scroll and focus) | PARTIAL | Chrome 156 interactive check on 2969d25; on 9ecf79b the suite's Back check and lifecycle.json (scroll restored, focus on the button, three times) | the interactive Chrome check was not repeated on the candidate; the transition code did not change |
| Owner's explicit acceptance | PENDING | | the real gate |

## E. Full content and all pages

| Check | Status | Evidence | Note |
|---|---|---|---|
| Every portfolio-owned route on the shared system with the required fields | VERIFIED PASS | portfolio-check.txt section 9 (223 routes) | trading-bot frozen by the owner's rule |
| Case-page graphics fallback (the arrangement still) | VERIFIED PASS | suite section 8 (no WebGL, failed import); fallbacks/case-* (flagship, long title, thin, CRM under no WebGL, failed import, slow assets, no JavaScript, reduced motion, narrow and short) | FAIL on 2969d25 (D-03) |
| Archive: an editorial index, searchable, keyboard-accessible, with status | VERIFIED PASS | suite sections 2, 11, 12; r4/*-archive-page.png; responsive/archive-* | FAIL on 2969d25 (D-02) |
| Manual review sample of pages | PARTIAL | r4 and fallbacks captures of the flagship, long-title, thin and CRM pages | not every one of the 223 pages opened by eye; all validated programmatically |

## F. Responsive, access and failure

| Check | Status | Evidence | Note |
|---|---|---|---|
| Widths 360, 390, 768, 1280, 1440 (suite) | VERIFIED PASS | portfolio-check.txt section 13 | |
| 1024, 1920, phone landscape, 200% zoom, short phones | VERIFIED PASS | responsive/ (25 captures, responsive.json: no overflow; nothing hidden except the Skip control outside the opening) | 200% zoom is emulated as a 720 x 450 layout viewport |
| Keyboard navigation and focus visibility | VERIFIED PASS | responsive/home-keyboard-*.png, flagship-keyboard-*.png, responsive.json tab stops with outline styles; suite section 6 | |
| Screen-reader walkthrough | BLOCKED | | no screen-reader automation in this environment; VoiceOver was not run by hand |
| Automated accessibility scan | VERIFIED PASS | lh-*.json: 100 on every page, both presets | |
| Reduced motion | VERIFIED PASS | suite section 7; fallbacks/case-*-reduced; recordings/final/opening-reduced | |
| Context loss and recovery; network failure; missing assets | VERIFIED PASS | gl-loss.json (five cycles), recordings/final/context-loss | |
| Touch targets, no overflow | VERIFIED PASS | suite section 13 (buttons >= 44 px on screen at 390 and 360), fallbacks.json and responsive.json (no overflow) | |
| Physical device | NOT TESTED | | no real phone was available; every phone figure is viewport emulation |

## G. Performance and lifecycle

| Check | Status | Evidence | Note |
|---|---|---|---|
| Frame pacing per journey, desktop and phone emulation | VERIFIED PASS | pace.json: p50 16.7 / p99 16.8 ms on every journey; the compile frame 100 ms desktop, 67 ms phone | |
| Throttled start-up cost with the GPU on | VERIFIED PASS | throttled.json: 108 ms phone, 206 ms desktop, 90 ms case (threshold 400) | |
| Lighthouse mobile LCP <= 2.5 s | **FAIL** | lh-*-mobile.json: home 2.6, case 2.4, long case 3.6, archive 2.6 s | improved from 3.0 to 4.1 s; consequence and next actions in docs/PERFORMANCE.md |
| Lighthouse desktop | VERIFIED PASS | lh-*-desktop.json: 100 on every page | |
| First-view transfer <= 1.5 MB | VERIFIED PASS | 414 KiB mobile, 446 KiB desktop | |
| Lifecycle journey x3 with counters | PARTIAL | lifecycle.json: canvases, loops, listeners, intervals, scroll and focus restoration verified; heap is single samples with no monotonic growth, which is not a leak verdict | |
| Recordings inspected for blank intervals, snapping, overlap, pacing | VERIFIED PASS | 16 contact sheets read (docs/REVIEW.md round 4) | |

## H. Delivery

| Check | Status | Evidence | Note |
|---|---|---|---|
| Review package self-contained, checksummed, matching the tested source | VERIFIED PASS | ~/Downloads/precision-atelier-review-<date>-<commit>.zip and .sha256; the script diffs the packaged site against the commit | |
| Publication | NOT APPLICABLE | | private branch only; the owner publishes |
| Audio gate | see docs/AUDIO.md | | numeric checks only; AUDITORY REVIEW NOT PERFORMED; sound off by default |
