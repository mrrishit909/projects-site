# ATELIER X: Creative Direction (PROPOSED, 2026-11-03)

Status: PROPOSED. The final pick belongs to the owner. Nothing here is approved until he says so. Written against seven rejected homes (dashboard, editorial, desk, dot field, cylinder carousel, flat fields, prism) and the "still generic, insufficiently cinematic" verdict on Precision Atelier. The brief that every concept answers: one rendered world carried through the page, every section a camera move, loud colour that changes per chapter, one line of huge type per screen, live screens, and real-time motion on modest hardware.

Shared constraints (all five): skippable intro, no fake loading, no autoplay audio (sound is opt-in behind one button), native scroll (ScrollTrigger scrubs the camera, it never hijacks the wheel), no blur on type, no particle soup, reduced-motion static poster, mobile is its own composition, Lighthouse 90+ / 95+ a11y, LCP <= 2.5 s via a poster image that is the first frame, CLS <= 0.1 via reserved canvas boxes, GitHub Pages, free only. Facts on screens come only from the project records (BTS on-time arrivals, 31 dbt tests, ETS + SARIMA backtests, the 10-K refusal); no invented metrics.

---

## 1. Precision Atelier Reimagined: "THE FOUNDRY"

Central idea. The old Atelier showed a finished brass instrument sitting on ivory, which read as a product shot. The reimagining keeps the owner-selected materials but changes the subject from the object to the making of it: the page is a foundry floor at night. Molten champagne metal is poured, hammered, machined and finally engraved into a plate for each flagship project. The reason it is this owner's work and not decoration: every project on the site is something he built from raw public data (BTS flights, SEC filings, retail transactions), and the foundry makes that literal: raw material in, instrument out. The camera never leaves the floor; each chapter is a different station on it. The brass is no longer the hero; the light is (one hot pour light, one cold work light, sparks that are a handful of emissive streaks, not particles).

Palette and colour behaviour. Floor #071d16 (racing green, kept), hot pour #ff7a1a and white-hot #ffe9c2 (new, the only saturated accents, used as light not fill), brass #c4ab7d, ivory #f0ebe1 for the plates and all reading text, soot #0a0a0a for the archive. Colour changes per chapter by changing the light, not the background: pour (orange floods the green), machining (cold cyan #9fd8e6 work light), engraving (neutral ivory), rest (green with a single brass highlight). The CSS ground tracks the light temperature with a `data-station` attribute.

Typography. Display: Bricolage Grotesque (already vendored, condensed, 800 weight, uppercase, 9 to 14 vw). Reading: Geist (vendored). Figures: JetBrains Mono (vendored). Fallbacks: Impact-free stack, `"Bricolage Grotesque", "Arial Narrow", sans-serif`; `Geist, system-ui`; `"JetBrains Mono", ui-monospace`.

Hero and chapters as camera moves.
- Hero: the camera is low on the floor, looking up at a crucible tilting. One line: "I POUR RAW DATA INTO INSTRUMENTS." The pour starts on scroll, not on load.
- Chapter 1 (Florida flight delays): dolly along a cooling bar that is also a 24-hour bar chart of on-time arrival rates; the owner's number is engraved as the bar cools.
- Chapter 2 (dbt + DuckDB pipeline): crane shot straight down over four machining stations in a row (the four dbt layers), 31 test pins drop into drilled holes; the camera counts them as it passes.
- Chapter 3 (retail forecast): orbit around a lathe turning a long curve, the real monthly series, then the forecast fan is cut as a chamfer at the end.
- Chapter 4 (Ask the 10-K): push in on the engraving plate; the stylus stops mid-line when the source does not support the claim: the refusal, shown as an unfinished engraving.
- Rest: pull back to the whole floor, every plate hung on the wall, which is the work index.

Project discovery. The wall of plates at the end is the index: a real HTML list (one row per project, kind, year, tools) rendered over the 3D wall; the search box filters rows and dims the matching plates in the scene. The archive page (`all.html`) stays the editorial index.

Mobile composition. Portrait, no floor: a single vertical pour. The crucible is a 2D canvas sprite sheet (16 frames, 120 KB), chapters are full-bleed colour-light panels with the plate as a static WebP and one 2D animated figure each (the bar chart cooling, pins dropping, the curve, the engraving). Type at 13 vw. Nothing in Three.js on phones.

Reduced motion. One poster of the floor at rest with all four plates lit (WebP, 1440 and 390 variants), instant chapters as static panels, index visible immediately.

