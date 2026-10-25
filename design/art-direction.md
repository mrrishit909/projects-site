# Art direction: THE BLOCK (2026-10-25)

The sixth direction for the home of mrrishit909.github.io/projects/. It replaces THE HALL (an architectural hall of 224
thumbnail screens, which the owner's current rules forbid: no thumbnail wall, one dominant object, loud colour).

## Visual thesis

What visitors see: one solid block made of 1,400 thin slips, the body of work as a physical stack of records, standing
on a loud red field with the name in huge type above it. What it means: the analyst's material is rows from public
sources, and the work is what happens to the stack. What they do: scroll, and the block is cut, layered, bent and opened
by each flagship project; set a departure hour and watch the block sort into on-time and late; open a case study. What
changes: the ground alternates red field and grey paper by chapter, the block inverts (paper on red, red on paper) and
performs a different operation per project. How it leads into real projects: each operation is the project's own method
(a star schema is a cut; dbt is layers and tests; a backtest bends a series; retrieval opens the stack to a cited page),
with the real figure, its source and a live fragment of the real interface beside it, and a button into the case study.

With animation paused the first frame is a red poster: a huge name, a white block of records, a small paper card with
four facts and two actions.

## Three candidates compared

| | A. THE BLOCK (chosen) | B. THE INSTRUMENT | C. THE LEDGER PAGE |
|---|---|---|---|
| Object | one block of 1,400 record slips that is machined per project | one bespoke measuring instrument (a balance: claim on one pan, source on the other) | one huge sheet of ruled paper the numbers are written on, folded per chapter |
| Connection to the work | records transformed, the literal material of data engineering | the check against a source, the site's claim | the written-down number |
| First-frame impact | solid monument, loud field, huge name | a single mechanical object, elegant but familiar (justice, jewellery) | typographic, flat |
| Still-frame quality | strong silhouette, lit faces | good | weak without motion |
| Legibility | type stays off the object | pans and beams compete with type | good |
| Interaction | sort by hour, drag to turn, cut and open per chapter | place a number on a pan | turn a page |
| Mobile | block in the top 40svh, copy below | the beam needs width | fine |
| Assets | none; primitives in code | none | none |
| Performance | one InstancedMesh, one draw call, Lambert, no post pass | low | lowest |
| Risk | reads as a bar chart if the transforms are timid | reads as a stock "scales" icon; the owner rejected printed objects before | reads as a document, not a statement piece |

A wins on connection, first frame and interaction. The risk is answered by treating the block as one solid that is
cut, delaminated, bent and opened (machining moves on one object), never scattered into a particle field (THE INDEX was
rejected for that), and by the loud two-colour field.

## The direction dealt by the taste skill

`design-taste-frontend` dealt three directions (name-as-monument, type-only-statement, pinned-poster); `pinned-poster`
was chosen because its device (one element holds while the series passes under it) is the only one that can carry one
persistent object. Full sheet: `.taste-skill/direction.json` (seed 1110276553). Redraws: none. Adaptations, each with
its reason:

- The pinned element is the block and the name, not a title over photographs (the brief pins one 3D object).
- Hero blueprint "Card over a dim room": kept the flat panel with facts, one action and one link that shrinks to a stub
  bottom-left on scroll; the "photograph of the room" is the block on the red field; the three title words become the
  name at display size (the brief pins huge type).
- Work blueprint "Title torn at the seam": kept the split stage (text left, picture right), one project per 150svh,
  the two-word section heading top-left; dropped the clip-path tear because the block is the right pane.
- "Pinned title, portraits pass" (about) became the experience chapter as a line-up (the list blueprint), since there are
  no portraits; the archive takes the list blueprint as dealt.
- Contact "The email as display type": as dealt, on the inverse colours, as a curtain under the page.
- Palette "Oxblood and grey": dealt proportions kept (grey paper holds the reading chapters; a solid red field takes the
  hero, the check and the footer). The red is pushed from oxblood #7d0c14 to a signal red #d7261e for the fields and the
  block because the owner's rule is loud colour; oxblood stays as the text ink on paper. The brief wins over the deal.
- Type "General Sans": as dealt, from Fontshare (ITF Free Font License), with Archivo (vendored) as the fallback.
- Photographs: the dealt sky set is not used; the real pictures on the page are the four live interface fragments drawn
  by the projects' own scenes (software shows its own interface) and the block itself.

The impeccable concept seed (`seed:f1db7f229cc74ef4`, mode experience) assigned grounded candidate 7 and dealt six
challengers. The brief-pinned direction beats the roll; the challengers were weighed and three donated a discipline:
oscilloscope (everything measured against the graticule): every figure carries its min-max range and its evidence;
azulejo (recompose by whole tiles): the block only ever moves whole slips, never fractional shapes; suminagashi basin
(the surface answers the pointer at 60 fps): the block answers drag and pointer tilt every frame. Declined on both axes:
multiplane dawn, Ray Gun layout desk, village coffeehouse (none can carry an analyst's truth).

## Tokens

```
--paper: #e4e4e4   ground of the reading chapters
--paper-2: #d6d6d6 a step for panels on paper
--red: #d7261e     the field, the block on paper, the one filled button
--red-2: #b81d16   pressed state, block shadow faces on paper
--ink: #7d0c14     text on paper (contrast 9.3:1), small lines
--on-red: #f3efe9  text and the block on the red field (5.4:1 at body size)
type: General Sans 700 for display (tracking -0.02em, leading 0.9), 400/500 for text (leading 1.45)
steps: --xl clamp(64px, 11vw, 190px) the name and the figures; --lg clamp(36px, 5.6vw, 96px) section lines;
       --lead clamp(20px, 1.5vw, 26px); --body 17px; --small 14px
motion: entrance cubic-bezier(0.16, 1, 0.3, 1); travel cubic-bezier(0.65, 0, 0.35, 1); block lerp 1 - 0.004^dt
radius: 0 everywhere (the block has square slips; the page has square corners)
depth: none in CSS (no shadows, no hairlines); depth is the block's lighting
```

## What is refused

Gradients, glass, blur of any kind, thumbnails, cards as structure, eyebrows, numbering, monospace outside figures,
custom cursor, autoplay sound, em dashes, claims not in the résumé or a repository.
