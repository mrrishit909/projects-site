# The instrument: asset contract

The instrument is procedural (no Blender model, no GLB, no downloaded texture or environment). Source: `instrument.js`.
Editable lab: `motion/instrument-lab.html` (query string sets state, next, u, arg, intro k, ry, rx, stage sx/sy/ss,
`ground=ivory`, `poster=1`). Posters: `NODE_PATH=$(npm root -g) node tools/poster.cjs` against the local server.
Three.js r170 is tree-shaken into `vendor/three/three.module.min.js` from the entry in docs/BUILD-THREE.md (124 KB gzip).

## Modelling-path decision (technical spike, 2026-10-25)

Three paths were weighed: a Blender-authored segmented GLB with baked materials, procedural geometry, a hybrid.
Procedural won after the spike in the lab (evidence `~/projects-site-evidence/atelier-2026-10-25/spike2/`): the parts
are prisms and cylinders whose craftsmanship lives in bevels (RoundedBoxGeometry), proportions, clearances and
materials, all reachable procedurally at 41 draw calls and 17k triangles; a GLB would add a loader, a decoder and a
download for no silhouette the procedure cannot reach. Blender remains available if a future part needs organic form.
Textures are drawn on canvases at start-up (value-noise fbm marble, brushed roughness, the engraving) in about 120 ms
on an M3 Pro; this is the only start-up cost beyond the shader compile.

## Parts (32, each one mesh, individually addressable by name)

| Name | Family | Size (w h d) | Material | Role in the arrangements |
|---|---|---|---|---|
| rail | rail | 3.6 0.3 0.55 | rail (ticks) | top bar; base of the star; a source bar; the drawer back |
| cap | rail | 3.0 0.12 0.42 | brass | under the rail; the drawer's front lip |
| frameTopF/B/L/R | frame | 3.3 0.1 0.08 (F/B), 0.08 0.1 1.0 (L/R) | brass | the upper frame; the staging frame; forecast bars; index cards |
| plate | core | 1.7 2.3 0.14 | plate (engraved) | the fact table; the marts output; an observed month; an index card |
| innerT/B/L/R | inner | 1.9 0.07 0.07 / 0.07 2.45 0.07 | brass | the frame around the plate; the source frame; forecast bars |
| backA, backB | core | 1.7 2.3 0.08 | lacquer | two dimensions; staging plates; observed months; index cards |
| marbleL | slab | 0.55 2.3 0.9 | green marble | a dimension; an intermediate table; the last observed month; a card |
| marbleR | slab | 0.55 2.3 0.9 | ivory marble | a dimension; an intermediate table; the forecast's last horizon; the selected passage |
| bracketL/R | bracket | 0.09 2.5 0.09 | brass | side brackets; the marts frame; the now line; the refusal's crossed bars |
| pinFL/FR/BL/BR | pin | r 0.035, h 2.7 (+2 caps) | brass | the four pins; the star's connectors; the pipeline's rails; the timeline axis |
| shelf | lower | 3.0 0.06 0.8 | lacquer | a thin shelf; an intermediate layer; an observed month; a card |
| lower | lower | 3.2 0.46 0.95 | lacquer | the lacquer base block; an intermediate layer; an observed month; a card |
| frameLowF/B/L/R | frame | as frameTop | brass | the lower frame; the intermediate frame; forecast bars; index cards |
| slotL, slotR | rail | 1.3 0.12 0.45 | slot (a dark slot) | the slotted bars; source bars; the drawer sides |
| pad, foot | pad | 0.9 0.08 0.6 / 0.6 0.06 0.4 | brass | small pads; the marts' tables |
| base | rail | 2.8 0.22 0.6 | slot | the base bar; the star's top rail; the drawer's bottom |
| tests[0..30] | test pin | r 0.03, h 0.42 + head | pin (own material, glows) | the 31 dbt tests, visible only in the pipeline |