Technical approach. CSS: grounds, type, panels, the index. GSAP + ScrollTrigger: one timeline per station scrubbing camera position and light intensity, plus the engraving stroke. Three.js: one scene, 6 meshes (crucible, bar, four plates), MeshStandardMaterial with a 256 px roughness texture, 2 lights, no shadows (baked AO on the floor plane texture, 180 KB). Sparks: 24 instanced quads, one draw call. Budget: Three subset 150 KB gz, GSAP 70 KB, textures 420 KB, fonts 110 KB, poster 90 KB; 11 draw calls desktop.

Risks. Fire and metal can read as "forge website" cliche if the light is overdone; mitigation is restraint (one hot light). The pour itself is a shader (a stretched capsule with a flow map), easy to get wrong on low GPUs. The owner already saw brass once; if the reimagining still reads as "the instrument with sparks" it fails. Prototype the pour first.

---

## 2. Monolithic Interface: "THE SLAB"

Central idea. One black granite slab the size of a building, standing in a flat field of colour. Every project is cut into it as a window; the windows are live. It is this owner's work because he ships many (220 repositories) and the slab is the only form that makes volume feel monumental instead of cluttered: a monolith with lit apertures reads as a single built thing, not a grid of cards. The camera moves around and into the slab; the slab never moves. Light is the drama: one raking sun that turns across the page.

Palette and colour behaviour. Slab #0b0b0d with a mica flake normal map. Field colour changes hard per chapter and is the only colour on screen: cadmium #ffd400, signal red #ff2e1f, cobalt #1733ff, acid #c8ff00, and white #f4f4f0 for the index. Text is always #0b0b0d or #f4f4f0. The field is a CSS background on `html[data-field]` with a 400 ms crossfade; the Three.js scene has a transparent clear colour so the slab always sits on the CSS field (one trick, big payoff, no second render).

Typography. Display: Archivo Black or Big Shoulders Display (both OFL, self-hostable) at 16 to 22 vw, uppercase, tracking -0.03em; one word per screen. Reading: Inter Tight (OFL). Figures: IBM Plex Mono (OFL). Fallbacks: `"Archivo Black", "Arial Black", sans-serif`; `"Inter Tight", system-ui`; `"IBM Plex Mono", ui-monospace`.

Hero and chapters as camera moves.
- Hero: a worm's-eye shot from the foot of the slab on a cadmium field; the sun is behind it and the edge burns. One word: "BUILT." Scroll tilts the camera up the face.
- Chapter 1 (Florida flights): crane up the face to the first aperture; inside, the hourly on-time bar chart is drawn live on a canvas texture; the field turns red.
- Chapter 2 (dbt pipeline): the camera passes through the aperture into the slab's interior, a corridor of four chambers; the field is not visible, the interior is lit by the 31 test lights on the walls.
- Chapter 3 (retail forecast): exit through the far side onto cobalt; the slab's shadow on the field is the forecast curve (a projected texture).
- Chapter 4 (Ask the 10-K): low tracking shot along the base where the text of a filing is engraved; one line is lit, the next is not: the refusal.
- Index: the camera lands square-on, orthographic; the apertures become the work index grid.

Project discovery. The index is the square-on face: an HTML grid overlaying the apertures, one cell per project, with kind tabs and a search field; selection lights the matching aperture in the scene. Keyboard navigation on the grid is native (it is a list of links).

Mobile composition. The slab becomes a single tall column in portrait with the camera looking straight up; chapters are the apertures scrolling past, each a full-width live canvas; the field colour changes under it. Three.js is kept on phones but at one mesh, one light, half pixel ratio; fallback to a WebP tower if WebGL is unavailable or the frame budget is missed in the first second.

Reduced motion. Poster of the slab square-on on the cadmium field; chapters are static field panels with the aperture content as pre-rendered WebP; the index is immediate.

Technical approach. CSS: fields, type, the index grid, the crossfades. GSAP + ScrollTrigger: a single camera path (CatmullRom) scrubbed by scroll with pinned chapter labels; the sun angle is a second scrubbed value. Three.js: 1 slab mesh with a 1k normal map (200 KB), 4 aperture planes with CanvasTexture (drawn by the existing `motion/scenes/<slug>.js` functions, which already paint project-faithful figures), 1 directional light, 1 shadow-casting pass only on desktop. Draw calls: 7. Budget: Three subset 150 KB, GSAP 70 KB, textures 260 KB, fonts 120 KB, poster 70 KB.

