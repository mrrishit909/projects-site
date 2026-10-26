# Performance: budgets and measurements (Precision Atelier, 2026-10-25)

Machine: Apple M3 Pro, macOS, 60 Hz display. Browsers: Chromium (Playwright) with ANGLE Metal for behaviour and
pacing; Lighthouse 12.8.2's headless Chrome for the lab scores. Phone rows are viewport emulation (390x844 at 3x,
CPU throttled 4x where stated), not a real device. Raw files: `~/projects-site-evidence/atelier-2026-10-25/`
(pace.json, throttled.json, gl-loss.json, lh-*.json, lighthouse.log).

## Budgets (set before the production assets)

| Budget | Target | Result |
|---|---|---|
| First view transferred (home, cold) | <= 1.5 MB | 506 KiB mobile / 531 KiB desktop (Lighthouse total-byte-weight, gzip) |
| LCP / CLS (lab) | <= 2.5 s / <= 0.1 | desktop 0.7 s / 0; mobile (slow 4G, 4x CPU) 3.3 s / 0: LCP over on the mobile preset, see below |
| INP | not claimed | no field data; lab TBT reported below and not called INP |
| Draw calls / triangles / materials / lights | <= 100 / <= 50k / <= 8 / 1 shadow light | 41 (81 in the pipeline) / 17,202 / 7 / 1 |
| Shadow map | one 1024 px, full quality only | desktop only; phones and case pages run lite (no shadow) |
| Pixel ratio | 1, rising to 1.75 (home desktop) / 1.5 (lite) with hysteresis | rose to 1.75 in Chrome 156 on the test Mac |
| Texture memory | about 1 MB, 6 canvas textures | 512 px marble on desktop, 320 px on phones, 384 / 256 on case pages |
| Frame pacing | p50 <= 16.7 ms, p99 <= 33 ms | met everywhere below except the opening's single compile frame |

## First-view weight (home)

| Resource | Size |
|---|---|
| Bricolage Grotesque (variable, latin) | 129 KB |
| Three.js bundle (gzip) | 122 KB |
| Geist Regular + Medium, JetBrains Mono, Geist Mono (the fragments) | 44 + 46 + 31 + 49 KB |
| GSAP (gzip) | 28 KB |
| posters | 37 KB desktop, 12 KB phone |
| HTML + atelier.css + home.js + instrument.js + four scenes (gzip) | about 60 KB |

## Lighthouse 12.8.2 (production files served with gzip by `serve` on 8801; final run on the committed build)

| Page | Preset | Perf | A11y | BP | SEO | LCP | CLS | TBT | Bytes | LCP element |
|---|---|---|---|---|---|---|---|---|---|---|
| home | desktop | 100 | 100 | | | 0.7 s | 0 | 10 ms | 531 KiB | h1 |
| home | mobile | 89 | 100 | 100 | 100 | 3.3 s | 0 | 160 ms | 506 KiB | h1 |
| case (florida-flight-delays) | desktop | 100 | 100 | | | 0.8 s | 0 | 0 ms | 628 KiB | h1 |
| case | mobile | 94 | 100 | 100 | 100 | 3.0 s | 0 | 90 ms | 475 KiB | summary dd |
| case, long title (workforce-scheduler) | desktop / mobile | 99 / 86 | 100 / 100 | | | 0.8 / 4.1 s | 0.006 / 0 | 0 / 90 ms | 711 / 641 KiB | h1 / tagline |
| archive | desktop / mobile | 100 / 88 | 100 / 100 | | | 0.7 / 3.6 s | 0.012 / 0.021 | 0 / 0 ms | 618 / 577 KiB | first thumbnail |

An earlier run of the same pages (before phones were switched to the lite quality and smaller textures) scored the
home at 61 on mobile with a TBT of 3,020 ms. Lighthouse's headless Chrome renders WebGL in software (SwiftShader), so
the physical materials and the shadow map were being drawn on the CPU inside the animation frames; the lite quality
removed most of that and the final mobile TBT is 160 ms. With the GPU on and the CPU throttled 4x through CDP
(throttled.cjs, the same phone viewport), the long tasks during load plus the whole opening sum to:

| Page | Long tasks (> 50 ms) | Sum over 50 ms (TBT-like) |
|---|---|---|
| home, phone 390x844, CPU 4x, GPU on | 298 ms (textures + first compile), 52 ms | 250 ms |
| home, desktop 1440x900, CPU 4x, GPU on | 59 ms, 333 ms | 292 ms |
| case, phone, CPU 4x, GPU on | 61, 175, 59 ms | 145 ms |

The remaining mobile deviations are the lab LCP on the simulated slow 4G (3.0 to 4.1 s against the 2.5 s target): the
largest text repaints when the 129 KB display font arrives, which is the font swap, not a blocked render; the fallback
text paints at once. A further subset of Bricolage would cut it; it is listed as a remaining limitation rather than
done. Desktop meets every target; mobile performance scores sit at 86 to 94 against the portfolio gate's 90.

## Frame pacing (pace.cjs; frames in ms)

| Path | Desktop 1440x900 at 2x | Phone 390x844 at 3x (emulated) |
|---|---|---|
| opening (3.4 s) | p50 16.7, p95 16.8, p99 33.4, max 200 (one compile frame) | p50 16.7, p99 16.8, max 100 (one) |
| slow scroll down 14 s | p50 16.7, p95 16.8, p99 16.8, 0 over 20 | same |
| flick up 0.7 s | p50 16.7, p99 16.8 | same |
| reverse scroll | p50 16.7, p99 16.8 | same |
| drag (desktop) | p50 16.7, p99 16.8 | not applicable (no drag on touch) |
| arrangement controls, separate slider | p50 16.7, p99 16.8 | same |
| case entry / Back | 5 ms / 135 ms navigation; case instrument p50 16.7 | 4 / 125 ms |
| resize x4 | p99 33.4 (one frame per resize) | same |
| requestAnimationFrame loops | 61 per second (one loop) | 61 |
| JS heap | 6 MB after the opening, 16 MB after Back | 12 / 19 MB |

## Graphics failure and recovery (gl-loss.cjs)

Five forced context losses: on loss the poster shows and the page stays usable (the hour input still updates, scroll
works); on restore the canvas draws again, one requestAnimationFrame loop (60 per second), heap flat at 13 MB, no
errors. WebGL unavailable: poster, entered, Replay harmless; case page reads with its words and summary. Poster
missing: no error, the canvas carries. home.js delayed 4 s: the headline and nav are readable at 1 s, the sequence
runs on arrival. Three.js failing to load: the poster stays, the headline is visible, navigation works, no unhandled
rejection.

## Limitations

- One machine; no real phone. The lite quality on phones (no shadow map, 320 px textures, pixel ratio capped at 1.5) is
  the mitigation, not proof of a mid-range Android's behaviour.
- INP not measured. Lighthouse's TBT on mobile is dominated by software GL in its headless Chrome; the throttled
  measurement above is the honest JavaScript figure, and both are reported.
- The opening's first rendered frame is one long task (shader compile, 100 to 200 ms unthrottled) under the poster.
