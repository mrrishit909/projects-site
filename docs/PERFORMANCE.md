# Performance: THE BLOCK (measured 2026-10-25, second pass)

Conditions: MacBook (Apple Silicon, macOS 27, 60 Hz display), Playwright Chromium 1.64 with ANGLE Metal, local servers
(`python3 -m http.server 8800` for the suite, captures and pacing; `npx serve@14.2.4 -l 8801 -s .` with gzip for
Lighthouse). Lighthouse 12.8.2, mobile preset (simulated Moto G Power, slow 4G, 4x CPU throttle). Laboratory numbers; no
field data and no real phone were measured. Pacing samples requestAnimationFrame deltas in the page, warm cache, over
the stated windows. Build: the working tree committed as the second THE BLOCK commit (see README).

## Budgets

| Budget | Target | Before (2d0763a) | After | Evidence |
|---|---|---|---|---|
| First view transferred | about 1.5 MB | 420 KiB | 430 KiB (the poster grew with the shadow) | lh-index-mobile.json |
| Lighthouse mobile, home | 90 / 95 / 90 / 90 | 98 / 100 / 100 / 100 | 98 / 100 / 100 / 100 | lh-index-mobile.json (a run with another Chrome session open scored 76 with TBT 1,000 ms; two clean reruns gave 98, TBT 30 and 50 ms) |
| Lighthouse mobile, archive | same | 97 / 100 / 100 / 100 | unchanged (not retouched this pass) | lh-all-mobile.json |
| LCP / CLS / TBT, home | 2.5 s / 0.1 / low | 2.0 s / 0.003 / 0 ms | 2.0 s / 0.004 / 50 ms | same |

## Frame pacing (pace.json; before in pace-before-2d0763a.json)

Desktop 1440x900, device scale 2:

| Path | Window | Median | p95 | p99 | Max | Over 33 ms |
|---|---|---|---|---|---|---|
| Opening (from first paint) | 3 s | 16.7 | 16.7 | 33.3 | 130 | 2 (the first rendered frame: shader and shadow-map compile) |
| Scroll down | 14 s | 16.7 | 16.8 | 16.8 | 16.8 | 0 |
| Fast flick | 0.9 s | 16.7 | 16.7 | 16.8 | 16.8 | 0 |
| Reverse scroll | 6 s | 16.7 | 16.7 | 16.8 | 183 | 1 (one frame; not reproduced in the earlier run of the same build, nor on the phone viewport) |
| Hour sweep | 4 s | 16.7 | 16.8 | 16.8 | 16.8 | 0 |
| Return from a case study | 2 s | 16.7 | 16.8 | 16.8 | 16.8 | 0 |
| Project jumps (four panels, 700 ms apart) | 5.6 s | 16.7 | 16.8 | 16.8 | 16.8 | 0 |
| Replay | 3 s | 16.7 | 16.8 | 16.8 | 16.8 | 0 |

Phone viewport 390x844 (emulated on this Mac, not a device): identical medians; the opening's first frame 114 ms; no
other frame over 20 ms. JS heap after the whole run: 5 to 6 MB.

Visible recordings (recordings/final/*.webm) were read as contact sheets; no visible hitch beyond the first frame.

## Scene budget

| Item | Value |
|---|---|
| Draw calls | 2 (the instanced slips and the shadow-only ground), plus the shadow pass |
| Instances | 1,440 desktop, 1,008 phone; 1 BoxGeometry, 1 Lambert material, 1 ShadowMaterial |
| Lights | 1 hemisphere, 1 directional key with a 1024 px PCF shadow map, 1 directional fill |
| Textures | none on the GPU (the fragments are DOM canvases) |
| Pixel ratio | starts at 1; rises to min(1.5, device) after 90 fast frames; drops to 1 after 40 slow frames and locks 20 s |
| Idle | the draw is skipped after 12 settled frames outside the opening; fragments draw only while on screen |
| Per frame on the CPU | 1,440 x 10 lerps, one matrix compose and one colour per slip; during the opening two more evaluations per slip |

## Graphics failure (gl-loss.json)

Five forced losses and restores: poster shown on loss, canvas back on restore, one render loop throughout, heap flat
at 6 MB, no errors. WebGL unavailable: poster, counts final, Replay harmless. Poster missing: no error. Module delayed
4 s: the HTML frame is readable at once and the sequence runs when the module arrives.

## Deviations and limits

- INP is not measured in the field; the proxies are TBT 50 ms and the hour sweep's pacing.
- No real phone; the phone numbers are a phone viewport on this Mac's GPU.
- One long frame at the first render (shader compile with the shadow map) is covered by the poster; it could be moved
  earlier with a warm-up render behind the poster, not done.
- One 183 ms frame appeared once during the reverse scroll on one desktop run and not on the others; cause not found.