Risks. Black slab plus big type is close to the brutalist-poster trend; the live apertures and the pass-through interior are what make it not that. Hard colour fields may be judged "flat colour + big type" if the slab is small on mobile. Shadow projection of the curve is the single risky shader.

---

## 3. The Living System: "GROUND TRUTH"

Central idea. The page is a terrain generated from the owner's own data: a heightfield whose rows are months and columns are the 24 hours of the day, built from the real flight on-time series, under a sky whose colour is the retail sales index. Nothing is a stock landscape; the ground is literally the data he analysed, and it changes as the visitor explores (hovering a ridge raises that hour, the chapters re-source the heightfield from a different project's table). It is his work because the subject of every project is a table, and this is the only concept where the table is the world. Live, procedural, responsive.

Palette and colour behaviour. Ground vertex colour by height from #1b4332 (low) to #d8f3dc (high) for flights; for retail #7b2cbf to #ffd166; for the 10-K chapter the terrain goes monochrome #e9ecef with one lit column. Sky is a CSS gradient on the page body that changes per chapter (dawn #ffb4a2, noon #a9def9, dusk #6d597a, night #0b132b). Text is #0b132b on light skies and #f8f9fa on dark.

Typography. Display: Space Grotesk 700 (OFL) at 10 to 14 vw with a wide tracked small-caps caption in Space Mono (OFL) carrying the data source line under each heading. Reading: Source Sans 3 (OFL). Fallbacks: `"Space Grotesk", "Helvetica Neue", sans-serif`; `"Space Mono", ui-monospace`; `"Source Sans 3", system-ui`.

Hero and chapters as camera moves.
- Hero: a flyover at dawn, nap-of-the-earth, over the Florida terrain; one line: "THE GROUND IS THE DATA." A small live caption names the source and the window.
- Chapter 1 (Florida flights): the camera climbs to a 45 degree survey angle; the 24 hour columns are labelled; the worst hour is a visible valley.
- Chapter 2 (dbt pipeline): the terrain is cut into four strata (staging, intermediate, marts, tests) and the camera sinks through them like a core sample; 31 test markers are flags on the top layer.
- Chapter 3 (retail forecast): the terrain re-sources to the monthly retail series as a single ridge line; the camera tracks along it to the edge where the backtest fan opens as a translucent wedge.
- Chapter 4 (Ask the 10-K): night; the terrain is a grid of filing pages; the camera looks straight down, one page lights where the answer is grounded and the query that has no support shows an empty, unlit plot: the refusal.
- Index: dawn again, high orbit; every project is a surveyed plot with a flag; the HTML index sits beside it.

Project discovery. The index is a survey table: a sortable HTML table (kind, year, tools, status) with search; hovering a row lights the flag on the terrain. On touch the table is primary and the terrain is a header.

Mobile composition. Portrait: the terrain is rendered as a 2D contour map on canvas (same heightfield, isolines drawn live, cheap), scrolled vertically as a long map strip; chapters are map insets with the same re-sourcing. Headlines at 12 vw.

Reduced motion. Poster of the terrain at the survey angle; chapters are static contour panels; the index table is immediate.

Technical approach. CSS: sky, type, table. GSAP + ScrollTrigger: camera path and heightfield morph (a uniform `mix` between two height textures, 0 to 1 per chapter). Three.js: 1 PlaneGeometry 128 x 128 (32k triangles), one custom ShaderMaterial (vertex displacement from two 128 x 128 R16 DataTextures, colour ramp in fragment), 1 light, flags as 1 InstancedMesh. Draw calls: 4. Budget: Three subset 140 KB, GSAP 70 KB, data JSON 30 KB, fonts 100 KB, poster 80 KB. The heightfield is computed in JS from `florida-flight-delays/preview/data.json` and the retail series at load, so the page is truthful by construction.

Risks. Procedural terrain is a known genre (every shader demo has one) and the owner rejected a dot field as generic; this survives only if the data labelling is loud and specific and the colour is bold. The core-sample move needs a clipping plane, which is fine in Three.js but can confuse mobile GPUs. Two height textures per chapter transition means the morph must be prepared ahead of the chapter.

---

## 4. Cinematic Editorial: "REEL"

Central idea. The homepage is a projection booth: a single beam of light across a dark room lands on a screen, and each chapter is a cut in a film about the work. Type is the actor: headlines enter as title cards with film-grade timing (hold, cut, wipe), never as fades. It is this owner's work because his projects are narratives with evidence (CASCADIA is literally an energy-grid narrative; the 10-K project is a story about refusing to answer), and a cinema is the one form where a chapter is expected to be a scene. There is no 3D object; the world is the light cone, the dust in it, the screen, and the room edges.

