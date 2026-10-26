# The refined journey: diagnosis, shot list, storyboard (2026-10-26)

Scope of this pass: the representative journey (opening, hero, first project, its case page, return), proven before
anything else is propagated. The other chapters and the ivory sections are planned here and held for the owner's
acceptance. Evidence: `~/projects-site-evidence/atelier-2026-10-25/refine/` (`before/` is commit f11ce90, `after/` the
candidate; the same script, tests/evidence/journey-frames.cjs, produced both).

## 1. Diagnosis (each concern verified in a WebGL browser before editing)

| Concern | Verified | Where | Ledger |
|---|---|---|---|
| The instrument is thin bars, widely separated | yes | before/d-hero.png: the rail and cap float a full object-height above the core; pins stand far out; nothing is a chassis | D-12 |
| Text left, object right every time | yes | eleven consecutive screens share the composition and the object's scale and angle | D-13 |
| Labels, rules, counts, controls as noise | yes | chapter 1 carries fourteen elements; chapters 2 to 4 carry counters and stage notes | D-14 |
| The camera never changes scale or emphasis | yes | stage s 0.72 to 1.0 everywhere, ry about -0.5 everywhere | D-13, D-15 |
| Scenes explain but lack an event | yes | the hour input changes two numbers; the object does not respond | D-16 |
| Entering a case study is not entering the same world | partly | the title travels, the ground stays green, but the object arrives small and re-assembles | D-17 |
| The lower page loses identity | yes | about and archive: a corner thumbnail and empty ivory | D-18 (held) |

Highest impact, in order: D-12 (every frame shows the object), D-15 (the first ten seconds), D-13 and D-14 (the
rhythm), D-16 (the first event), D-17.

## 2. The instrument (the hierarchy)

Five assemblies, each with a purpose and its own exploded behaviour:

1. **Head** (primary chassis, top): a thick brass head block with the tick scale on its face, a lacquer cap bar over
   it, and the top door frame. The heaviest member; it lifts as one assembly and leads the explode.
2. **Core** (the mechanism): the engraved brass plate with the four words; in front of its lower third the **dial**, a
   brass drum with a tick ring and an index needle, set between two brass cheeks; the inner frame; two lacquer back
   plates. The dial is the recognisable mechanism: it turns in the opening and to the departure hour in chapter 1.
3. **Side panels**: the green and the ivory marble slabs, thick (0.6), with their brass brackets. They open outward.
4. **Connectors**: four brass pins with caps, close to the brackets; four small screws at the plate's corners (the fine
   detail seen in the close-up).
5. **Base**: a deep lacquer plinth, the slotted brass base bar, two feet pads. It drops as one assembly and follows the head.

Exploded composition: the head rises most (tension at the top), the base drops half as far, the sides open a little,
the core stays compact with small depth steps, the connectors stay near their seats. Nothing is evenly spaced.
Materials: brass roughness 0.5 to 0.58 with the brushed map (no mirror), lacquer clearcoat 0.6, marble clearcoat 0.4;
bevels 0.045 with 4 segments so edges catch the key light; the key light from upper left, a cool rim from behind right,
the contact shadow on the ground plane at full quality.

## 3. The opening: shot list (implemented at 3.0 s on the GSAP clock; Skip on wheel, touch, key or the button; Replay restarts)

| # | t (s) | Framing | Focal subject | Camera | Object | Typography | Into the next shot | Skip / reduced motion |
|---|---|---|---|---|---|---|---|---|
| 1 | 0.0 to 0.7 | close-up, the object fills the right two thirds, cut at the frame | the dial between its cheeks, the plate's words above it | still, three-quarter from the left (ry -0.95, rx 0.05, scale 2.3) | assembled except the core stack, which stands 0.7 ahead of its seat; the dial turned 2.4 rad off its index | brand, nav, kicker and BUILT WITH INTENT are on the first frame (the poster shows the same crop) | the dial starts to turn at 0.5 | Skip: everything to the end state; reduced motion: this shot is omitted |
| 2 | 0.5 to 1.3 | same | the dial's index | still | the dial turns to its index (power3.out, a 6% overshoot settled by 1.3); as it aligns, the core stack slides home (0.9 to 1.3, power4.in) and the click | | the seating is the cause of shot 3 | |
| 3 | 1.3 to 2.3 | the object pulls away from the camera | the head block | pull back and turn: scale 2.3 to 1.0, ry -0.95 to -0.5, rx 0.05 to 0.16, x 0.62 to 0.71 (power2.inOut 1.1 s) | the seating pushes the head up (1.3 to 2.0), the base drops after it (1.5 to 2.2), the sides open (1.7 to 2.4), the core steps apart last (1.9 to 2.5): one unlocking, propagated | the lead rises at 1.6, the buttons at 1.9, the domains and the corner lines at 2.1 | the object settles into the hero's exploded register | reduced motion: assembled to exploded in 0.6 s with no camera move |
| 4 | 2.5 to 3.0 | the hero | the whole register | settles (the lerp) | restrained settling | the words are settled; nothing competes | html.entered; Replay appears | |
| 5 | scroll | the orient and chapter 1 | | the same object, handed on by scroll | | | | |

