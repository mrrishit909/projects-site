# The instrument: object contract (rebuilt 2026-10-26)

`instrument.js` draws one object, the register, on a transparent canvas; the page's CSS ground is its ground. The design
reasoning is in design/journey.md (section 2); the lab at motion/instrument-lab.html renders any state, blend, intro
value or camera from the query string (`?state=closed&next=open&u=0.5&lead=1&ry=-0.5&rx=0.16&ss=1&sx=0.5&sy=0.5`,
`poster=1` for clean exports); tests/evidence/lab-views.cjs renders the comparison set.

## Assemblies and parts (41 parts, 31 test pins)

| Assembly | Parts | Material | Purpose | Explode |
|---|---|---|---|---|
| Head (primary chassis) | rail (the head block, 3.4 x 0.44 x 0.92, the tick scale on its faces), cap, lip, frameTopF/B/L/R | brass with the scale map, lacquer, brass | the heaviest member; what the close-up in Selected work shows | rises 1.1 to 1.4, leads the explode |
| Core (the mechanism) | plate (engraved with the four words), backA, backB, innerT/B/L/R, dial (a drum 0.28 x 1.1 with the hour ring, axis x, spin on the pitch), cheekL/R, needle, screwTL/TR/BL/BR | brass, lacquer, the dial map | the recognisable mechanism; the dial turns in the opening and to the departure hour in chapter 1; the screws are the fine detail of the close-up | steps apart by 0.3 to 0.78 in depth, last |
| Sides | marbleL (green), marbleR (ivory), bracketL/R | marble with clearcoat, brass | the two panels that open | open 0.52 outward, the brackets 0.82 |
| Connectors | pinFL/FR/BL/BR with caps | brass (the `pin` material, so they light as one) | join the panels to the core; the schema's relationships | 0.64 to 0.72 outward, close to their seats |
| Base | shelf, lower (the plinth 3.3 x 0.5 x 1.0), frameLowF/B/L/R, base (slotted), slotL/R, pad, foot | brass, lacquer, the slot map | the foundation | drops 0.42 to 1.68, follows the head |

Geometry: RoundedBoxGeometry with 4 segments and a 0.045 bevel so edges catch the key light; cylinders for the pins
(18 sides), the dial (56) and the screws (16). Materials: MeshPhysicalMaterial; brass metalness 1, roughness 0.48 to
0.56 with the brushed roughness map and anisotropy (never a mirror); lacquer clearcoat 0.6; marble clearcoat 0.35 to
0.4. Light: the PMREM room (warm key panel left, the champagne face panel behind the camera, cool fill right, skylight,
the green floor glow), a shadow-casting key from upper left (full quality only), a cool rim from behind right, a low
ambient. Draw calls: 50 assembled or exploded, 36 in the network, at DPR 1.

## States

| State | Arguments | What it is |
|---|---|---|
| closed | | assembled |
| open | | the hero: each assembly at its authored exploded offset |
| network | hour (5 to 23), late (0 to 1) | the star schema: the core assembled as the fact block with the dial at the hour; the four panels (green slab, ivory slab, the two lacquer plates) at the corners turned toward the centre; the connectors from the block's corners to the panels; the head beam, the base beam and the brackets as the frame. `late` lights the ivory Time panel, steps it forward and thickens its connector |
| pipeline | n (0 to 31) | four standing frames on two rails; n test pins seated |
| timeline | | the observed columns and the fanning forecast bars |
| documents | u (0 to 2) | the card index; u 0..1 lifts the passage, 1..2 closes the drawer (the refusal) |
| rest | | closed |

Blends: `pose.next` with `u` blends state to state per part; with `pose.lead` the blend propagates by assembly
(LEAD: head 0, frame 0.08, base 0.2, sides 0.36, connectors 0.42, core 0.52, dial 0.58, screws 0.62) over the first
half of u, otherwise by a small per-assembly stagger. The opening: `introD` (0..1) turns the dial from 2.4 rad off its
index to the index; `introK` (0..1) seats the front core stack (plate, inner frame, dial, cheeks, needle, screws) from
0.7 ahead of its seat; `startOut` begins there. The camera (stage x, y, s; ry, rx) is owned by the page and lerped
here; the first frame starts on its stage. Tone (slot 9) drives the emissive intensity per material.

## Update contract

`update(t, pose)` once per frame from the page's single loop; `pose = { state, arg, arg2, next, nextArg, nextArg2, u,
lead, introK, introD, introStill, stage: {x, y, s}, ry, rx, tilt, spin, ground, force }`. Rendering stops when every
lerp has settled unless `force`. `paused` stops everything. Context loss removes `html.gl-on` (the poster or the still
shows) and restoration re-adds it. `dispose()` frees geometries, materials, textures, the environment and the renderer.