Palette and colour behaviour. Room #0e0e10. Beam #fff4d6. Each chapter is a different film stock: the screen washes in saturated single colours with a visible grain texture (not a blur): Kodachrome red #d7263d, Fuji green #1b998b, Ektachrome blue #2e5bff, tungsten amber #f4a300. Type is #fffdf7 and, for the refusal, #0e0e10 on a white leader frame.

Typography. Display: a tight condensed sans with film-title authority, League Gothic or Anton (both OFL), 14 to 20 vw, with a secondary italic in Instrument Serif (OFL) for one-line subtitles. Reading: Instrument Sans (OFL). Figures: JetBrains Mono (vendored). Fallbacks: `Anton, "Arial Narrow", sans-serif`; `"Instrument Serif", Georgia, serif`; `"Instrument Sans", system-ui`.

Hero and chapters as camera moves.
- Hero: the beam snaps on (hard cut from black, no fade) and the camera is inside the beam looking at the screen; the title card "RISHIT MATHUR, A FILM ABOUT BUILDING THINGS WITH DATA" holds for 1.2 s then cuts.
- Chapter 1 (Florida flights): a slow push into the screen while the on-time hourly chart is drawn on it live as a continuous line (a "data wipe"); the room turns red.
- Chapter 2 (dbt pipeline): a 4-panel split screen (one per layer) that the camera pans across; 31 test counters tick on screen.
- Chapter 3 (retail forecast): the projector itself is in frame; the camera racks focus from the lens to the screen where the series and its forecast fan are drawn.
- Chapter 4 (Ask the 10-K): the film runs out: a white leader frame, the words "NOT SUPPORTED BY THE FILING" in black, hard cut. That is the refusal.
- Index: house lights up: the room is revealed as a lobby with poster frames, which is the work index.

Project discovery. The lobby is an HTML poster wall with real `cover.jpg` posters at full resolution (no upscaling, the posters are rendered at 2x), search and kind filters above; this is the only concept where thumbnails are allowed, because posters are the diegetic object.

Mobile composition. Portrait: the screen is the whole viewport; chapters are full-bleed title cards with the live line drawings on 2D canvas; no beam or room geometry; cuts use View Transitions between chapter sections.

Reduced motion. Poster of the lit screen with the title card; chapters are static cards; no cuts, only scroll; the lobby index is immediate.

Technical approach. CSS: almost everything (room, beam as a clipped gradient plus a grain SVG turbulence at 0.08 opacity, type, title cards, split screens). GSAP + ScrollTrigger: the cut timings, the data wipes (stroke-dashoffset on SVG paths generated from real data at build time by `build.py`), the rack focus (a CSS filter on a wrapper, never on text). Three.js: none. Draw calls: 0 WebGL. Budget: GSAP 70 KB, fonts 130 KB, grain SVG 2 KB, posters 2x WebP about 40 KB each, lazy. This is the cheapest and most accessible concept.

Risks. Without 3D it may feel below the owner's references (every one of them renders a world). Film grain on type violates the no-blur rule if applied wrongly; it must be a separate layer. Title-card motion is a known trend; the data wipes and the leader-frame refusal are the distinguishing moves.

---

## 5. Experimental Digital Observatory: "THE ARRAY"

Central idea. A radio-telescope array at the edge of a salt flat at blue hour. Each dish is pointed at one project, and what it "hears" is drawn as a live trace on the page. The visitor navigates spatially by turning the array (drag or scroll) and the chapters are the dishes tilting one after another toward the camera. It is this owner's work because his projects are instruments for listening to systems (flights, markets, filings, a paper-trading account, drift detection: DriftSentinel is literally a listener), and an observatory is the honest metaphor for an analyst. Constellations appear only as the project graph in the index, drawn as lines between dishes on the ground, never as a starfield.

Palette and colour behaviour. Salt flat #e9e4d8, sky from #ff9f1c (horizon) to #2b2d42 (zenith), dish white #f7f7f2, trace #ff2e63 for the active project. Colour behaves by time of day: the hero is blue hour, chapters move through night (sky to #0b0b1a, traces turn phosphor #39ff14), and the index returns to dawn. The CSS sky and the Three.js fog share one colour variable.

