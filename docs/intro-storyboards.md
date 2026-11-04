# ATELIER X: Intro Storyboards (PROPOSED, 2026-11-03)

Status: PROPOSED. Every intro is skippable at any moment (Skip button visible from t=0, Escape, Enter, Space, any scroll or wheel, any tap), has no fake loading screen (the intro starts only when the scene is ready; before that the poster is simply the page), no autoplay audio (a Sound button appears after the intro), and a static poster for reduced motion. The final pick belongs to the owner. Shared rules: total 2.5 to 4 s; the LCP element is always the poster `<img>` (WebP, 1440 and 390 variants, `fetchpriority=high`, preloaded), the canvas is inserted behind it in a reserved box and the poster is removed on the first rendered frame (CLS 0); WebGL context loss restores to the poster and re-inits once, then stays on the poster; frame budget 16.7 ms desktop, 33 ms mobile, measured by the evidence harness; fonts preloaded (display face only, the rest swap); Three.js and GSAP deferred `type=module`, data JSON inline.

## Intro A: THE SLAB LIGHTS UP (Concept 2, recommended)

- Opening frame: cadmium #ffd400 field, the slab black and unlit from the foot, the word BUILT already set in Archivo Black at 18 vw along the bottom edge (HTML text, so it is readable before any script). LCP: the poster image of this exact frame.
- Main visual subject: the monolith's edge catching a sun that rises behind it.
- Environment: flat cadmium field, no horizon line, no sky; the field is CSS.
- Camera (3.2 s total): 0.0 to 1.6 s a slow tilt up the face from the foot (ease out), 1.6 to 2.6 s the sun clears the top edge and the rim light runs down the face, 2.6 to 3.2 s the first aperture lights with the live Florida chart, camera settles at hero position.
- Typography choreography: BUILT is static; at 2.6 s the kerning tightens by 0.02 em (no blur) and the one-line subtitle "by Rishit Mathur, data and ML engineer" is typeset under it in Inter Tight; nothing fades, text is either set or not.
- Transition into the homepage: the camera position at 3.2 s is scroll position 0; the slab, the field and the word persist; the Skip button becomes the Sound button; the first scroll begins the tilt toward aperture one. Nav (Work, Archive, Contact) is typeset at 3.0 s top right and stays.
- Interaction: Skip or Escape or Enter or Space or any scroll jumps to 3.2 s state instantly; pointer position shifts the sun by 2 degrees (subtle parallax of light, not of object); keyboard focus order starts at Skip then nav.
- Mobile: portrait column version, the camera looks straight up the column, the word at 22 vw broken over two lines ("BUI/LT" is not allowed; set "BUILT" at a size that fits one line, minimum 16 vw); same timing, half pixel ratio, one light.
- Reduced motion: poster of the final frame plus nav immediately; no camera move; apertures static WebP.
- Performance: preload poster, display font, Three subset (150 KB) and GSAP (70 KB); defer normal map (200 KB, the slab renders flat-shaded until it arrives, which is invisible at t<1.0 s because it is unlit); context loss as shared rule; 7 draw calls.

| t (s) | Frame |
|---|---|
| 0.0 | Poster: cadmium field, black slab foot, BUILT along the bottom, Skip top right. |
| 0.4 | Canvas live behind the poster, poster removed, tilt begins, no visible change. |
| 0.9 | Camera a third up the face; the top edge still black against cadmium. |
| 1.6 | Tilt reaches the top; a white-hot line appears at the edge. |
| 2.4 | Rim light runs down the face; mica flakes catch it; the field stays flat. |
| 3.0 | First aperture lights with the hourly on-time chart; nav typesets; subtitle typesets. |
| end 3.2 | Hero rest: scroll position 0, Sound button replaces Skip. |

## Intro B: THE FOUNDRY POUR (Concept 1)

