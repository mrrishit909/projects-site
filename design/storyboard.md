# Storyboard and motion score: THE BLOCK

Playback: the opening is autoplay (one 2.4 s event, skippable); everything after is scroll-controlled (the block's
state is a function of scroll position; nothing is pinned by hijacking). Sound is off by default and never carries
information. Timing budget for the opening: first paint at HTML, event starts when the module has loaded, ends at 2.4 s,
navigation live throughout.

## The entrance, five states

| State | What is on screen | Owner | Fallback |
|---|---|---|---|
| 1 Immediate first frame | Red field; name at 11vw top-left; nav top-right (Work, Archive, Contact, Résumé); paper card bottom-left with role, four facts, "See the work", "Résumé"; the block as a poster image centre-right | HTML + CSS + `assets/block-poster.webp` | this is the fallback for no JS and no WebGL |
| 2 Loading | The poster stays; nothing counts. The module and the font load in the background; no timer, no fake percentage | browser | if the module fails, state 1 is the page |
| 3 Signature event (2.4 s) | The canvas fades in over the poster with the slips scattered loosely across the right half; they fly into the block (records collected); a plane of light sweeps through the block once (the check); the card's two counts roll to 224 and 219 | GSAP timeline on `intro.k`; the world reads `intro.k` | reduced motion: state 1 straight to 5, counts shown final |
| 4 Handoff | The name scrolls away in normal flow; the block holds its stage (it is fixed and its target moves); the card shrinks to a stub bottom-left; at the first chapter edge the field turns from red to paper and the block from paper to red | scroll progress | reduced motion: instant colour change at the edge |
| 5 Landed | The Work chapter: panel text left, the block performing right | scroll | the DOM order reads top to bottom without any of it |

Skip: wheel, touch, key or a click on "Skip" ends state 3 immediately; the counts land. The event never replays on
internal navigation (session flag) and never runs under reduced motion.

## Chapters

| Chapter | Ground | Block state (scrubbed 0..1 inside the chapter) | Words | Motion | Quiet state |
|---|---|---|---|---|---|
| Hero | red | BLOCK, tilted toward the visitor; pointer tilt; drag turns it | name, role, four facts, two actions | the event, then idle | yes |
| Work 1 Florida flights | paper | SLICE: the block is cut into one fact block and four dimension blocks that step out and back (the star schema) | "When does a flight run late?" 75.5% on time, source, one line, buttons, live report fragment | words rise once as the panel enters; the cut follows scroll | the fragment plays its 6 s loop once |
| Work 2 Retail dbt | paper | LAYER: the block delaminates into staging, intermediate, mart; 31 slips light in turn (tests passing) | "Can a pipeline prove itself?" 31 of 31 tests | as above | |
| Work 3 Retail forecast | paper | BEND: the block's top row bends into the monthly series; the last twelve slips fan out (the range) | "How wrong is a forecast, usually?" 1.81% MAPE | as above | |
| Work 4 10-K retrieval | paper | OPEN: the block opens along its spine; one slip lifts out and faces the visitor (the cited passage) | "Can an answer cite its source?" | as above | |
| The check | red | HOUR: the block sorts into on-time (paper) and late (dark) by the chosen departure hour; the proportion is the published figure | "Pick an hour." a range input 5 a.m. to 11 p.m., the on-time rate, the flight count, the source line "published model, BTS Aug 2025 to Jul 2026, recomputed by check_powerbi.py; a demonstration, not live data" | the sort answers the input within a frame | holds the chosen hour |
| Experience | paper | REST: the block closed, small, lower right, settling | the three roles, the certification, the two degrees, from the résumé, as a line-up at one type size | one entrance | yes, deliberately |
| Archive | paper | SHEET: the block spreads into a flat sheet of slips (224 of them lit), then gathers | "All 224." the query form, the twelve most recent case studies as a line-up, "Every case study" | spread follows scroll | |
| Contact | red | REST, paper, bottom right | the e-mail as display type, the sentence, city, links | the curtain reveal | yes |

## Motion score (one owner per property)

| Effect | Purpose | Owner | Trigger | Start / end | Duration or range | Ease | Reverse | Interrupt | Replay | Keyboard / touch | Reduced motion | Cost |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Slips assemble | the records are collected | block.js, `intro.k` | module ready | scattered / BLOCK | 1.6 s | expo out per slip, staggered by seed | no | skip jumps to end | once per session | any key or tap skips | not run | 1 draw call |
| The check sweep | the second script reads every record | block.js, `intro.sweep` | 1.2 s into the event | x = -1 / x = +1 across the block | 0.9 s | linear | no | with skip | once | same | not run | per-instance colour |
| Counts roll | 224 and 219 arrive with the block | home.js | event end | 0 / final | 0.9 s | cubic out | no | skip lands them | once | same | shown final | none |
| Card to stub | the identity stays | CSS transform from scroll progress | scroll 0..0.6 of hero | full card / 120px stub | scroll | smoothstep | yes | n/a | always | n/a | instant at the edge | transform only |
| Field colour | chapter edges | CSS custom property on `html` from the current chapter | chapter change | red / paper | 600 ms | travel | yes | n/a | always | n/a | instant | background-color on two elements |
| Block state | the project's method | block.js targets lerped | scroll position inside the chapter | state A / state B | per chapter | smoothstep on u, lerp on frames | yes | n/a | always | n/a | holds end states, no lerp | 1 draw call |
| Block stage | where the block sits | block.js group target | chapter | right 55% / top 40svh on phone | lerp | frame lerp | yes | n/a | always | n/a | instant | none |
| Pointer tilt / drag | exploration | block.js | pointer | ±6° / drag angle | continuous | lerp | yes | n/a | always | drag on fine pointers only; keyboard not needed (decorative) | off | none |
| Panel words rise | hierarchy on arrival | CSS `.is-in` class from home.js | panel 55% in view | 18px below, 0 / 0, 1 | 700 ms, stagger 60 ms | entrance | class toggles off | n/a | each arrival | n/a | none; content visible | transform, opacity |
| Fragment loop | the real interface at work | home.js draws the scene at DPR | panel visible | u 0 / 0.92 | 6 s once, then holds | scene's own | no | pauses offscreen | on each arrival | n/a | final frame only | one 2D canvas while visible |
| Hour sort | a visible consequence | block.js from the input | input / change | previous hour / chosen hour | lerp | frame lerp | yes | last value wins | always | native range input | instant | per-instance colour |
| Button press | feedback | CSS | hover, focus, active | 0 / -2px, colour swap | 160 ms | entrance | yes | n/a | always | focus-visible ring | colour only | none |
| Curtain footer | the close | CSS sticky bottom | scroll | under / revealed | scroll | none | yes | n/a | always | n/a | same (no motion involved) | none |

Rests: Experience and Contact hold still except the block's settle and the curtain.

Owners: GSAP owns `intro.*` only; block.js owns every instance matrix and colour; CSS owns every DOM transform and
colour; home.js only toggles classes, sets custom properties and feeds block.js. No property has two owners.
