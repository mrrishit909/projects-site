# Source and skill ledger (2026-10-25)

Status: READ (whole), PARTIAL (named sections), UNAVAILABLE, NOT APPLICABLE. Text was extracted with pdftotext 25.x
into the session scratchpad; page counts from mdls. "Affects" names where a finding changed this build.

## Supplied documents

| Source | Pages | Status | Sections read | Actionable findings | Affects | Limits |
|---|---|---|---|---|---|---|
| Claude_Code_Cinematic_Portfolio_Master_Prompt.md | 16 sections | READ | all | the brief for this build; mandatory corrections in section 15 | everything | none |
| Rishit_Website_Building_Master_Playbook.pdf | 25 | READ | all 23 chapters (as page images) | authority order; intro as a sequence with a carried element; composition first; animation contract per effect; 1.5 MB first view as a provisional target; exact status labels | design/storyboard.md, docs/EVIDENCE.md | the playbook states no live site was audited for it |
| 3D Website Animation Toolkit | 32 | READ | all | choose the experience first, then the tool; install one thing at a time; sandbox an effect in isolation; customise to the design system; one motion language; reduced motion | motion score; the block was prototyped alone before the page | aimed at React component libraries, which this static site does not use |
| 3D Website Project Lab | 28 | READ | all | the no-animation test, the disable-3D test, the five-second test; fix the single biggest problem per version; the 24-hour test; stop condition | critique rounds in docs/REVIEW.md | its projects are fictional products |
| 3D Website Prompt Vault, 50 prompts | 17 | READ | all | prompt 50: one original object that transforms, separates and reconnects per section, transformations connected to the story; prompt 45 (creative developer portfolio) | the block's per-chapter operations | prompts, not a method |
| 30+ Animations, Interactions and Effects | 13 | READ | all | the golden rule (if everything moves nothing is important); section transition as part of the design; cinematic hero entrance kept short for returning visitors; magnetic buttons must not move targets | hero entrance length; no magnetic buttons | |
| The Prompting Playbook | 32 | READ | all | the seven layers; freeze what works; one variable per version; prompt a 3D object by object, material, light, camera, motion, role; the slow-internet test | the block is specified by those six terms in design/art-direction.md | |
| Guide: AI Animated Websites | 27 | READ | all | a general tool guide; its "premium" recipes (glassmorphism, gradient text, blur reveals, particle networks, custom cursors) are exactly what the owner's rules and the house rules forbid | refused list | its advice conflicts with the brief; treated as a floor to avoid |
| Motion-First Interactive Product Engineering Build Book (Vol V) | 59 | PARTIAL | shared standard, universal requirements, contents, Orbital blueprint's experience and motion system | motion must communicate state, time, causality or space; deterministic state machines for sequences; reduced motion keeps information | storyboard | the ten products are unrelated platforms |
| Claude Code Multi-Agent Motion Websites Build Book (Vol VI) | 72 | PARTIAL | design principles, routing, token rules, CLAUDE.md template, agent templates, hooks | "avoid generic AI SaaS card layouts"; motion rules; never hide failing tests | process | multi-agent workflow not used: the owner's instruction is one agent |
| Advanced Engineering Build Book Vol III | 79 | NOT APPLICABLE | front matter and contents | operational platform blueprints (airports, agriculture, satellites) | none | not website craft |
| Advanced Engineering Build Book Vol IV | 124 | NOT APPLICABLE | front matter and contents | enterprise system blueprints | none | not website craft |
| Advanced Engineering Build Book Vol VII (Blender-to-web) | 61 | PARTIAL | method, team, skills, repository shape, Abyssal's motion budgets, accessibility, QA matrix, definition of done | the browser owns live motion, Blender owns the editable asset; still fallbacks for mobile, reduced motion, graphics failure; QA matrix (intro first load, replay, skip, refresh mid-sequence; scroll fast and reverse; context loss; tab hidden) | docs/EVIDENCE.md test list; block kept procedural (no Blender asset needed for a box of slips) | Blender not used: the object is primitives |
| Advanced Engineering Build Book Vol VIII (cinematic, WebGPU) | 35 | PARTIAL | studio standard, banned patterns, team, flow, Rift's identity, opening, choreography, deliverables, motion quality gates, performance budget, release critique questions | banned: one centred 3D object reused identically across the site; scrolling must change the world state; typography participates in motion; mobile gets an art-directed alternative; the release critique questions | the block changes per chapter; critique questions in docs/REVIEW.md | WebGPU not used: no benefit for one instanced mesh |
| Metics Media transcripts A and B | 2 txt | READ via website-playbook references | quality-rubric.md, motion-and-assets.md, transcript lessons | the eight criteria; polish pass A as one batch; mobile pass; evidence before completion | docs/EVIDENCE.md | |
| BRIEF.md, CLAUDE.md, ~/CLAUDE.md release gate, memory | | READ | all | private repo only; mandatory independent visual QA; résumé as the only source of claims | process | |

