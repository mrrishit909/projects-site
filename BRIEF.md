# Portfolio brief (2026-10-24, fourth direction: THE TOWER)

Everything before this is history: no printed objects, no desk, no paper, no boarding pass, no colour fields, no dots.
This file is the spec; the research behind it is in `~/projects-site-evidence/tower-2026-10-24/RESEARCH.md` (the Awwwards
crawl and the 690 Webflow templates) and `~/projects-site-evidence/index-2026-10-24/RESEARCH.md` (the earlier passes).

## Positioning
Rishit Raj Mathur, data analyst, Tampa. The claim the site makes in one line: **Every number, checked against its source.**
Below it, the facts: 224 case studies, 219 public repositories. Audience: recruiters, hiring managers and technical reviewers
for data and business analyst roles. The first screen must show, in under five seconds, the size of the body of work and
that it is real. Desired actions: open a flagship case study, query the index, download the résumé, contact.

## The one idea
**The work is the world.** Every one of the 224 case studies is one screen in a tower of screens standing in a dark hall on
a reflecting floor. The visitor does not read about the work; they stand in front of it and fly through it.
- The opening is the tower assembling: the screens fly in from the dark in order while a counter runs 000 to 224. The
  statement rises almost at once; the count and the assembly continue behind it. Skip, wheel, key or touch ends it. A repeat
  visit plays it at 0.45x; a hash, reduced motion, or coming back from a case study skips it.
- Scroll is a camera flight, not a page: the hero stands before the tower; at each of the four flagships, that project's own
  screen leaves the tower and comes to a stage in front of the camera (real cover, real number); the about section looks down
  into the tower from above; the index unwraps the tower into a flat wall of all 224 with a reflection; the contact pulls far
  back across the floor.
- The HUD is thin instrumentation: name and role, three nav items, Tampa time, the counts, the last push. Mono for data,
  Bricolage for words. The page copy sits bottom-left so the object owns the frame.
- The index is a real query over the inventory (`language:`, `kind:`, `year:`, `commits>`, `live:yes`, free words), with
  Covers and Table views. Every case study carries a facts strip from its repository (commits, last push, created, languages,
  live site, topics, licence).

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
