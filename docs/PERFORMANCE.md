# Performance: THE BLOCK (measured 2026-10-25)

Conditions: MacBook (Apple Silicon, macOS 27), Playwright Chromium 1.64 with ANGLE Metal, local servers (`python3 -m
http.server 8800` for the suite and captures; `npx serve@14.2.4 -l 8801 -s .` with gzip for Lighthouse). Lighthouse
12.8.2, mobile preset (simulated Moto G Power, slow 4G throttling). Laboratory numbers; no field data and no real phone
were measured. Build: the working tree at the commit named in the README.

## Budgets and what was measured

| Budget | Target | Measured | Evidence |
|---|---|---|---|
| First view transferred (HTML, CSS, JS, fonts, poster, module) | about 1.5 MB | 420 KiB on the home (gzip); 394 KiB on the archive | lh-index-mobile.json, lh-all-mobile.json (`total-byte-weight`) |
| Largest requests | | three.module.min.js 121 KiB, Geist faces 44 to 49 KiB each (loaded for the fragments), General Sans 22 to 23 KiB each, poster 30 KiB, GSAP 28 KiB | network-requests audit |
| Lighthouse mobile, home | 90+ / 95+ / 90+ / 90+ | performance 98, accessibility 100, best practices 100, SEO 100 | lh-index-mobile.json |
| Lighthouse mobile, archive | same | performance 87, accessibility 96 (one colour-contrast node, fixed after this run), best practices 100, SEO 100 | lh-all-mobile.json |
| LCP / CLS / TBT, home | 2.5 s / 0.1 / low | 2.0 s / 0.003 / 0 ms (FCP 1.8 s, TTI 2.0 s) | same |
| Frame pacing, desktop 1440x900 at device scale 2 | near 16.7 ms, no stalls | opening 16.7 ms median (one 130 ms frame at the first paint, the module compiling), scroll down 14 s 16.7 median / 16.8 p95 / 0 over 33 ms, flick 0 over 33, reverse 0 over 33, hour input 0 over 33, return from a case study one 64 ms frame | pace.json |
| Frame pacing, phone viewport 390x844 at device scale 2 (emulated on the Mac GPU, not a phone) | 30+ fps | 16.7 ms median on every path, one 114 ms frame at the first paint | pace.json |
| Scene budget | one draw call, bounded instances | 1 InstancedMesh of 1,440 slips (1,008 on phones), 1 BoxGeometry, 1 Lambert material, 2 directional lights and 1 hemisphere light, no post pass, no shadows, no textures | block.js |
| Pixel ratio | start 1, raise to 1.5 only with headroom, hysteresis | starts at 1; after 90 fast frames rises to min(1.5, device); steps down to 1 after 40 slow frames and locks for 20 s | block.js `update` |
| Idle cost | no draw when nothing moves | the frame skips `renderer.render` after 12 settled frames; the fragments draw only while on screen and stop at the end of their loop | block.js, home.js |
| Texture memory | none | the fragments are 2D canvases in the DOM at device resolution, not GPU textures | |

## Deviations and limits

- INP was not measured in the field; the lab proxy is TBT 0 ms and the hour input's pacing (0 frames over 33 ms while
  the value sweeps).
- A real mid-range phone was not available; the phone numbers are a phone viewport on this Mac's GPU.
- The archive page's performance score (87) is the thumbnail grid's first row of three 880 px images on slow 4G; it was
  not changed in this pass.
- The one long frame at the opening is the Three.js module compiling and the first shader compile; the poster covers it.
- Context loss: the canvas listens for `webglcontextlost` (poster shown) and `webglcontextrestored` (canvas back); tested by
  code reading only, not by forcing a loss.