- Opening frame: racing green #071d16 floor, the crucible as a black silhouette against a faint orange glow at its lip, headline "I POUR RAW DATA INTO INSTRUMENTS." set in Bricolage at 10 vw in ivory. LCP: the poster of this frame.
- Main visual subject: one pour of molten champagne metal into a plate mould.
- Environment: foundry floor at night, baked AO on the floor plane, one hot light, one cold work light.
- Camera (3.6 s): 0.0 to 1.2 s low static shot while the crucible tilts, 1.2 to 2.6 s the pour (shader capsule with flow map) and the camera dollies right to follow the metal into the mould, 2.6 to 3.6 s the metal cools from white-hot to brass and the camera pulls back to the hero position.
- Typography choreography: the headline is set at t=0; at 2.6 s the final word INSTRUMENTS. takes the brass colour as the metal cools (a colour change, not an animation of position).
- Transition: the cooled plate is the Florida plate; scroll continues the pull-back along the floor; nav typesets at 3.2 s.
- Interaction: as shared; pointer tilts the crucible by 1 degree before the pour starts.
- Mobile: 2D sprite-sheet pour (16 frames, 120 KB), portrait, same timing, no Three.js.
- Reduced motion: poster of the cooled plate on the floor, nav immediate.
- Performance: the pour shader is the only risky part; capped at 1.4 s, falls back to an emissive scale animation if the shader compile exceeds 200 ms; textures 420 KB deferred behind the poster; 11 draw calls.

| t (s) | Frame |
|---|---|
| 0.0 | Poster: dark floor, crucible silhouette, orange lip, headline, Skip. |
| 0.4 | Canvas live; the lip glow brightens; crucible begins to tilt. |
| 0.9 | Crucible at 20 degrees; the first drop of light touches the mould. |
| 1.6 | Full pour; orange floods the green floor; camera dollies right. |
| 2.4 | Mould filling; sparks as 24 streaks. |
| 3.0 | Metal cooling to brass; INSTRUMENTS. turns brass; nav typesets. |
| end 3.6 | Plate cooled; camera at hero rest; Sound button. |

## Intro C: GROUND TRUTH FLYOVER (Concept 3, also usable for Concept 5)

- Opening frame: dawn sky gradient on the body (#ffb4a2 to #a9def9), the terrain as a flat dark silhouette at the bottom third, headline "THE GROUND IS THE DATA." in Space Grotesk at 12 vw, the source caption in Space Mono under it. LCP: the poster.
- Main visual subject: the Florida on-time heightfield rising from flat to its true heights.
- Environment: open ground under a dawn sky; no horizon objects.
- Camera (2.8 s): 0.0 to 1.0 s static at ground level while the heightfield rises (uniform mix 0 to 1), 1.0 to 2.8 s a nap-of-the-earth flyover that lifts to the 45 degree survey angle.
- Typography choreography: headline set at t=0; at 1.0 s the caption gains the data window text; at 2.4 s the 24 hour labels typeset along the far edge.
- Transition: the survey angle is scroll position 0; scroll continues the climb; nav typesets at 2.4 s.
- Interaction: as shared; pointer over the terrain raises the hour column under it by 5 percent.
- Mobile: 2D contour map drawn live, isolines appearing in order of height over 2.8 s; portrait.
- Reduced motion: poster of the survey angle; table immediate.
- Performance: heightfield computed from the inline JSON (30 KB) before the first frame; one 128 x 128 plane, one shader; 4 draw calls; the cheapest WebGL intro of the three.

| t (s) | Frame |
|---|---|
| 0.0 | Poster: dawn sky, flat dark ground, headline, caption, Skip. |
| 0.4 | Canvas live; heights begin to rise. |
| 0.9 | Heightfield at full height; the worst hour is a visible valley. |
| 1.6 | Flyover at ridge height; colour ramp visible. |
| 2.4 | Camera lifting; hour labels typeset; nav typesets. |
| 3.0 | (ended at 2.8) |
| end 2.8 | Survey angle; scroll position 0; Sound button. |

## Prototype plan (PROPOSED)

Build two short interactive prototypes first, as standalone pages under `motion/` run through the existing evidence harness (`tests/evidence/`):

1. Intro A, THE SLAB LIGHTS UP. Must prove in a real browser: poster to canvas handoff with CLS 0 and LCP under 2.5 s on throttled 4x CPU; the edge burn reads as light at 1440 x 900 at device pixel ratio 2 (screenshot judged by a person); 60 fps on integrated graphics and 30 fps on a mid-range phone with the normal map deferred; Skip, Escape, scroll and tap all land on the identical hero state; context loss restores to the poster; the live aperture text is crisp.
2. Intro C, GROUND TRUTH FLYOVER. Must prove: the heightfield built from the real JSON is legible as a 24 hour by month table at a glance (the owner should be able to point at the worst hour); the rise and flyover hold frame budget on a phone; the 2D contour fallback is visually acceptable rather than a downgrade; and whether a data terrain reads as specific or as "another shader demo" at Retina scale, which decides whether Concept 3 survives at all.

Intro B is deferred because its single risk (the pour shader) is the most expensive to prove and the owner has already judged brass once; it is built only if he picks Concept 1.
