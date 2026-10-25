# Requirements-to-evidence matrix: THE BLOCK (2026-10-25, second pass)

Status values: VERIFIED, FAILED, NOT TESTED, BLOCKED, DEFENDED (a finding left as is, with the reason). "PASS" in older rows means VERIFIED. Evidence paths are
under `~/projects-site-evidence/redesign-2026-10-25/` unless absolute. "Suite" is `tests/portfolio-check.cjs`
(portfolio-check.txt). The tested commit is named in the README of that folder.

| Requirement (source) | Implementation | Check | Evidence | Status | Open issue |
|---|---|---|---|---|---|
| Remove the cylindrical selector and its choreography (prompt §15) | THE TOWER's cylinder was gone in THE HALL; THE HALL's wall of 224 screens is gone now; no carousel, torus or ring | baseline/ vs r3/ | baseline/d-room1.png, r3/d-02-hero.png | PASS | |
| Every showcased project has an individually authored animated introduction with a crisp readable title; each with a different silhouette and a label (§15; second directive §2, §5) | four operations from BLOCK, each labelled with what it stands for; the forecast uses the real series and the backtest fan | recordings/final/panel1..4-sheet.jpg; r6 panels | | VERIFIED | |
| Project titles never blurry; no sharpen filters (§15) | no texture scaling: titles are DOM text, fragments are 2D canvases sized to CSS width x device pixel ratio (max 2) | screenshots at scale 2 | r3/d-panel2.png (the fragment's labels are legible) | PASS | |
| Cinematic intro with a signature event and a handoff (§7, §15); Replay (second directive §3) | five states: HTML + poster, loosen (0.8 s), the band collects the rows while the counts roll (1.4 s), settle, handoff on scroll; Skip; Replay with teardown; reduced-motion version | suite 3, 5, 6, 7; recordings; Chrome Replay check (three rapid clicks, one timeline, counts land) | recordings/final/opening-fresh-sheet.jpg, opening-replay-sheet.jpg, opening-reduced.webm; r5/d-01-open-* | VERIFIED | the first frame on a cold load is the poster until the module arrives |
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
| Project opening preserves a relationship; closing returns focus and position (§9; second directive §7) | cross-document View Transitions carry `title` and `cover`; Back restores scroll and focus | real Chrome 156: entry, Back (scroll 2,775 kept, focus on the title), Forward, Back, three rapid clicks (one entry), direct load, the Home link to `#feature-<slug>`; headless clip | recordings/final/case-entry-return-chrome.gif, case-entry-return-sheet.jpg; suite 10 | VERIFIED | Firefox (no cross-document transitions) falls back to a plain navigation: NOT TESTED in Firefox |
| Asset pipeline: real-time 3D where viewpoint changes, HTML for text (§10) | one procedural object; no generated assets; no credits spent | design/art-direction.md | | PASS | Blender and Higgsfield not used, by choice |
| Context loss and recovery (§10; second directive §9) | webglcontextlost shows the poster, restored shows the canvas; one loop; no listener pile-up | five forced losses through WEBGL_lose_context; WebGL unavailable; poster missing; module delayed | gl-loss.json | VERIFIED | |
| First view about 1.5 MB (§11) | 420 KiB | Lighthouse | lh-index-mobile.json | PASS | |
| Scene budgets, pixel ratio 1 rising to 1.5 with hysteresis (§11) | block.js | code reading, pace.json | docs/PERFORMANCE.md | PASS | |
| Frame-time distribution on intro, scroll, reverse, flick, input, return, project changes, Replay (§11, §15; second directive §10) | pace.cjs with p95, p99, max, heap | pace.json, pace-before-2d0763a.json | docs/PERFORMANCE.md | VERIFIED on this Mac | not measured on a phone; one 183 ms frame on one reverse run unexplained |
| LCP 2.5 s, CLS 0.1, INP 200 ms (§11) | | Lighthouse mobile | lh-index-mobile.json: LCP 2.0 s, CLS 0.003, TBT 0 ms | PASS (lab) | INP is a lab proxy |
| Desktop, tablet and phone compositions; landscape; 200% zoom; intermediate widths; short heights (§12; second directive §8) | three compositions; landscape unpins; the tablet column defect fixed | r5x at 540, 1024, 1280x620, 720x450 at 2x (200% zoom), 844x390, 360, 1920; r6 at 1440 and 390; no horizontal overflow at any | r5x/*.png, r6/* | VERIFIED | a real phone NOT TESTED (viewport emulation on this Mac) |
| WCAG 2.2 AA: one h1, landmarks, skip link, focus, names, contrast, 44 px targets (§12) | one h1, header/main/footer, skip link, focus-visible 3 px, labelled range, table headers, 44 px links and 48 px buttons | Lighthouse accessibility 100 (home), suite 6 (keyboard), suite 11 (button size) | lh-index-mobile.json | PASS | screen reader reading order NOT TESTED with a screen reader |
| Reduced motion is a composition (§12) | no opening, no entrances, the block holds end states | suite 7, r3/d-reduced.png | | PASS | |
| Keyboard, focus over the scene, disabled JS, WebGL failure, slow network (§12) | | suite 1, 6, 8; Lighthouse slow 4G | | PASS | slow-network visual check NOT TESTED beyond Lighthouse's throttle |
| Independent review pass with the rubric and the motion scorecard (§13) | docs/REVIEW.md, two passes | document | | VERIFIED (degraded: same session) | 86/100 against the 85 target, each change anchored |
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
| Imagery | the subject's own | four live interface fragments (540 px, linked) and the object with its shadow | r6 panels | Strong | no photographs, by the brief |
| Motion | meaningful, one owner each | storyboard.md; pace.json; recordings/final | sheets and clips | Strong | |
| Mobile | its own composition | block on the top 40svh at 60%, words below; landscape unpins | r6/m-*, r5x | Strong | no drag on touch, by decision |
| Invisible quality | measured | Lighthouse 98 / 100 / 100 / 100, suite green, no console errors | lh json, suite | Strong | archive page performance 87 |

## Second directive: additional rows

| Requirement | Implementation | Check | Evidence | Status | Open issue |
|---|---|---|---|---|---|
| The slip count has a stated meaning (§2) | 1,440 is an artistic construction; the hero card says it is not a count; the facts are the two counts from the data | r6/d-02-hero | | VERIFIED | |
| Material quality without blur (§4) | shadow-casting key, shadow-only ground, per-slip variation; no blur, no glass, no post pass | r6 stills at desktop and phone | | VERIFIED | |
| Fragment legibility checked in the render (§5) | 540 px fragment at 2x | r6/d-panel1b, d-panel2 read at full size | | VERIFIED on desktop; on the phone the fragment is full width and legible (r6/m-panel2) | |
| Experience: object clear of the table (§5) | stage 84% / 28% at 0.4 | r6/d-exp | | VERIFIED | |
| Continuity per boundary documented (§6) | design/storyboard.md | document | | VERIFIED | |
| Replay respects the motion preference (§3) | reduced motion runs the band-only version | opening-reduced.webm; suite 7 | | VERIFIED | |
| Repeated loss and recovery without memory growth (§9) | heap 6 MB flat across five cycles | gl-loss.json | | VERIFIED | |
| Blocked autoplay (§9) | no autoplay media on the home | | | NOT APPLICABLE | |
| Real phone (§8) | | | | BLOCKED: no device available | |