Typography. Display: Unbounded 800 (OFL), 10 to 13 vw, uppercase, with slightly extended width; it reads technical without being a monospace joke. Reading: Public Sans (OFL, US government typeface, fitting for BTS and SEC data). Figures: Martian Mono (OFL). Fallbacks: `Unbounded, "Arial Black", sans-serif`; `"Public Sans", system-ui`; `"Martian Mono", ui-monospace`.

Hero and chapters as camera moves.
- Hero: drone shot sliding sideways past the array at dish height; one line: "I LISTEN TO SYSTEMS AND WRITE DOWN WHAT THEY SAY." The nearest dish begins to tilt toward the camera on scroll.
- Chapter 1 (Florida flights): the camera settles on the first dish; its trace is the 24 hour on-time curve, drawn live; the night falls.
- Chapter 2 (dbt pipeline): the camera rides the cable trench between dishes; 31 junction boxes light in order as tests pass.
- Chapter 3 (retail forecast): the camera rises above the second dish and the trace extends off the dish into the sky as the forecast fan.
- Chapter 4 (Ask the 10-K): one dish is pointed at nothing; its trace is flat; the caption reads the refusal. Silence as a visual.
- Index: the camera climbs to a plan view; dishes become points, lines between shared tools form the constellation; the HTML index sits beside the map.

Project discovery. Plan view plus table: a sortable HTML table with search and kind filters; hovering a row highlights that dish and its links; selecting a tool filter dims unrelated dishes. The graph edges come from shared `tools` fields in `project.json`.

Mobile composition. Portrait: the array as a side-scrolling horizon strip at the top (2D canvas silhouette), the traces as full-width live canvases per chapter beneath; the plan view becomes a static SVG map above the table.

Reduced motion. Poster of the array at blue hour; chapters are static trace panels; the plan view is a static SVG; table immediate.

Technical approach. CSS: sky, type, table. GSAP + ScrollTrigger: camera path and dish tilt per chapter, the trace draw. Three.js: 1 dish mesh instanced 12 times (1 draw call), a ground plane with a 512 px salt texture (120 KB), fog, 1 light; traces are 2D canvases positioned with CSS (cheaper and crisper than textures). Draw calls: 4. Budget: Three subset 140 KB, GSAP 70 KB, textures 140 KB, fonts 120 KB, poster 80 KB.

Risks. Telescope and space imagery drifts toward sci-fi cliche; the salt flat and daylight palette are what keep it earthbound. Twelve identical dishes could read as a repeated-card wall in plan view; the constellation lines must carry real meaning (shared tools) or they become decorative.

---

## 6. Comparison matrix (1 = weak, 5 = strong)

| Criterion | 1 Foundry | 2 Slab | 3 Ground Truth | 4 Reel | 5 Array |
|---|---|---|---|---|---|
| Originality | 3 | 4 | 4 | 3 | 4 |
| Professional credibility | 4 | 5 | 4 | 4 | 4 |
| Visual impact | 4 | 5 | 4 | 3 | 4 |
| Intro quality | 4 | 5 | 3 | 4 | 4 |
| Project discoverability | 3 | 5 | 4 | 4 | 4 |
| Mobile feasibility | 3 | 4 | 4 | 5 | 3 |
| Accessibility | 4 | 4 | 4 | 5 | 4 |
| Performance | 3 | 4 | 4 | 5 | 4 |
| Maintainability | 3 | 4 | 3 | 5 | 3 |
| Distinction from common AI-generated sites | 3 | 4 | 4 | 3 | 4 |
| Fit with the owner's stated taste | 3 | 5 | 3 | 2 | 4 |
| Total | 37 | 49 | 41 | 43 | 42 |

Justification per row.
- Originality: the foundry and the cinema are recognisable genres, the slab, the data terrain and the array are rarer as portfolio worlds.
- Professional credibility: the slab reads as institutional and serious; the foundry and the cinema risk theme-park tone if overcooked.
- Visual impact: hard single-colour fields with one black monolith is the strongest first frame at Retina scale; the cinema has no object.
- Intro quality: the slab's edge-burn on a cadmium field is a one-shot image; the terrain's flyover needs data loaded before it means anything.
- Project discoverability: the slab's square-on face is the index itself; the foundry's plate wall is a step removed from a list.
- Mobile feasibility: the cinema is CSS and 2D; the foundry and the array both need a second, 2D design for phones.
- Accessibility: all five keep a real HTML index and text; the cinema has the fewest canvases to describe.
- Performance: zero WebGL for the cinema; the foundry carries the heaviest shader (the pour) and the most textures.
- Maintainability: the slab and the cinema reuse the existing `motion/scenes` canvases unchanged; the terrain and the array add custom shaders and data pipelines.
- Distinction from AI-generated sites: AI sites default to gradients, cards and glass; a black slab on cadmium, a data terrain and a salt-flat array do not resemble that output; a foundry with sparks and a cinema with title cards sit closer to template territory.
- Fit with the owner's taste: he asked for one 3D world, hard saturated fields, huge type, one line per screen and camera moves; the slab is the literal answer; the cinema has no rendered world and the foundry repeats materials he has already judged.

