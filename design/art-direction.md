# Art direction: Precision Atelier (2026-10-25)

Owner-selected direction; the concept image is the target: `~/projects-site-evidence/atelier-2026-10-25/refs/precision-atelier-concept.png`.
Supersedes THE BLOCK (loud red, record slips) and every earlier home. Directive: Precision_Atelier_Claude_Code_Master_Build_Prompt.md.

## The idea in one sentence

An exquisitely engineered instrument, a register of brass, lacquer and marble, assembles on arrival and is taken apart
by each flagship project into the structure of that project's work: a star schema, a pipeline, a forecast, a document
index. The site is the atelier the instrument sits in.

## Tokens

| Role | Value | Where |
|---|---|---|
| deep ground | #071D16 | the home's scene, case-page heroes, the top bar on case pages |
| racing green | #0B3025 | reserved (panels, future) |
| secondary green | #174C38 | reserved |
| ivory | #F0EBE1 | the reading ground (About, Archive, Contact, case bodies, the archive) |
| ivory 2 | #E6E0D3 | cards on ivory (notes) |
| champagne | #C4AB7D | accent on green: rules, outlines, the filled button, the dot, focus rings |
| champagne 2 | #7A6436 | accent on ivory (4.65:1 on ivory; the directive's #C4AB7D fails 4.5:1 as text on ivory, so it stays a mark there) |
| muted on green | #B8C7BA | secondary text on green (9.1:1) |
| ink | #142E24 | text on ivory (14:1) |
| muted on ivory | #4F5F56 | secondary text on ivory (5.5:1) |

The renderer's materials are not these tokens (docs/INSTRUMENT.md); the canvas is transparent so there is no scene
background to mismatch the CSS ground; the shadow plane darkens whichever ground is under it.

## Type

- Display: Bricolage Grotesque, variable, width 75% (condensed), weight 800, uppercase, line-height 0.86. Chosen for
  the concept's heavy condensed grotesk; self-hosted (OFL, 131 KB). Hero clamp(66px, 11.6vw, 188px); chapter titles
  clamp(46px, 7.4vw, 128px); figures 700 at 80% width.
- Reading: Geist 400/500 (OFL, vendored). Body 17px/1.55; lead clamp(18px, 1.45vw, 23px); small 14px; labels 13px
  uppercase with 0.08em tracking (moderate, never tiny).
- Figures and data: JetBrains Mono (OFL, vendored).
- Fontshare (General Sans) dependency removed: no third-party request on first view.

## Layout, grid, borders, focus, icons

12-column feel as a 5.4 / 6.6 split on desktop (text left, the instrument's room right); one pair of gutters
clamp(20px, 5vw, 72px); 1 px rules in champagne at 38% on green, ink at 22% on ivory; square corners; focus is a 2 px
champagne outline offset 4 px; icons are typographic (arrows, a triangle play glyph, four bars for sound, a pause
glyph), no icon font.

## Motion tokens

--ease cubic-bezier(.16, 1, .3, 1) for entrances; --travel cubic-bezier(.65, 0, .35, 1) for the ground colour; durations
240 / 480 / 900 ms. The instrument lerps per frame with time-based rates (docs/INSTRUMENT.md). Reduced motion removes
entrances, the opening's travel and the ground transition.

## The two grounds and the handoff

Green from the hero through the four chapters and the system chapter (spatial continuity: one object, one scene).
A cut ivory edge (clip-path wedge) hands off to the reading ground at About; the ground colour of the document
follows at the handoff so the instrument stays in the same world (it rests, assembled, on ivory at About, Archive and
Contact). No alternation beyond this single handoff.

## What the taste draw said, and the conflict

`draw.mjs --sector personal-portfolio --tone luxury --options 3` dealt "dark-room" (one dark field, lit exhibits) and
"name-as-monument" (the name at 16 to 24 vw). The owner's selected concept puts a statement ("Built with intent.") left
and the object right, not the name as the monument. Conflict recorded; the selection stands. Taken from dark-room: one
continuous deep ground with the object as the brightest thing on each screen.

## Compositions (verified by screenshots in ~/projects-site-evidence/atelier-2026-10-25/r*/)

- Desktop 1440x900: hero split, the instrument at 71% / 52% of the viewport at scale 1; chapters pinned 100svh with the
  object at 69% / 46% (0.72 to 0.88 scale by arrangement) under four marks; the evidence fragment bottom right.
- Tablet 768x1024: the same split at 1 / 0.7.
- Phone 390x844: the instrument in the top 30 to 44 svh at 0.42 to 0.55 scale, the words below; it leaves at the handoff (no room beside the words on ivory); the four marks as one
  row of four small labels; the evidence fragment hidden (the case study carries it); the brand and controls on one row,
  the nav on the next.
- Protected text area: the left column at every state; the object never enters it on desktop (stage x >= 0.66, the
  pipeline and timeline at reduced scale), and sits above the text on the phone.
