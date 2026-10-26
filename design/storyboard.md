# Storyboard and motion score: Precision Atelier

Evidence: screenshots in `~/projects-site-evidence/atelier-2026-10-25/r*/`, recordings in `recordings/final/`.

## The opening (3.0 s on the GSAP clock; design/journey.md section 3 is the shot list)

| t | Object (instrument.js: introD, introK, the lead blend) | Camera (home.js: intro.cam) | Words | Sound |
|---|---|---|---|---|
| 0.0 | assembled except the front core stack, which stands 0.7 ahead of its seat with the dial 2.4 rad off its index | the close-up: scale 2.3, the dial at the right of the statement, ry -0.95 | brand, nav, kicker and the statement on the first frame | silence |
| 0.5 to 1.3 | the dial turns to its index (back.out, a small overshoot) | still | | |
| 0.85 to 1.3 | the core stack seats as the dial aligns (power4.in) | still | | the click at 1.3 |
| 1.3 to 2.5 | the seating unlocks the register by assembly (lead order: head, frame, base, sides, connectors, core, dial, screws; power2.inOut over 1.2 s) | the pull-back: scale 2.3 to 1.0, ry -0.95 to -0.5, rx 0.05 to 0.16 (1.1 s) | the lead, the buttons, the domains and the corner lines rise from 1.5 s (staggered 120 to 400 ms) | the texture at 1.35 |
| 2.5 to 3.0 | settling | settled | | |
| 3.0 | html.entered; Replay appears, Skip disappears | | | |

Controls: Skip (button, wheel, touch, key) sets the timeline to its end. Replay kills the timeline and its listeners,
scrolls to the top, cuts the ground to green, and runs again. Repeat visits in a session, hash arrivals and returns
from case studies skip the sequence. Reduced motion: no close-up, no travel; assembled to exploded in 0.6 s.

## Chapters (scroll-driven; each a pinned screen inside a 185 svh section)

| Chapter | Entry (u 0 to 0.04) | Development (u 0.04 to 0.54) | Settled reading state (u 0.54 to 1) | Interaction | Out |
|---|---|---|---|---|---|
| Hero | the opening | | the exploded hero (split: statement left, register right) | tilt (fine pointers); Replay | the words scroll off, the object closes as the camera approaches |
| Selected work (orient) | the register closes | the camera comes in on the head block: scale 1.9, the tick scale and the plate fill the lower right; negative space on the left | the list of four | links to the chapters | the schema forms as the title arrives |
| 01 Florida: network (the wide composition) | from closed | the title spans the screen; beneath it the core stays assembled as the fact block, the four panels travel to the corners, the connectors turn from the block's corners, the head and base beams and the brackets frame it | the schema under AIRPORTS / TIME / CARRIERS / OBSERVATIONS; the figure, one control line and two actions bottom left, the report fragment bottom right | the departure hour turns the dial to that hour and lights the Time panel by its lateness; the figure line updates (published rates) | the next chapter's blend |
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