## 7. Decision report (PROPOSED)

Recommendation: Concept 2, THE SLAB, with one borrowed element from Concept 3: the aperture contents are not static canvases but the live data drawings that already exist in `motion/scenes/<slug>.js`, so every window on the monolith is a real figure from the project. Call the hybrid "THE SLAB (live apertures)".

Why. It is the only concept that satisfies all six of the owner's reference traits at once (one rendered object, scroll chapters as camera moves, hard colour fields per section, monumental type, one line per screen, live screens) while staying inside the directive's performance envelope (7 draw calls, one normal map, CSS fields instead of a second render). It is also the furthest from everything he has rejected: no dashboard, no cream editorial, no cards, no dot field, no carousel, no glass, no brass. Its weakest row is mobile, and the fallback (a single tall column, half pixel ratio, WebP tower if the first-second frame budget is missed) is defined up front.

What to prototype first, in this order, each as a standalone page under `motion/` with the existing evidence harness:
1. The hero frame: slab on a cadmium CSS field with a transparent WebGL clear colour, worm's-eye camera, sun behind the edge. Prove: the first paint is the poster and the canvas replaces it with no layout shift; LCP under 2.5 s on a throttled 4x CPU profile; the edge burn reads at 1440 x 900 Retina as a photograph of light, not a glow filter.
2. The pass-through: camera entering an aperture into the lit corridor and exiting onto a different field colour. Prove: no visible seam at the aperture plane, 60 fps desktop on integrated graphics, 30 fps on a mid-range phone, and that the field crossfade does not fight the scene.
3. One live aperture: the Florida hourly chart drawn by the existing scene function onto a CanvasTexture. Prove: text in the aperture is crisp at device pixel ratio 2, and texture upload per frame stays under 1 ms.

Alternate if the owner rejects the slab: Concept 5, THE ARRAY, which shares the camera-path architecture and the HTML index, so the prototypes transfer.

Explicit statement: this whole document is PROPOSED. The owner chooses. He has rejected seven directions on first visual impression and may reject all five of these; the prototypes exist so that his decision is made on a real rendered frame, not on this text.

## 8. Rejection checklist

| Directive rejection criterion | How the five concepts avoid it |
|---|---|
| Generic AI dashboard | No concept has panels, KPIs or sidebars; data appears only as one drawn figure inside the world (plate, aperture, terrain, screen, trace). |
| Repeated glass cards | No cards anywhere; the index is a typographic HTML list or table in all five, and the cinema's posters are full-resolution originals, not cards. |
| Gratuitous gradients | Fields are flat single colours (slab), or gradients that are a sky with a stated time of day (terrain, array); no gradient is used as surface decoration. |
| Centred hero template | Hero cameras are low-angle, side-tracking or flyover; the one line of type is set off-centre against the object, never a centred headline over a subtitle and two buttons. |
| Random particles | Banned outright; the foundry's sparks are 24 instanced streaks tied to the pour, the array has none, the cinema's dust is a static grain layer. |
| Decorative charts | Every figure is the project's real series (hourly on-time arrivals, 31 tests, the monthly retail series and its backtest fan, the refusal) and is captioned with its source. |
| Weak typography | Display faces are specific, heavy and condensed or extended (Bricolage, Archivo Black / Big Shoulders, Space Grotesk, Anton, Unbounded), one line per screen at 10 to 22 vw, no blur, no outline-only text. |
| Broken mobile | Each concept specifies its own portrait composition and a WebGL-free path; mobile is verified by screenshots at 390 x 844, not by reflow. |
| Preset-looking motion | All motion is a camera move scrubbed by scroll or a data drawing; no fade-up-on-scroll, no stagger-in cards, no parallax layers. |
| Visual noise | One object, one light, one line of type, one colour per screen is the rule in all five. |
| Copied layouts | None of the five reproduces a reference site's layout; the shared traits (world, chapters, fields, type) are principles, and the subjects (foundry, slab, data terrain, cinema, array) are the owner's own metaphors. |
