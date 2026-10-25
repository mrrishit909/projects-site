# Portfolio brief (2026-10-25, sixth direction: THE BLOCK)

Everything before this is history: no printed objects, no desk, no colour fields with objects, no dots field, no cylinder
tower, no hall of screens. The owner's rules for this pass: LOUD COLOUR, ONE DOMINANT 3D OBJECT, HUGE TYPE, LITTLE TEXT,
NO BLUR, NO THUMBNAILS. The references: riseof.digital, kprverse.com, persepolis.getty.edu, en.manayerbamate.com, lusion.co
(principles only). The method: `design/art-direction.md` (thesis, candidates, tokens), `design/storyboard.md` (the
entrance's five states, the chapters, the motion score), `design/SOURCES.md` (the source and skill ledger),
`docs/REVIEW.md` (the review pass), `docs/EVIDENCE.md` (the requirements matrix), `docs/PERFORMANCE.md`.

## Positioning
Rishit Raj Mathur, data analyst, Tampa. The line under the name: data analyst in Tampa, every number on this site was
checked against its source. The facts: 224 case studies, 219 public repositories (read from the data at build time).
Audience: recruiters, hiring managers and technical reviewers for data and business analyst roles. Desired actions: open
a flagship case study, search the archive, download the résumé, write.

## The one idea
**The body of work is one block of record slips, and each project machines it.** 1,440 thin slips stand as one solid on
a loud red field with the name above it. Scrolling into each flagship performs that project's method on the block:
the flight-delay star schema cuts it (SLICE), the dbt pipeline delaminates it into strata and lights 31 tests (LAYER),
the forecast bends it into a monthly series with a fanned range (BEND), the 10-K retrieval opens it and lifts the cited
slip (OPEN). The check chapter cuts the block at the published on-time rate for a departure hour the visitor picks (HOUR).
The archive spreads it into a sheet with 224 lit (SHEET). Contact rests it. The field alternates red and grey paper by
chapter and the block inverts with it.

The entrance: the HTML first frame (name, line, card with the counts and two actions, the poster of the block), then the
slips fly in, a plane of light sweeps through them once (the check) and the two counts roll; wheel, touch, key or the
Skip button ends it; it plays once per session and never under reduced motion.

## Art direction
- Colour: paper #e4e4e4 and #d6d6d6; red #cf2419 (the field, the block on paper, the one filled button); oxblood #7d0c14
  text on paper; #f0f0f0 text and block on red. Nothing else.
- Type: General Sans (Fontshare, ITF Free Font License) for everything; Archivo vendored as the fallback; Geist only
  inside the projects' own interface fragments. Steps: --xl, --lg, --lead, --body 16px, --small 14px.
- The object: Three.js r170, one InstancedMesh, Lambert, no post pass, transparent canvas; pixel ratio 1 rising to 1.5
  with headroom; the poster (`assets/block-poster.webp`, rendered by `tools/poster.cjs`) stands in before WebGL and
  without it.
- Motion: one owner per property (block.js the instances, CSS the DOM, GSAP the opening only); native scroll, no Lenis,
  no ScrollTrigger; entrances cubic-bezier(0.16, 1, 0.3, 1), travel cubic-bezier(0.65, 0, 0.35, 1).
- Banned: gradients, glass, blur, thumbnails, cards as structure, eyebrows, numbering, monospace outside the fragments,
  custom cursors, autoplay sound, em dashes, claims not in the résumé or a repository.

## Gate
Real screenshots at 1440x900, 768 or 1024 wide, 390x844 and 844x390, reduced motion, no JavaScript, no WebGL, read by a
person; frame pacing on a stated machine; the suite green; Lighthouse measured; the owner's visual approval before
anything is published.