Pivot: every mesh's local origin is its geometric centre; the pins' caps are children at ±h/2. The group `group`
carries stage position, scale and rotation (rx, ry); the ground (ShadowMaterial plane) sits at `pose.ground` under it.
Transform limits: ry is free (drag and keys add to a per-chapter base), rx is held at 0.16 ± tilt 0.08, scale 0.3 to 1.
Reset: the system chapter's Reset view zeroes the spin; chapters set their own ry each frame so navigation always
arrives at a defined orientation.

## Materials (MeshPhysicalMaterial under an authored PMREM environment)

- brass / pin / rail / slot / plate: metalness 1, roughness 0.46 to 0.5 with a brushed roughness map (512 px canvas,
  horizontal streaks, repeat 2), anisotropy 0.5 to 0.6; rail and slot carry a tick/slot colour map; the plate carries the
  engraving (768x1024 canvas; the four words set in Bricolage Grotesque condensed 800 at 96 px, ink at 80% alpha, a
  tick column and two rules). Base colour 0xcbb084 in linear space (the UI token #C4AB7D is not this value).
- lacquer: 0x0b3328, roughness 0.34, clearcoat 0.7 / 0.14.
- green marble: fbm veins over 0.04/0.16/0.11 with 0.6/0.66/0.58 veins (sharpness 16), roughness 0.22, clearcoat 0.5.
- ivory marble: 0.92/0.88/0.8 with 0.58/0.53/0.47 veins (sharpness 11), roughness 0.26, clearcoat 0.45.
- Environment: a 20x14x20 room, walls 0x3d5047, a warm 7x9 key panel left, a warm 12x8 panel behind the camera (so
  faces toward the visitor read champagne), a cool fill right, a skylight, a green floor glow; PMREM sigma 0.04.
- Lights: key DirectionalLight 0xfff0d8 at 2.2 with a 1024 px PCF soft shadow (full quality only), rim 0xcfe6dc 0.8,
  ambient 0x2a4a3c 0.5. ACES Filmic tone mapping, exposure 1.1, sRGB output. Transparent canvas (alpha, premultiplied).
- Tone (emissive) per material: plate 0.8, test pins 1.0, lacquer 0.5, marble 0.5/0.6; plain brass never glows.

## States (STATES in instrument.js; each writes position, euler, scale and tone for all 63 meshes)

closed, open, network(), pipeline(n tests), timeline(), documents(u: 0..1 select, 1..2 refuse), rest. States are
cached per (name, arg at 2 decimals); the frame loop lerps `now` toward `tgt` with a time-based rate
(1 - 0.004^dt, 1 - 0.00005^dt during the opening), so any interruption is continuous. A blend between two states is
`pose.state` to `pose.next` at `pose.u` with a small per-mesh stagger.

## The opening (introK 0..1, written in `arrive`)

Families arrive along their own axes (rails from above, frames from behind, the core from the front, slabs from the
sides, brackets from below, pins from the depth, the lower block from the left, pads from the lower right) in a
lead/follow order (rail 0.00, core 0.12, slab 0.22, lower 0.30, frame 0.42, inner 0.48, bracket 0.52, pin 0.60, pad
0.66; each over 0.34 of k) with a residual yaw/roll that unwinds as they land; the group's ry unwinds 1.2 rad over
k 0..0.8. home.js drives k with GSAP (power2.inOut, 2.0 s), then blends closed to open (0.9 s). Reduced motion:
`introStill` skips the trajectories and the sequence is 0.8 + 0.6 s with no travel.

## Costs (measured in the lab, Apple M3 Pro, Chromium via ANGLE Metal, 1440x900)

41 draw calls (81 in the pipeline with the 31 test pins), 17,202 triangles, 7 materials, 6 canvas textures (1 MB GPU
memory), one 1024 px shadow map, 1 active shadow light. Pixel ratio starts at 1 and rises to 1.75 (full) or 1.5 (lite)
only after 90 fast frames, steps down after 40 slow ones, with 8 s and 20 s locks (hysteresis).

## Disposal

`dispose()` releases geometries, materials, canvas textures, the environment texture and the renderer. The case pages
create their own instrument on their own canvas (quality lite, no shadows) after the load event.
