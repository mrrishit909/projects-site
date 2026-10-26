# Precision Atelier: review package

This archive is a **corrected review candidate**. It is not accepted: the owner's explicit acceptance of the working
visual and interactive experience (gate D of the v2 directive) is pending. Nothing in it is published; the public
site is unchanged.

## Contents

| Path | What it is |
|---|---|
| `site/` | the repository at the tested commit (CONDITIONS.txt names it): the home, every case study, the archive, the instrument, the build script, the test suite, the evidence scripts, the docs; no git history |
| `evidence/` | the raw evidence produced on that commit (see the manifest below) |
| `CONDITIONS.txt` | tested commit, machine, browsers, tool versions, display, network conditions |
| `SHA256SUMS` | a checksum of every file in the package; the archive itself has a `.sha256` beside it |

## Start the site

```
cd site
python3 -m http.server 8800 --bind 127.0.0.1
```
Open http://127.0.0.1:8800/ (the home), http://127.0.0.1:8800/all.html (the archive), any `<slug>/` (a case study),
`motion/instrument-lab.html` (the instrument lab). Opening `index.html` from disk does not work: browsers refuse module
scripts on file URLs.

## Rebuild and re-verify

```
python3 build.py                                            # every page from project.json, featured.json, the templates
NODE_PATH=$(npm root -g) node tests/portfolio-check.cjs      # the regression suite against the server on 8800
NODE_PATH=$(npm root -g) node tools/poster.cjs               # the hero posters (lab in poster mode, pixel-checked)
NODE_PATH=$(npm root -g) node tools/config-posters.cjs       # the six arrangement stills for the case pages
EVIDENCE_OUT=/some/folder NODE_PATH=$(npm root -g) node tests/evidence/<script>.cjs   # shots, record, sheets, pace, gl-loss, throttled, fallbacks, responsive
zsh tests/evidence/lighthouse.sh                             # Lighthouse 12.8.2 on a gzip server (8801)
zsh tools/package.sh <commit>                                # this package
```
Requirements: Python 3 (standard library only), Node 24 with Playwright installed globally (`npm i -g playwright` and
its Chromium), cwebp, and npx access for lighthouse, serve and esbuild at the pinned versions in CONDITIONS.txt. The
Three.js bundle is rebuilt per `docs/BUILD-THREE.md`.

## Evidence manifest

| Artefact (under `evidence/`) | Demonstrates |
|---|---|
| `portfolio-check.txt` | the regression suite's output on the tested commit (every check named) |
| `refs/precision-atelier-concept.png` | the owner's concept image, the visual target |
| `baseline/` | the previous home (THE BLOCK) before this work |
| `spike/`, `spike2/` | the instrument lab's modelling proof: every arrangement and three opening frames |
| `r1/`, `r2/`, `r3/`, `r4/` | page captures at desktop and phone at every stop, by round; `r4` is the candidate |
| `recordings/final/*.webm` + `*-sheet.jpg` | the opening (fresh, skip, replay, reduced), each flagship's transformation, reverse scroll, the system controls and a drag, project entry and Back, the closing, pause and resume, context loss and recovery, the phone opening and walk; six-frame contact sheets per clip |
| `pace.json` | frame-time distributions (p50, p95, p99, max, long frames) per journey at desktop 2x and phone 3x emulation, navigation times, loop count, heap |
| `throttled.json` | long tasks and blocking time with the GPU on and the CPU throttled 4x (the honest JavaScript cost beside Lighthouse's software-GL figure) |
| `gl-loss.json` | five forced context losses and recoveries, WebGL unavailable, poster missing, module delayed, Three.js failing |
| `fallbacks/` | the home under cold, delayed-module, no-JavaScript, no-WebGL, context-lost and missing-poster conditions at four aspects; four case pages under no-WebGL, failed import, slow assets, no-JavaScript, reduced motion, narrow and short viewports; `fallbacks.json` with overflow and still state |
| `responsive/` | 1024, 1920, phone landscape, 200% zoom and short-phone captures of five pages, keyboard-walk captures, `responsive.json` with overflow and hidden-content audit |
| `lh-*.json`, `lighthouse.log` | Lighthouse 12.8.2 reports (mobile and desktop presets) for the home, two case pages and the archive |
| `taste/` | the taste inspector's report and film strips |
| `audio` | see `site/docs/AUDIO.md`: numeric envelope checks; AUDITORY REVIEW NOT PERFORMED |
| `site/docs/DEFECTS.md`, `site/docs/EVIDENCE.md` | the defect ledger and the gate matrix for this candidate |

## What the recordings show

`recordings/final/opening-fresh.webm` is the intended arrival (parts off-axis, assembly, the unlock into the exploded
hero); `chapter1-florida-flight-delays.webm` to `chapter4-sec-10k-rag.webm` are the four transformations scrubbed by
scroll; `case-entry-return.webm` is the route transition and Back; `system-controls-drag.webm` the arrangement buttons,
the separate slider and a drag; `pause-resume.webm` and `context-loss.webm` the two interruption cases;
`phone-walk.webm` the phone composition end to end.
