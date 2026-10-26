# Performance: protocol, budgets and measurements (review candidate 9ecf79b)

## Protocol (written before the final run; thresholds frozen and not adjusted afterwards)

| Item | Value |
|---|---|
| Device | Apple M3 Pro laptop, macOS 27, 60 Hz display; no physical phone was available, so every phone row is **viewport emulation** (390 x 844 at 3x, isMobile, touch) and says so |
| Browsers | Playwright's Chromium (GPU through ANGLE Metal) for pacing, lifecycle, fallbacks and recordings; Lighthouse 12.8.2's headless Chrome (software GL for WebGL) for the lab scores; Chrome 156 (the owner's browser) for the interactive transition checks |
| Quality tier | full on desktop (shadow map, 512 px textures, pixel ratio up to 1.75); lite on phone viewports (no shadow map, 320 px textures, pixel ratio up to 1.5); case pages lite |
| Network and cache | behaviour runs on `python3 -m http.server 8800` (no cache headers: every navigation revalidates); Lighthouse on `serve` with gzip on 8801 with its simulated slow 4G (mobile preset) and 4x CPU; the throttled run uses CDP 4x CPU with the real network |
| Cold and warm | Lighthouse runs are cold (fresh profile per run); pace.cjs is one cold load then warm navigations; lifecycle.cjs is one session with three repetitions (the second and third are warm) |
| Journeys | load and opening (3.4 s sample); slow scroll down 14 s; flick up 0.7 s; reverse scroll; drag (desktop); the six arrangement controls; the separate slider; case entry; Back; four resizes; the three-pass lifecycle journey |
| Repetitions and outliers | pacing: one run per build reported in full (p50, p95, p99, max, frames over 20, 33 and 50 ms), with the previous build's run kept beside it; Lighthouse: one run per page and preset per build (a single run is noisy by about 3 points); lifecycle: three repetitions |
| Measurement method and build | tests/evidence/pace.cjs, throttled.cjs, lifecycle.cjs, lighthouse.sh, gl-loss.cjs; raw JSON in the evidence folder; build identity in portfolio-check.txt and CONDITIONS.txt |

## Frozen thresholds and results

| Threshold | Frozen value | Candidate 9ecf79b | Status |
|---|---|---|---|
| First view transferred, home, cold | <= 1.5 MB | 414 KiB mobile, 446 KiB desktop | VERIFIED PASS |
| LCP, desktop preset | <= 2.5 s | home 0.6, case 0.7, long case 0.8, archive 0.5 s | VERIFIED PASS |
| LCP, mobile preset | <= 2.5 s | home 2.6 s, case 2.4 s, long-title case 3.6 s, archive 2.6 s | **FAIL** on three of four pages (home and archive by 0.1 s; the long-title page by 1.1 s) |
| CLS | <= 0.1 | 0 to 0.006 | VERIFIED PASS |
| Frame time, interaction journeys | p50 <= 16.7, p99 <= 33.4 ms, nothing over 100 ms after the first paint | p50 16.7, p99 16.8 on every journey, resize p99 33.4; the opening's single compile frame 100 ms desktop, 67 ms phone | VERIFIED PASS (interaction); the compile frame is at the frozen 100 ms limit on desktop |
| Opening first compile frame | <= 250 ms unthrottled | 100 ms desktop, 67 ms phone (was 200 / 100) | VERIFIED PASS |
| Blocking at 4x CPU with the GPU on, load plus opening | <= 400 ms | 108 ms phone, 206 ms desktop, 90 ms case phone (was 250 / 292 / 145) | VERIFIED PASS |
| Draw calls / triangles / materials / shadow lights | <= 100 / 50k / 8 / 1 | 41 (81 in the pipeline) / 17,202 / 7 / 1 | VERIFIED PASS |
| Heap after three lifecycle journeys | no monotonic growth beyond 20% of the warm baseline | end of rep 1 / 2 / 3: 14 / 12 / 26 MB, with 25 MB seen inside rep 1 and 19 in rep 2 | PARTIAL: single samples, no monotonic trend visible, not a leak verdict either way |
| Accessibility scan | no serious finding, score >= 95 | 100 on every page, both presets | VERIFIED PASS |

## Mobile LCP: what was found and what changed (D-06)

Lighthouse's network timeline showed every request finishing early; the LCP's "render delay" (2.9 s of 3.3 s) was the
display font: the h1 paints in the fallback face at the first contentful paint (2.0 s on the simulated slow 4G and
4x CPU) and is repainted, larger, when the 129 KB variable font arrives, so LCP was the font's arrival. Corrections:
the font instanced to the roles the site sets (weight 600 to 800, width 75 to 85%, optical size 96) and subset to
Latin (131 KB to 40 KB); the Geist preload dropped so the display font wins bandwidth; the home module fetched at low
priority; on case pages the arrangement still (now the LCP element) loaded eagerly with high priority instead of lazily.
Result: home 3.3 to 2.6 s, case 3.0 to 2.4 s, archive 3.2 to 2.6 s, long-title case 4.1 to 3.6 s. Three pages still
miss 2.5 s on the mobile preset. Practical consequence: on a real slow 4G phone the statement reads at once in the
fallback face and takes about 0.6 s longer than the target to settle into the display face; the long-title page's
still arrives later because its taller hero pushes the image down the fetch order. Proposed next actions: inline the
first-paint CSS on the home (saves one round trip, about 0.3 s on the preset), preload the case still, and measure on a
physical phone before deciding whether the remaining gap matters to a visitor.

## Start-up cost (D-07): where the time went and what changed

Under 4x CPU in the lab, creation took env 136 ms, textures 223 ms, compile 57 ms, first frame at 459 ms (desktop).
Now the textures are drawn in three yielded tasks before the renderer exists and the programs are compiled once before
the first frame, so no task carries textures and compile together: the longest tasks are 207 ms (desktop) and 158 ms
(phone) at 4x, and the opening's compile frame fell from 200 to 100 ms unthrottled on desktop and from 100 to 67 ms on
the phone viewport. The poster covers the interval before the first frame; the words never wait.

## Lighthouse 12.8.2 (gzip, cold, one run per cell)

| Page | Preset | Perf | A11y | BP | SEO | LCP | CLS | TBT | Bytes | LCP element |
|---|---|---|---|---|---|---|---|---|---|---|
| home | desktop | 100 | 100 | | | 0.6 s | 0.002 | 10 ms | 446 KiB | h1 |
| home | mobile | 94 | 100 | 100 | 100 | 2.6 s | 0 | 140 ms | 414 KiB | h1 |
| case (florida-flight-delays) | desktop / mobile | 100 / 97 | 100 / 100 | | | 0.7 / 2.4 s | 0 / 0 | 0 / 30 ms | 556 / 403 KiB | the arrangement still |
| case, long title (workforce-scheduler) | desktop / mobile | 100 / 90 | 100 / 100 | | | 0.8 / 3.6 s | 0.006 / 0 | 0 / 30 ms | 642 / 572 KiB | the arrangement still |
| archive | desktop / mobile | 100 / 95 | 100 / 100 | | | 0.5 / 2.6 s | 0.001 / 0.002 | 0 / 0 ms | 253 / 253 KiB | the lead paragraph |

Previous build 2969d25 for comparison: home mobile 89 (LCP 3.3 s), case mobile 94 (3.0 s), long case 86 (4.1 s),
archive 88 (3.6 s, 577 KiB with the thumbnails).

## Frame pacing (pace.cjs; frames in ms; one run on 9ecf79b)

| Path | Desktop 1440x900 at 2x | Phone 390x844 at 3x (emulated) |
|---|---|---|
| opening (3.4 s) | p50 16.7, p95 16.8, p99 33.4, max 100 (one compile frame) | p50 16.7, p99 16.8, max 67 (one) |
| slow scroll, flick, reverse, controls, slider, case instrument, after Back | p50 16.7, p99 16.8, nothing over 20 ms | same |
| resize x4 | p99 33.4 (one frame per resize) | same |
| case entry / Back navigation | 4 ms / 54 ms | 2 / 55 ms |
| requestAnimationFrame loops | 61 per second (one loop) | 61 |
| JS heap | 7 MB after the opening, 7 on the case page, 13 after Back | 9 / 7 / 12 |

## Graphics failure and recovery (gl-loss.cjs on 9ecf79b)

Five forced context losses: on loss the poster shows and the page stays usable; on restore the canvas draws again with
one loop at 60 per second and the heap at 13 MB after the second cycle; no errors. WebGL unavailable: the poster, the
page entered, Replay harmless; the case page shows its still. Poster missing: no error. Module delayed 4 s: the headline
and nav read at 1 s; the sequence runs on arrival. Three.js failing: the poster stays, the headline is visible,
navigation works, no unhandled rejection.

## Lifecycle (lifecycle.cjs, three repetitions in one session)

Canvases: 5 on the home (the instrument and the four evidence fragments), 1 on a case page, never more. One
requestAnimationFrame loop (60 to 61 per second) at every step. Listeners on window and document: 14 on the home, 4 on
a case page, 11 after a bfcache return; intervals 2 on the home (the clock and the measurement timer). Scroll restored
and focus on the clicked button after every Back. Repeated downloads: every navigation re-requests the shared assets
because the local server sends no cache headers; on GitHub Pages they are cached for ten minutes. Heap: single samples,
no monotonic growth across the three repetitions; not a leak verdict.

## Limitations

- No physical device. The phone rows are emulation on the same GPU; the lite tier is the mitigation, not proof.
- INP is not measured (no field data); TBT is a lab proxy.
- Lighthouse renders WebGL in software; its TBT is reported beside the GPU-on throttled figure.
- The mobile LCP target is missed on three pages by the amounts above and is recorded as FAIL, not redefined.
