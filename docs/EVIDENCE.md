# Phase gates: Precision Atelier (2026-10-25)

Statuses: PASS, FAIL, BLOCKED, NOT APPLICABLE (with a reason). Tested commit: f48d7ca on `unified-portfolio` (the
suite, Lighthouse, pacing and recordings ran on this build; the docs commit that follows changes no page). Conditions:
Apple M3 Pro, macOS, Chromium (Playwright) with ANGLE Metal and Chrome 156 (the owner's browser through the extension),
local `python3 -m http.server 8800` for behaviour and `serve` with gzip on 8801 for Lighthouse. Evidence root:
`~/projects-site-evidence/atelier-2026-10-25/` (paths below are relative to it).

## Phase A: evidence and baseline

| Check | Status | Evidence | Observation |
|---|---|---|---|
| Visual: current desktop/mobile pages captured, defects named | PASS | baseline/d-*.png, m-*.png (THE BLOCK, bff4f13) | the previous home's red field and record slips; case pages in an ink hall; the owner rejected the direction |
| Audio inventory | PASS | home.js (previous) read | a Web Audio drone bed and pings behind a Sound button, off by default, no files; replaced |
| Repository, routes, factual sources, instructions, authorization | PASS | docs/ATELIER_PROGRESS.md, docs/ROUTES.md | 224 projects, 142 demos; featured.json mislabelled 75.5% as departures (corrected) |
| Exit: inventory and acceptance matrix exist; ambiguities resolved | PASS | this file, docs/ROUTES.md | |

## Phase B: art direction and storyboard

| Check | Status | Evidence | Observation |
|---|---|---|---|
| Opening, hero, each transformation, a case page, mobile, closing rendered and assessed | PASS | spike2/*.png (lab), r1/, r2/ (page), taste/desktop-film-*.jpg | silhouette readable at every state; text column protected on desktop; the hero matches the concept's composition |
| Cue sheet tied to visible events | PASS | docs/AUDIO.md | four cues; the bed rejected |
| State transitions, asset pipeline, budgets, fallbacks, schema, controls specified | PASS | design/storyboard.md, docs/INSTRUMENT.md, docs/PERFORMANCE.md, docs/ROUTES.md | |
| Exit: the direction is concrete and technically plausible; the prototype presented | PASS | r2/d-02-hero.png against refs/precision-atelier-concept.png | the owner's visual verdict on the built page is still the real gate |

## Phase C: technical proof

| Check | Status | Evidence | Observation |
|---|---|---|---|
| Segmented object in a real browser; assembly and one transformation; materials and intermediate frames | PASS | spike/, spike2/ (states, intro k 0.35/0.5/0.7), r2/zoom-*.png | 41 draw calls, 17k triangles; engraving legible at 2x; brass reads champagne after the environment fix |
| Gesture-gated playback, mute, envelope, skip, replay | PASS (numeric) | docs/AUDIO.md; suite section 4 | AUDITORY REVIEW NOT PERFORMED |
| Real WebGL rendering, frame pacing, keyboard controls, mobile strategy, graphics fallback | PASS | suite section 3 (champagne pixels), pace.json, gl-loss.json, r2/m-*.png | see Phase G for the numbers |
| Exit: the central interaction works | PASS | | |

## Phase D: complete homepage slice and project route

| Check | Status | Evidence | Observation |
|---|---|---|---|
| Opening → hero → first project → page → return captured | PASS | recordings/final/opening-fresh.webm, chapter1-*.webm, case-entry-return.webm (+ sheets) | |
| Audio across route boundaries | PASS by construction | docs/AUDIO.md | a new document has no context; the preference is re-applied only after a gesture |
| Direct links, history, focus/scroll restoration, reduced motion, loading, interruption | PASS | real Chrome 156: pageswap viewTransition=true; Back to scrollY 2210 with focus on the clicked button; suite sections 5 to 8 | the View Transition opt-in was missing in the first build and is now in atelier.css |
| Exit | PASS | | |

## Phase E: full content and all project pages

| Check | Status | Evidence | Observation |
|---|---|---|---|
| Distinct chapter choreography; consistent case templates; flagships and edge cases inspected | PASS | r2/d-ch1b..ch4a; r1/d-case-flagship, d-case-long (long title), d-case-thin (thin project), m-case-flagship | manual review sample: the four flagships' home chapters, florida-flight-delays, workforce-scheduler (long title), iris-fisher (thin), twenty-crm (CRM); not every one of the 223 pages was opened by eye; all were validated programmatically |
| Approved cue vocabulary only | PASS | docs/AUDIO.md | |
| Every route/content record validated; links; archive search; provenance | PASS | suite section 9 (223 routes), sections 1, 2, 11, 12 | trading-bot frozen by rule: the one page outside the system |
| Exit: no placeholder, no stale template | PASS | | |

## Phase F: responsive, accessible, failure review

| Check | Status | Evidence | Observation |
|---|---|---|---|
| Widths 390, 768, 1024, 1280, 1440, 1920, phone landscape, short heights, 200% zoom | PARTIAL | suite section 13 (1440, 1280, 768, 390, 360 on four page types); r3/m-*; the chapter button checked at 390x844, 360x800, 390x700; CSS for short phones (max-height 760) and 560 | 1024, 1920, phone landscape and 200% zoom not captured in this pass (listed as remaining) |
| Audio: mute, unavailable, touch, backgrounding, labels | PASS by code path | docs/AUDIO.md | |
| Keyboard, automated accessibility scan, reduced motion, context loss, network failure, overflow, touch targets | PASS | suite sections 6, 7, 13; gl-loss.json; Lighthouse accessibility (docs/PERFORMANCE.md) | screen-reader walkthrough not performed (no VoiceOver pass) |
| Exit | PASS with the listed remainders | | |

## Phase G: performance and adversarial review

| Check | Status | Evidence | Observation |
|---|---|---|---|
| Recordings inspected for stutter, jumps, blanks, repetition | PASS | recordings/final/*-sheet.jpg, taste/desktop-film-*.jpg | see docs/REVIEW.md |
| Audio assets and mixing | NOT APPLICABLE (no files) + AUDITORY REVIEW NOT PERFORMED | docs/AUDIO.md | |
| Production profile, regression paths, memory, adaptive quality | PASS | pace.json (p50 16.7 / p99 16.8 ms on every path, one compile frame in the opening), throttled.json (250 ms blocking at 4x CPU), gl-loss.json (five recoveries, heap flat), lh-*.json | Lighthouse mobile perf 61 / 70 is software-GL rendering in its headless Chrome; reported with the GPU-on throttled figure beside it |
| Exit: no critical/high defect open; budgets met or deviations accepted | PASS with the mobile Lighthouse deviation recorded | docs/PERFORMANCE.md | the 1.5 MB, CLS, draw-call, pacing and recovery budgets are met; mobile lab LCP 3.3 s (font swap on simulated slow 4G) is over the 2.5 s target and is accepted as a lab artefact to re-measure on a real device |

## Phase H: delivery

| Check | Status | Evidence | Observation |
|---|---|---|---|
| Final captures against the concept and the baseline | PASS | r3/ vs baseline/ and refs/ | |
| Default silence on the deployed site | PASS | the preference is session-scoped; no autoplay | |
| Commit, route coverage, deployed state, rollback, sources, licences, commands, limits | see docs/ATELIER_PROGRESS.md | | audience: the PRIVATE repository only (unified-portfolio); the public site is unchanged until the owner publishes |
