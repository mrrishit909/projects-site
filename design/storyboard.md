# Storyboard and motion score: THE BLOCK (revised 2026-10-25, second pass)

Playback: the opening is autoplay (one 2.6 s sequence, skippable, replayable); everything after is scroll-controlled
(the block's state is a function of scroll position; nothing is pinned by hijacking; native scroll, no Lenis). Sound is
off by default and never carries information. Timing budget for the opening: first paint at HTML, the sequence starts
when the module has loaded, ends at 2.6 s, navigation live throughout.

## What the slips are

The block is 6 x 40 x 6 = 1,440 slips on desktop (6 x 28 x 6 = 1,008 on phones). The count is an artistic construction
chosen for the silhouette and the frame budget; it is not a record count, a case-study count or a repository count. The
page says so on the hero card ("It is not a count."). The counts that are facts (224 case studies, 219 public
repositories) are read from the data at build time and shown as numbers.

## The entrance, five states

| State | Time | What is on screen | Block | Camera | Type | Owner | Fallback |
|---|---|---|---|---|---|---|---|
| 1 Opening frame | 0 s | Red field; name at 11vw top-left; the line under it; nav top-right (Work, Archive, Contact, Résumé); the card bottom-left (what is here, the two counts, the note that the block is not a count, See the work, Résumé); the block as the poster, centre-right | poster image of the settled block | fixed, 32° fov, the block at 70% / 56% of the viewport | all visible and selectable | HTML + CSS + `assets/block-poster.webp` | this is the page without JavaScript or WebGL |
| 2 Anticipation | 0 to 0.8 s | the canvas replaces the poster; the slips loosen apart from the top row down, each lifting and tilting a little; the counts read 0; the block is turned 12° further away | loose (per-slip offsets from a seeded table, up to 1.4 units) | still | the two counts show 0 | block.js from `intro.k` 0 to 0.3 | reduced motion: not run |
| 3 Signature event | 0.8 to 2.2 s | a band of light passes from the top of the block to the bottom; every row it passes is collected back into place (the check reads each record and files it); the counts roll up from 0 to 224 and 219 in step | collected row by row behind the plane; the band lights the rows it touches | the block turns back toward the visitor through the pass | counts rolling | block.js `introAt(k)`, GSAP on the counts | reduced motion: the band alone passes down the settled block (1.4 s), the counts show final |
| 4 Resolution | 2.2 to 2.6 s | the last rows settle, the band leaves at the base, the block is whole, the Replay control appears in the top bar | settled, scale eases from 94% to 100% | settled | counts final | block.js | |
| 5 Handoff | on scroll | the name scrolls away while the block holds its stage; the top bar takes the name as a stub; at the work chapter the field turns red to paper and the block paper to red over 600 ms, and the first operation begins as the panel's words arrive | BLOCK to SLICE from 12% of the first panel | same axis, the block moves 4% up the screen | panel words rise | scroll | reduced motion: instant changes |

Skip: wheel, touch, any key or the Skip button ends the sequence immediately; the counts land. Replay: the top bar's
"Replay opening" (visible once entered) scrolls to the top, cuts the field to red, kills the previous timeline and its
listeners (an AbortController per run), and runs the sequence again; under reduced motion it runs the reduced version.
Once per session for normal visits (sessionStorage `seen`); never on a return from a case study or a hash arrival.

Recordings: `~/projects-site-evidence/redesign-2026-10-25/recordings/final/opening-fresh.webm` (a fresh session),
`opening-replay.webm` (scroll, then Replay), `opening-reduced.webm` (reduced motion, then Replay), with six-frame contact
sheets beside them.

## Chapters and what carries across each boundary

| Boundary | What carries | What changes |
|---|---|---|
| Opening to hero | the block, its position and axis; the name and card were there from the first frame | the band leaves; Replay appears |
| Hero to work | the block holds its stage while the name scrolls off; the top bar keeps the name | field red to paper, block paper to red (600 ms); the block begins to cut |
| Panel to panel | the block returns to BLOCK between operations, same stage, same axis; the fragment column stays in place | the operation; the words |
| Work to the check | the block's stage and axis | field back to red, block back to paper; the operation becomes the hour cut |
| The check to experience | the block, shrinking to the upper right | field to paper; the block rests (the chapter is a rest) |
| Experience to archive | the block | the block spreads into the sheet of 224 lit slips and gathers again |
| Archive to contact | the block, small, upper right | field to red; the e-mail is the statement |

Between panels the scroll runway (0 to 12% of each panel) is where the block returns to BLOCK, so each operation starts
from the same solid and the transformations never overlap.

## Motion score (one owner per property)

| Effect | Purpose | Owner | Trigger | Start / end | Duration or range | Ease | Reverse | Interrupt | Replay | Keyboard / touch | Reduced motion | Cost |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Loosen | anticipation | block.js `introAt` | sequence start | tight / loose | 0.8 s | smoothstep per slip | no | skip jumps to end | yes, via Replay | any key or tap skips | not run | 1 draw call plus the shadow pass |
| The band and the collection | the check reads and files every record | block.js `introAt` | 0.8 s | top / bottom of the block | 1.4 s | smoothstep | no | with skip | yes | same | band only | per-instance colour |
| Counts roll | the facts arrive with the collection | home.js, GSAP | 1.0 s | 0 / final | 1.1 s | power2 out | no | skip lands them | yes | same | shown final | none |
| Settle | resolution | block.js | 2.2 s | 94% / 100% scale, 12° / 0° | 0.4 s | smoothstep | no | with skip | yes | | not run | none |
| Field colour | chapter edges | CSS on `html[data-pal]` | chapter change | red / paper | 600 ms | travel | yes | n/a | cut on Replay | n/a | instant | background-color on two elements |
| Block operation | the project's method | block.js targets lerped | scroll inside the panel (12% to 67%) | BLOCK / SLICE, LAYER, BEND, OPEN | per panel | smoothstep on u, frame lerp | yes | n/a | always | n/a | holds end states | 1 draw call |
| Tests lighting | 31 tests pass | block.js `layer(tests)` | scroll 30% to 90% of panel 2 | 0 / 31 lit | | linear | yes | | | | end state | per-instance colour |
| Block stage | where the block sits | block.js group target | chapter | per chapter and viewport | lerp | frame lerp | yes | n/a | always | n/a | instant | none |
| Pointer tilt / drag | exploration | block.js | pointer | ±6° / drag angle | continuous | lerp | yes | n/a | always | fine pointers only | off | none |
| Panel words rise | hierarchy on arrival | CSS `.is-in` | panel 20% in view | 18 px below / 0 | 700 ms, stagger 60 ms | entrance | class toggles off | n/a | each arrival | n/a | none | transform, opacity |
| Fragment loop | the real interface at work | home.js | fragment 20% in view | u 0 / 0.92 | 6 s once, then holds | the scene's | no | pauses offscreen | on each arrival | n/a | final frame | one 2D canvas while visible |
| Hour cut | a visible consequence | block.js from the input | input | previous / chosen hour | lerp | frame lerp | yes | last value wins | always | native range | instant | per-instance colour |
| Title and cover into the case study | continuity | cross-document View Transitions (`title`, `cover`) | click | panel title and fragment / case heading and cover | 560 ms | travel | Back reverses | native | always | native links | none | compositor |
| Button press | feedback | CSS | hover, focus, active | 0 / -2 px | 160 ms | entrance | yes | n/a | always | focus-visible ring | colour only | none |

Rests: Experience (the block small, upper right, still) and Contact (the block resting, the e-mail as the statement).

Owners: GSAP owns `intro.k` and the counts only; block.js owns every instance matrix and colour, the shadow and the
group's transform; CSS owns every DOM transform and colour; home.js toggles classes, sets custom properties and feeds
block.js. No property has two owners.