Interruption: Skip sets k, u and cam to 1 and enters. Leaving mid-opening counts as seen (Back never replays).
Pause stops the GSAP clock and the renderer. The first frame before WebGL is the poster of shot 1's crop, so the
page never shows the hero composition and then jumps to the close-up.

## 4. Storyboard: the journey as consecutive frames

| Frame | Section | Composition | Camera / object | Type | Purpose |
|---|---|---|---|---|---|
| A | opening shot 1 | close-up right, type left | scale 2.3, dial | name and statement | identity in the first frame, a mechanism to look at |
| B | opening shot 3 | pull back | 2.3 to 1.0 | lead, actions | the unlocking |
| C | hero settled | split: statement left, exploded register right | 1.0, ry -0.5 | statement, lead, two actions, domains, three facts | the concept frame |
| D | Selected work | close-up: the head block's tick scale fills the lower right, the list of four over negative space on the left | scale 1.9, y 0.78, ry -0.3 | FOUR SYSTEMS and the list | a scale change that shows the fine detail; the list is the navigation |
| E | chapter 1 development | full-width title across the top, the object wide beneath it, forming | scale 1.05, x 0.56, y 0.6, ry -0.22 | FLORIDA FLIGHT DELAYS at full width | a wide establishing view: the schema forms under the title |
| F | chapter 1 settled | the title holds; the figure, the hour control and two actions sit bottom-left, the evidence fragment bottom-right; the four marks over the object | the schema with the dial at the chosen hour | the figure, one control line | the event: the hour turns the dial and lights the Time dimension |
| G | case hero | title left (travels from F), the object right already formed at F's scale, the marks shared with F | scale 0.95 | title, tagline, summary | the same world: same ground, same arrangement, same marks |
| H | case reading | ivory | the object leaves at the handoff | the cover, facts, sections | reading |
| I | Back | frame F restored | | focus on View project | reliable return |

Held for acceptance (planned, not built): chapter 2 as a split with the pipeline running across the full width and
the tests as pins attaching to the frames; chapter 3 with the chart large (the evidence as the picture) and the object
small as a time axis; chapter 4 as a close-up on the lifted passage; the instrument chapter with assembly selection;
about with the engraved plate as a close-up ground; archive with the register lying flat; contact unchanged.

## 5. Interaction plan (the journey)

| Where | Interaction | Consequence | Phone | Keyboard |
|---|---|---|---|---|
| hero | pointer tilt (fine pointers) | the register turns a few degrees | none (scroll only) | none |
| chapter 1 | the hour input | the dial turns to the hour; the Time dimension and its connector light by that hour's lateness; the figure line updates | native range | arrow keys on the range |
| chapter 1 | View project | the title and the marks travel; the case hero holds the schema | same | Enter |
| case | Back | scroll and focus restored to View project | same | same |

## 6. Status (2026-10-26)

Implemented and verified in emulation: frames A to I (refine/after, the same script as refine/before), the recordings
`recordings/refine/journey-desktop.webm` and `journey-phone.webm` with their contact sheets, the suite (113 checks).
Owner acceptance of this journey: PENDING. Nothing from sections 4 (held rows) or 5 beyond chapter 1 has been built.
Known: on phones the close-up in Selected work crosses the words briefly while the section scrolls (D-11 class);
after Back the hour input returns to 8 a.m. (the chapter's state is not restored, only scroll and focus).
