# Requirements-to-evidence matrix: THE BLOCK (2026-10-25)

Status values: PASS, FAIL, NOT TESTED, BLOCKED, DEFENDED (a finding left as is, with the reason). Evidence paths are
under `~/projects-site-evidence/redesign-2026-10-25/` unless absolute. "Suite" is `tests/portfolio-check.cjs`
(portfolio-check.txt). The tested commit is named in the README of that folder.

| Requirement (source) | Implementation | Check | Evidence | Status | Open issue |
|---|---|---|---|---|---|
| Remove the cylindrical selector and its choreography (prompt §15) | THE TOWER's cylinder was gone in THE HALL; THE HALL's wall of 224 screens is gone now; no carousel, torus or ring | baseline/ vs r3/ | baseline/d-room1.png, r3/d-02-hero.png | PASS | |
| Every showcased project has an individually authored animated introduction with a crisp readable title (§15) | four panels, each a different operation of the block (slice, layer, bend, open) with the question as an HTML heading and the figure in DOM text; the live fragment at device resolution | r3 panels; the inspector measured the type | r3/d-panel1b..4, m-panel1b, m-panel3 | PASS | |
| Project titles never blurry; no sharpen filters (§15) | no texture scaling: titles are DOM text, fragments are 2D canvases sized to CSS width x device pixel ratio (max 2) | screenshots at scale 2 | r3/d-panel2.png (the fragment's labels are legible) | PASS | |
| Cinematic intro with a signature event and a handoff (§7, §15) | first frame = HTML + poster; the slips fly in, the sweep, the counts roll; the name scrolls away while the block holds; the field turns at the first chapter | suite 3 and 5; r3 opening frames | r3/d-00-first, d-01-open-700..3400, d-02-hero; portfolio-check.txt | PASS | the first frame on a cold load is the poster until the module arrives |
| Truthful loading, no fake percentages or timers (§7) | no loader; the poster stands in; the event starts when the module has loaded | code reading, r3/d-00-first | | PASS | |
| Skip usable by keyboard and touch; no replay on internal navigation; reduced motion respected (§7) | Skip button, wheel, touch, key; sessionStorage seen; html.opening only without reduced motion | suite 5, 6, 7 | portfolio-check.txt | PASS | |
| Autoplay or scroll-controlled, chosen explicitly (§7) | the opening is autoplay (2.4 s, skippable); everything after is scroll-controlled with native scroll | storyboard.md; suite | | PASS | |
| Core content reachable without JS, WebGL (§7, §12) | no-JS: every section, the stills, the per-section ground; no WebGL: the poster | suite 1, 8; r3/d-nojs*.png | r3/d-nojs.png, d-nojs-panel.png | PASS | |
| Header, hero, selected work, project views, resume/experience, contact, archive access (§8) | top bar; hero; four panels; case studies (unchanged); experience line-up; contact; archive line-up and all.html | suite 1 | | PASS | |
| Truthful content from the résumé and the data; no hard-coded counts (§8) | counts from data/github.json at build; experience from resume.pdf; figures from featured.json and the case studies | suite 1 (counts), code reading | | PASS | |
| Resume, e-mail, GitHub, LinkedIn, case studies, external links work (§8) | real links | suite 1, 10 (every internal link on disk) | | PASS | external URLs not fetched in this pass |
| Deep links and back/forward (§8) | #work etc.; Back from a case study returns without replaying | suite 6, 10 | | PASS | |
| Motion score for the whole journey; one owner per property (§9) | design/storyboard.md | document | | PASS | |
| Hover has touch equivalents; text selectable; no custom cursor (§9) | drag only on fine pointers; no cursor; no hover-only information | code reading; r3/m-* | | PASS | |
| Project opening preserves a relationship; closing returns focus and position (§9) | cross-document View Transitions carry the title and the fragment into the case study's heading and cover; Back restores the scroll position natively | suite 10 (Back) | | PASS (transition itself NOT TESTED visually: headless capture cannot record cross-document transitions) | |
| Asset pipeline: real-time 3D where viewpoint changes, HTML for text (§10) | one procedural object; no generated assets; no credits spent | design/art-direction.md | | PASS | Blender and Higgsfield not used, by choice |
| Context loss and recovery (§10) | webglcontextlost shows the poster, restored shows the canvas | code reading | | NOT TESTED | no forced loss was run |
| First view about 1.5 MB (§11) | 420 KiB | Lighthouse | lh-index-mobile.json | PASS | |
| Scene budgets, pixel ratio 1 rising to 1.5 with hysteresis (§11) | block.js | code reading, pace.json | docs/PERFORMANCE.md | PASS | |
| Frame-time distribution on intro, scroll, reverse, flick, input, return (§11, §15) | pace.cjs | pace.json | docs/PERFORMANCE.md | PASS on this Mac | not measured on a phone |
| LCP 2.5 s, CLS 0.1, INP 200 ms (§11) | | Lighthouse mobile | lh-index-mobile.json: LCP 2.0 s, CLS 0.003, TBT 0 ms | PASS (lab) | INP is a lab proxy |
| Desktop, tablet and phone compositions; landscape; 200% zoom (§12) | three compositions in home.css; landscape unpins the panels | r3 at 1440, 1024, 390, 844x390 | r3/d-*, t1024-panel2, m-*, landscape-* | PASS | 200% zoom NOT TESTED; 1920 NOT TESTED |
| WCAG 2.2 AA: one h1, landmarks, skip link, focus, names, contrast, 44 px targets (§12) | one h1, header/main/footer, skip link, focus-visible 3 px, labelled range, table headers, 44 px links and 48 px buttons | Lighthouse accessibility 100 (home), suite 6 (keyboard), suite 11 (button size) | lh-index-mobile.json | PASS | screen reader reading order NOT TESTED with a screen reader |
| Reduced motion is a composition (§12) | no opening, no entrances, the block holds end states | suite 7, r3/d-reduced.png | | PASS | |
| Keyboard, focus over the scene, disabled JS, WebGL failure, slow network (§12) | | suite 1, 6, 8; Lighthouse slow 4G | | PASS | slow-network visual check NOT TESTED beyond Lighthouse's throttle |
| Independent review pass with the rubric and the motion scorecard (§13) | docs/REVIEW.md | document | | PASS (degraded: same session) | 80/100 against the 85 target |
| Functional journeys: bypass intro, reach projects, open and close a case study, back/forward, archive filters, resume, contact, keyboard, touch-sized layouts, reduced motion, fallbacks (§14) | suite | portfolio-check.txt | | PASS | |
| Repeated interactions, interrupted transitions, resize/orientation, zero matches (§14) | suite: rapid hour sweep (pace), zero archive matches, five widths | pace.json, suite 9, 11 | | PASS | orientation change mid-scroll NOT TESTED |
| Console errors and failed requests (§14) | suite's last check; shots.cjs report | portfolio-check.txt, r3/report.json | | PASS | |
| Page length is chapters, not filler (§15) | hero, four panels, the check, experience, archive, contact: 10,000 px | r3 | | PASS | |
| Substantive interaction with a visible consequence, labelled as a demonstration (§15) | the hour input cuts the block at the published rate | suite 4; r3/d-check-8pm | | PASS | |
| No transition stutter under the test conditions, with a quality fallback (§15) | pace.json; adaptive pixel ratio | | | PASS on this Mac | a weak GPU is untested |
| No blank or stranded navigation states (§15) | the poster is always under the canvas; no loader gate | suite 8; r3/d-nojs | | PASS | |
| Website-playbook rubric (eight criteria) | see below | | | | |

## The eight criteria (website-playbook)

| Criterion | Intended outcome | Implementation decision | Evidence inspected | Status | Remaining correction |
|---|---|---|---|---|---|
| Point of view | one idea in every section: the work is a block of records each project machines | the object persists from the first frame to contact; the field alternates | r3 every stop | Strong | |
| Typography | one face, huge display, few steps | General Sans only; five tokens | inspector report | Strong | about nine sizes measured once the fragments and HUD count |
| Colour | two colours plus the text ink, with roles | paper, red, oxblood, off-white | inspector, detector | Strong | |
| Hierarchy | one read per screen | name; question then figure; the e-mail | r3 | Strong | |
| Imagery | the subject's own | four live interface fragments and the object | r3 panels | Mixed | no photographs, by the brief; the fragments are small on desktop |
| Motion | meaningful, one owner each | storyboard.md; pace.json | r3 rounds, pace | Strong | recordings of the opening not captured this round |
| Mobile | its own composition | block on the top 40svh, words below; landscape unpins | r3/m-*, landscape | Strong | the phone cannot drag the block |
| Invisible quality | measured | Lighthouse 98 / 100 / 100 / 100, suite green, no console errors | lh json, suite | Strong | archive page performance 87 |