## Skills

| Skill | Location | Status | Commands actually run | Result |
|---|---|---|---|---|
| website-playbook | ~/.claude/skills/website-playbook | READ (SKILL.md, quality-rubric.md, motion-and-assets.md) | none (process skill) | governs the evidence table |
| design-taste-frontend (taste-skill v2) | ~/.claude/skills/design-taste-frontend | READ (SKILL.md, critique.md, motion.md pinned story, copy.md §2) | `draw.mjs --list sectors/roles`; `draw.mjs --sector personal-portfolio ... --options 3`; `draw.mjs ... --direction pinned-poster`; later `lint.mjs`, `inspect.mjs` | three directions dealt, pinned-poster dealt in full (seed 1110276553), see art-direction.md |
| impeccable 4.7.1 | ~/.claude/skills/impeccable | READ (SKILL.md, new-work.md, init.md, craft-floor.md) | `impeccable context`; `concept-seed --help` (refused without PRODUCT.md); PRODUCT.md written; `concept-seed --scope direction --mode experience` (seed:f1db7f229cc74ef4); later `detect --json`, critique, bolder, overdrive | decision page not served: the owner asked for an unattended single-agent run, so the brief-pinned direction was taken and the substitution is disclosed in the report |
| five-tool-design-pipeline | SKILL.md | READ | none runnable (it chains the other skills) | order followed: system (DESIGN.md study) then taste then Playwright then Three.js |
| 10k-websites | SKILL.md | PARTIAL (first 80 lines: role, done means, phase 1 and 2) | none | its fixed Higgsfield + Hostinger pipeline is not used; its "done means" list adopted |
| ui-ux-pro-max | SKILL.md | PARTIAL (head) | none | not used: its catalogue is for product UI |
| threejs-skills | README + skills list | READ (index) | none | instancing and Lambert lighting used from prior knowledge; the skill files are API references |
| awesome-design-skills | README | PARTIAL | none | the registry of 67 styles; none picked, the taste deal set the system |
| awesome-design-md | github VoltAgent/awesome-design-md, design-md/{elevenlabs,runwayml,sanity}/DESIGN.md | READ (overview, colours, typography, depth, do/don't of each; 2,572 / 2,161 / 3,204 words via gh api) | gh api | principles taken: one typeface for everything (Runway, Sanity); depth from lighting and section colour, zero CSS shadows (Runway); tight display leading 1.0 with negative tracking (all three); a single primary action colour (ElevenLabs). Their palettes are not used. |
| impeccable.style | the skill's own site | counted once with impeccable | | |
| Skiper UI | skiper-ui.com | UNAVAILABLE as a repository (github URL 404; third-party listings disagree on licence: one says paid with attribution for free use) | WebSearch | no component adopted; no code copied |
| Animmaster Lib | | UNAVAILABLE (404 / paid, checked 2026-10-24) | | none |
| ThreeUI (MengTo) | MIT | READ 2026-10-24 | | the CRT shader adapted for THE HALL is removed in this build; nothing of it remains |
| img2threejs | github img2threejs/img2threejs (Apache-2.0) | READ (README via WebFetch) | not installed | its pipeline rebuilds a reference image as procedural Three.js code; this build has no reference image to rebuild (the block is specified, not photographed), so the pipeline does not apply. Its discipline (component tree, staged passes, compare renders to the reference) is followed by hand: blockout, form, material, lighting, interaction, optimisation, each checked against the storyboard still. |

## References observed (captures in ~/projects-site-evidence/redesign-2026-10-25/refs/, 2026-10-25, headless Chromium 1440x900 and 390x844)

| Site | Observed | Principle taken | Limit |
|---|---|---|---|
| lusion.co | light lavender page; a thin nav; one framed band of glossy 3D objects filling 75% of the first screen; "SCROLL TO EXPLORE"; then a statement at 12vw | the object is big and framed, the type is plain and huge, the page is light | the full interactive experience did not run headless; stills only |
| riseof.digital | an intro flight over a 3D city with one line ("Endless inside."); chapter nav across the top (Lobby, Identity, Graphic design...); each chapter one huge line over the set; sound toggle; skip intro | one line per chapter; the chapter nav is the structure; skip from the first frame | cookie dialog present |
| kprverse.com | full-bleed art inside a bordered frame; three stacked uppercase words at 11vw; later chapters: a grid with a black headline, panels with folder-tab corners | huge stacked words over the picture; later chapters change register completely | |
| persepolis.getty.edu | a scroll-driven film: one serif sentence centred over a slowly moving fogged landscape, "Scroll to continue" in a ring, a sound and a settings control bottom-right; the next scroll step changes the sentence and the scene under it | one line per screen; the scene changes under the words; a sound control that is optional | the full WebGL scene ran only partly headless |
| en.manayerbamate.com | a lime-green field, a product can centred and large, flat illustrated shapes around it, big rounded navigation chips; on the phone the first frame is the can alone on a pale ground with soft green discs | one object, one loud flat field, almost no copy on the first screen; the phone is its own composition | shop content, not a portfolio |
| virtualvinyl.app | a cream page split: left a small typewriter title, Start and Login buttons; right a huge record on a turntable filling 60% of the width | one physical object at the scale of the screen; the controls stay small and plain | a sign-up panel overlays the page |
| everswap.lusion.co | captured; a dark hero with a 3D figure and large type (stills in refs/) | large object, large type, nothing else | headless capture only |
| blink.capital | a black field with a glowing planet edge, the name spaced letter by letter across the top, a violet message card, a bottom chip navigation | the name as a frame; one glowing form; a chip nav at the bottom | |
| enpower.trading | UNAVAILABLE: the host does not resolve (ERR_NAME_NOT_RESOLVED on 2026-10-25) | | the URL was unresolved; no other address was found |

## Second pass additions (2026-10-25, later)

| Source | Status | Use |
|---|---|---|
| mrrishit909/us-retail-forecast `data/retail_sales.csv` and `results/backtest_by_horizon.csv` (via gh api) | READ | the forecast operation's columns are the last 24 real months; the fan is the backtest's MAPE by horizon |
| Google Chrome 156 (the owner's browser, through the Claude in Chrome extension) | USED | interactive verification of the cross-document transitions, Back/Forward, focus, rapid clicks, the Home link, Replay |
| WEBGL_lose_context (Chromium) | USED | forced context loss and recovery |

## Precision Atelier pass (2026-10-25, afternoon)

| Source | Path | Sections read | Status | Principle | Decision | Evidence |
|---|---|---|---|---|---|---|
| Precision_Atelier_Claude_Code_Master_Build_Prompt.md | ~/Downloads | all 21 sections | READ | the creative contract, the phase gates, the pitfalls table | this build; docs/EVIDENCE.md follows its gates | docs/ATELIER_PROGRESS.md |
| The concept image | ~/projects-site-evidence/atelier-2026-10-25/refs/precision-atelier-concept.png | the whole image (two frames: the hero on green, the row on ivory) | READ (image) | an exploded register of brass bars, frames, green and ivory slabs, pins; a heavy condensed statement left; four labelled marks over the row | the instrument's parts list, the hero composition, the marks | docs/INSTRUMENT.md, r2/d-02-hero.png |
| Rishit_Website_Building_Master_Playbook.pdf | ~/Downloads | read this morning as page images (ledger above) | READ | authority order; intro as a sequence with a carried element; status labels | unchanged | |
| Advanced Engineering Build Book Vol VII (Blender-to-web) | ~/Downloads | the method (graybox, deterministic build, validate, GLB, re-import, browser-owned motion, still fallbacks), the asset contract, deliverables | PARTIAL (grepped lines and the text around them) | Blender owns the editable asset only when the asset needs it; still fallbacks for mobile, reduced motion, graphics failure; an asset contract with names and pivots | the spike chose procedural geometry; the contract is written anyway (docs/INSTRUMENT.md); the posters are the stills | spike2/, gl-loss.json |
| Advanced Engineering Build Book Vol VIII (cinematic, WebGPU) | ~/Downloads | opening cinematic (the intro must become the first usable product state through a shared object), performance budget, release questions | PARTIAL | the intro hands the same object to the first chapter; explicit budgets | the handoff: the hero's exploded instrument is the first chapter's starting state; docs/PERFORMANCE.md budgets | design/storyboard.md |
| Three.js 0.170.0 source | ~/portfolio-tunnel/tunnel/vendor/three-0.170.0 | MeshPhysicalMaterial (anisotropy), RoundedBoxGeometry, PMREMGenerator.fromScene, ShadowMaterial | READ (the vendored source is the version shipped) | | the materials and the environment | docs/BUILD-THREE.md |
| website-playbook | ~/.claude/skills/website-playbook | SKILL.md, quality-rubric.md | READ | the eight criteria; evidence before completion; the mobile pass | docs/REVIEW.md grades by it | |
| design-taste-frontend | scripts/draw.mjs | `--list sectors`; `--sector personal-portfolio --tone luxury --options 3` | RUN | dealt dark-room and name-as-monument | the conflict with the selected concept is recorded; one principle taken | design/art-direction.md |
| impeccable 4.7.1 | scripts/impeccable | `context --target index.template.html`; detect and critique after the build | RUN | PRODUCT.md loaded; mode Experience | PRODUCT.md updated for the new rules | docs/REVIEW.md |
| img2threejs | | not used | NOT APPLICABLE | the instrument is procedural modelling by hand from a concept image, not a run of that pipeline | described as procedural | |
| Blender 4.5 | ~/Applications | not used in this pass (available) | NOT USED | | the procedural path was chosen after the spike | docs/INSTRUMENT.md |
| Higgsfield, Figma, Canva, Adobe | connectors | not used | NOT USED | no credit spend was authorised; nothing needed them | | |
