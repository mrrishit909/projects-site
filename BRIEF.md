# Portfolio brief (2026-10-24, fifth direction: THE HALL)

Everything before this is history: no printed objects, no desk, no paper, no boarding pass, no colour fields, no dots, no
cylinder tower. The owner's references for this pass: riseof.digital (a building you walk through, one room per service,
an elevator between), kprverse.com (huge type, bordered frames, chapters), persepolis.getty.edu (a scroll-driven film with
an Enter gate, a sound choice, one line of copy per scene, no gaps).
This file is the spec; the research behind it is in `~/projects-site-evidence/tower-2026-10-24/RESEARCH.md` (the Awwwards
crawl and the 690 Webflow templates) and `~/projects-site-evidence/index-2026-10-24/RESEARCH.md` (the earlier passes).

## Positioning
Rishit Raj Mathur, data analyst, Tampa. The claim the site makes in one line: **Every number, checked against its source.**
Below it, the facts: 224 case studies, 219 public repositories. Audience: recruiters, hiring managers and technical reviewers
for data and business analyst roles. The first screen must show, in under five seconds, the size of the body of work and
that it is real. Desired actions: open a flagship case study, query the index, download the résumé, contact.

## The one idea
**The work is a hall you walk down, and the walk is a film.** Every one of the 224 case studies is a screen on the hall's
walls; the four showcased projects are rooms where their own dashboard plays live on the wall.
- The gate: a ring fills as the 224 screens load (real bytes), then "Enter with sound" or "Enter in silence". Nothing
  else on screen. This is the first frame.
- The flight: 4.6 s from above the hall down to eye level, the screens coming on ahead of the camera, grain and
  aberration settling, the statement rising as the camera lands. Wheel, touch or key skips it.
- The walk: scroll scrubs the camera (GSAP ScrollTrigger over Lenis). Between rooms a title card asks the project's
  question in one line, letters rising; in the room the camera turns to the wall where the project's screen hangs,
  drawn live from its motion scene with a CRT pass; the number counts up, the word and copy rise. Four rooms, alternating
  walls. Then Method (three beats under a sweeping light), About, the end wall (every wall screen leaves the wall and
  assembles into one grid; point at any screen to see its name, click to open it), and Contact with the lights going down.
- Sound is a choice: a low bed, a riser for the flight, a ping per chapter. Off by default; the choice is remembered.
- The HUD: name and role, three nav items, the live strip, a chapter counter with the chapter's name, a cursor ring.

## Art direction
- Colour: **ink #07070C**, **white #FFFFFF**, one hot accent **#FF4D00** for the first meta word, underlines and the one
  filled button. Dim white at 62% for secondary data. Nothing else; the screens carry all the colour.
- Type: **Bricolage Grotesque** (variable) for words, display at wdth 75, wght 800; **JetBrains Mono** for data. Self-hosted.
- The world: Three.js r170, two instanced meshes (one per 4096 px atlas), a custom shader (frame, back-face dimming,
  scan-line, fog), a mirror copy under a floor with a grid and a glow, dust, and one post pass (grain, vignette, chromatic
  aberration that grows with scroll speed). Adaptive DPR; a still of each flagship's cover is shown without WebGL.
- Motion: one easing for entrances `cubic-bezier(0.16, 1, 0.3, 1)`, one for travel `cubic-bezier(0.65, 0, 0.35, 1)`; the
  world eases with a frame-rate-independent lerp; nothing animates layout. Reduced motion: no opening, poses only.
- Banned: cards, gradients, glass, device mock-ups, marquees, stock photography, the six-section template, custom cursors,
  autoplay sound, em dashes, "leverage/seamless/unlock" copy, claims not in the résumé.

## Gate
Real screenshots at 1440x900, 768x1024 and 390x844 of every scene, read by a person; recordings of the opening and the
flight; zero console errors; 60 fps pacing on desktop; the suite green; Lighthouse measured, not invented; the owner's
visual approval before anything is published.
