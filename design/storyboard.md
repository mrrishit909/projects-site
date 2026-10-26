# Storyboard and motion score: Precision Atelier

Evidence: screenshots in `~/projects-site-evidence/atelier-2026-10-25/r*/`, recordings in `recordings/final/`.

## The opening (measured 3.1 s on the GSAP clock; about 3.4 s from first render on the test Mac)

| t | Object (instrument.js, k = introK) | Words (CSS, html.opening / .words) | Sound |
|---|---|---|---|
| 0.0 | the parts are off-axis at their families' approach distances (the instrument starts there when the opening will play); the group turned 1.2 rad | brand, nav, kicker and the headline are in the first frame; the poster shows until the first WebGL frame | silence |
| 0.0 to 2.0 | k 0 to 1 (power2.inOut): rails from above, the core from the front, slabs from the sides, the lower block from the left, frames from behind, the inner frame, brackets from below, pins from the depth, pads last; each unwinds its yaw as it lands; the group's turn settles | at 0.5 s the lead, the buttons, the domains and the corner lines rise (staggered 120 to 400 ms) | click at 1.9 s when the register locks |
| 2.0 to 2.9 | the signature: closed blends to open (power3.inOut 0.9 s); the register unlocks into the exploded hero | the words are settled; nothing competes | a short texture at 2.0 s |
| 2.9 to 3.1 | rest; html.entered; Replay appears, Skip disappears | | |

Controls: Skip (button, wheel, touch, key) sets the timeline to its end: k = 1, u = 1, entered. Replay kills the timeline
and its listeners (AbortController), scrolls to the top, cuts the ground to green, and runs again. Repeat visits in a
session, hash arrivals and returns from case studies skip the sequence. Reduced motion: no travel; k and u still run in
0.8 + 0.6 s with `introStill`.

## Chapters (scroll-driven; each a pinned screen inside a 185 svh section)

| Chapter | Entry (u 0 to 0.04) | Development (u 0.04 to 0.54) | Settled reading state (u 0.54 to 1) | Interaction | Out |
|---|---|---|---|---|---|
| Hero | the opening | | the exploded hero | drag, tilt (fine pointers); Replay | the words scroll off, the object holds |
| Selected work (orient) | | the object holds | the list of four | links to the chapters | |
| 01 Florida: network | from the previous arrangement (open) | the plate becomes the fact table; the two slabs and two lacquer plates travel to the corners; the pins turn into connectors from the plate's corners; the rails settle as a base | the star schema under AIRPORTS / TIME / CARRIERS / OBSERVATIONS | the departure-hour range (published rates, figure in HTML) | the next chapter's blend |
| 02 dbt: pipeline | from network | four standing frames line up on two long rails: source bars, staging plates, intermediate slabs, the engraved plate as the marts; 31 test pins slot into the frames' top bars from u 0.3 to 0.8 | the row under SOURCE / STAGING / INTERMEDIATE / MARTS, 31 of 31 | the counter follows the scroll both ways; ticks | |
| 03 Forecast: timeline | from pipeline | twelve solid parts stand in time order at the real series' height; twelve thin bars stand ahead at last year's shape and fan apart by the backtest's error; the pins lie as the axis; the bracket marks now | OBSERVED / NOW / FORECAST / 80% RANGE; the figure 1.81% with its backtest definition | | |
| 04 10-K: documents | from timeline | the drawer forms; cards fan back from a shared edge; the ivory passage lifts out and turns to face the visitor (u 0.08 to 0.48) | the answer with its passage; then (u 0.7 to 0.98) the drawer closes and the brackets cross: the refusal (`refusing` class) | | |
| The instrument (system) | | user-controlled: six arrangements, the separate slider (closed to open), turn left/right/reset, drag, arrow keys | | buttons, slider, keys | |
| Handoff | the ivory wedge cuts in; the document ground follows at 92% of the viewport | | | | |
| About (ivory) | | the register rests assembled at 82% / 36%, 0.55 (desktop); on phones it leaves at the handoff (shrinks away below the screen) | the résumé line-up | résumé, LinkedIn, GitHub | |
| Archive (ivory) | | the register small at 86% / 55% | the query and the twelve most recent | the query form | |
| Contact (ivory) | | the register assembled, turning slowly (sin t / 9 s, ± 0.25 rad) | the e-mail as display type | copy e-mail | footer |

Reverse scrolling reverses every blend (targets are functions of scroll; the lerp follows either way). Fast scrolling
jumps the targets and the lerp settles in about 0.5 s. Navigation links arrive at the chapter's target directly.

## Motion contracts (one owner per property)

| Motion | Purpose | Trigger | Space | Duration / interval | Easing | Owner | Interrupt | Reverse | Replay | Touch | Reduced motion | Cost |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Opening arrival | state, causality (parts have axes) | first top arrival in a session; Replay | instrument local | 2.0 s | power2.inOut on k; per-part smoothstep windows | GSAP (k) + instrument.js (matrices) | Skip jumps to the end | n/a | kill + restart | same | no travel (introStill) | 41 draw calls at DPR 1 |
| Signature unlock | reveals the object's purpose (it comes apart) | k reaches 1 | instrument local | 0.9 s | power3.inOut | GSAP (u) | Skip | n/a | yes | same | 0.6 s | same |
| Words arrive | hierarchy | 0.5 s into the opening | CSS | 900 ms staggered | --ease | CSS transitions on html.words | none needed | n/a | class removed and re-added | same | none | trivial |
| Chapter blend | state | scroll position in the chapter | instrument local | u 0.04 to 0.54 of the section | smoothstep per part with a 3% stagger | scroll (targets) + instrument.js (lerp) | scroll | yes | n/a | native scroll | end states, no stagger (ease 1) | same |
| Test pins | causality (tests attach to transforms) | scroll u 0.3 to 0.8 of chapter 2 | instrument local | per scroll | step | scroll | scroll | yes | n/a | same | same | +40 draw calls |
| Passage lift / refusal | time, state | scroll in chapter 4 | instrument local | u 0.08 to 0.48 and 0.7 to 0.98 | smoothstep | scroll | scroll | yes | n/a | same | same | none |
| Ground handoff | space (green scene to ivory reading) | the handoff reaching 92% of the viewport | document | 900 ms | --travel | CSS transition on html[data-field] | none | yes | n/a | same | none (instant) | trivial |
| Chapter words | hierarchy | IntersectionObserver is-in | CSS | 900 ms staggered 80 ms | --ease | CSS | none | re-enter | n/a | same | none | trivial |
| Tilt / drag / turn | exploration | pointer, buttons, keys | group rotation | continuous, 0.985 decay | time-based lerp | instrument.js | reset button | yes | n/a | buttons only (no drag on touch; scroll never trapped) | ease 1 | none |
| Contact turn | rest | time | group rotation | ± 0.25 rad over 9 s | sine | instrument.js | pause | n/a | n/a | same | still | draws every frame (force) |
| Pause | control | the Pause button | all owners | | | home.js | | | | same | | stops the renderer, GSAP, fragments, audio |

Delta time is bounded at 50 ms (a hidden tab's return cannot jump); every rate is `1 - base^dt`, independent of the
monitor's refresh; one requestAnimationFrame loop on the home (home.js `tick`), one on a case page (case.js).
