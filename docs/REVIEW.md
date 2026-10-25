# Independent review pass: THE BLOCK (2026-10-25)

This is an independent review pass, not an independent person or model: the same session that built the page reviewed
its screenshots and recordings after a break from the code, judging only the pictures, in the formats the installed
skills prescribe. No external reviewer was available. The owner's visual approval remains the real gate.

Evidence reviewed: `~/projects-site-evidence/redesign-2026-10-25/` baseline/ (THE HALL, 2026-10-24 build adc1d7c), r1/, r2/,
r3/ (THE BLOCK at 1440x900 and 390x844 at device scale 2, plus 1024x768, 844x390, reduced motion, no JavaScript, the
archive), `.taste-skill/inspect/`, pace.json, lh-*.json, portfolio-check.txt.

## Baseline defect report (THE HALL, before any change)

Reproduced on 2026-10-25 from baseline/d-room1.png, m-room1.png, d-gate.png:

1. Blurry project presentation: the 224 wall screens are 4096 px atlas cells (about 250 px each) scaled to a metre-wide
   screen; close to the camera every title on the walls is unreadable (right half of d-room1). Cause: low source
   resolution per cell, not a filter. The flagship screens themselves were drawn live and were sharp.
2. The gate was a ring and a counter on black: nothing of the site in the first frame (d-gate).
3. Dark corridor, thumbnail wall: against the owner's rules (no thumbnails, loud colour, one object).
4. Lag: on this Mac the pacing script measured 16.7 ms median with no frame over 33 ms, so the stutter reported by the
   owner was not reproduced here; the four live CRT canvases plus a post pass were the likely cost on a weaker GPU
   (Lighthouse TBT reached 1,020 ms under load). Not reproduced, recorded honestly.
5. The cylinder (THE TOWER) had already been removed in THE HALL; no cylinder, carousel, torus or ring exists now.

## Critique rounds (taste skill format)

```
ROUND 1 (r1, first build)
Seen in one second: a white block of records on a red field, a huge name.
Idea (one sentence): the body of work is one block of record slips that each project machines (cuts, layers, bends, opens).
Live thing: the departure hour cuts the block at the published on-time rate; drag turns it.
Layout words by section: hero=statement+object / work=split x4 (pinned) / check=split / experience=line-up / archive=line-up+sheet / contact=statement
Scores: design 6.5 · usability 6 · creativity 8 · content 7.5 → overall 6.75
Caps applied: anything covering a headline (6): the panels overflowed their screen and the chapter title crossed the question.
Top three problems:
1. Panel copy taller than the viewport; the next panel's words overlap (d-panel2). Fix: fragment moved to the right column's foot, type steps cut, line hidden under 820 px.
2. Panel scroll positions wrong: offsetTop was relative to the section (d-panel1b showed the hero). Fix: document positions cached from getBoundingClientRect.
3. The forecast and open states read as clouds (d-panel3, d-panel4). Fix: 24 monthly columns with a fanned range; the halves slide apart and the cited slip lifts.

ROUND 2 (r2)
Seen in one second: the same, and now each project changes the block.
Scores: design 7.5 · usability 7.5 · creativity 8 · content 7.5 → overall 7.6
Caps applied: none.
Top three problems:
1. The dbt strata rise into the top bar (d-panel2). Fix: strata centred lower.
2. The archive sheet sits behind the table's right columns (d-archive-b); on the phone it sits under the rows. Fix: sheet scaled and moved right, table narrowed; the phone keeps the closed block small.
3. The top bar has no ground, so headings pass through its words (m-archive-b). Fix: the bar takes the field colour.

ROUND 3 (r3, after the inspector and the detector)
Seen in one second: a white block of records, a huge name, a red field. A stranger can say in five seconds: a data analyst in Tampa, 224 case studies, the numbers were checked; the next step is "See the work".
Idea: unchanged. Live thing: unchanged.
Layout words: hero=statement+object / work=split (pinned, four operations) / check=split with a control / experience=figure+line-up / archive=search+line-up+sheet / contact=e-mail statement. No two neighbours share a layout.
Scores: design 8 · usability 8 · creativity 8.5 · content 8 → overall 8.1
Caps applied: none that the page earns. The inspector's remaining FAILs are listed below with the reason each is defended or fixed.
Remaining, honestly:
1. The opening's first frame on a cold load is the poster, then the slips scatter in: on a slow connection the module arrives late and the scatter starts after the visitor has already read the hero (no fake loader covers it, by design).
2. The object is lit, not shadowed: there is no contact shadow under the block, so on the paper field it can read as floating. A soft contact shadow was refused by the house rules (no shadows); the field colour and the block's own face shading carry it.
3. The archive sheet (224 lit of 1,440 slips) is the one state that reads as a wall; it is kept because the archive is a wall of case studies, and it is the only one.
```

Inspector findings (`inspect.mjs`, final run) and their disposition:

| Finding | Disposition |
|---|---|
| Headlines over two lines ("How wrong is a forecast, usually?", "Pick a departure hour.") | Fixed: "How wrong is a forecast?", "Pick an hour." |
| Body text 14 px | Fixed: source lines at 16 px; 14 px only for the corners and the HUD |
| Contrast 4.4:1 on the red field | Fixed: red #cf2419 with #f0f0f0 text, 4.7:1 |
| Sections lopsided ("88.7", "All 224."), empty screens 4, 8, 10, 11 | Defended: the right half of every screen holds the object on the canvas, which the DOM inspector cannot see; the "empty" screens are the scroll runway inside each pinned panel, with the block performing on them (r3/d-panel1b, d-panel3) |
| Reduced motion hides "Rishit Raj Mathur" (the stub) and "Skip the opening" | Defended: the stub is the name in the top bar, shown only once the h1 has scrolled away; the skip button exists only while the opening runs, and there is no opening under reduced motion |
| No real photographs, no footage | Defended with the brief: the subject is software; the four live fragments are the projects' own interfaces (data-ui), and the owner's rules forbid stock imagery |
| Pinned text over pictures | Defended: the pinned words never cross the fragment (same sticky box); the "picture" crossed is the canvas object, placed in the other column |
| Yellow-cream text | Fixed: neutral #f0f0f0 |
| 17 type sizes | Reduced to about nine (the fragments and the HUD add a few); the five steps are the tokens |
| Name-only h1 | Fixed: the line under the name says data analyst in Tampa, every number checked |
| Blank 452 px stretch | Fixed: the archive no longer forces a full screen |

Lint (`lint.mjs`): the Geist Mono face is loaded only for the fragments' own code labels (marked taste-skill-ignore); the
outline buttons use a border, not a shadow.

Impeccable detector (`impeccable detect --json index.html home.css`): the only findings were the 4.4:1 contrast
advisories, fixed as above. Re-run after the fix: no findings on index.html.

## Impeccable critique (degraded)

⚠️ DEGRADED: single-context (the owner's instruction is one agent, no sub-agents; Assessment A and B ran in sequence here).

Design specificity: the composition could not be used unchanged by another portfolio: the object is this analyst's
records, the four operations are these four projects' methods, the figures and sources are theirs.

Heuristics (0-4): visibility of status 3 (chapter label, field colour, the counts; no loading state is shown because
none is needed); match with the world 4; control and freedom 3 (skip, native scroll, no hijack; the opening cannot be
replayed); consistency 4; error prevention n/a (no destructive action); recognition over recall 3 (nav always present;
the archive query language needs the hint line); flexibility 3 (keyboard, touch, drag); aesthetic and minimalist 4;
error recovery n/a; help 2 (the query syntax is explained in one line only).

Cognitive load: no decision point with more than four visible options (the top bar has four links and the sound toggle).
Emotional journey: peak at the opening and the check; the quiet is the experience chapter; the end is the e-mail at
display size. Priority issues: see the round-three remainders. Questions skipped: the owner asked for an unattended run.

Bolder (scoped to the experience chapter, which read flattest): the chapter now opens with the one figure the résumé
carries (22% less report turnaround at TraceRT) in the page's own figure vocabulary; nothing else changed.

Overdrive (one direction taken, two recorded): taken: the clicked panel's live fragment and title travel into the case
study's cover and heading through cross-document View Transitions, and back. Recorded, not built: a Web Audio tick that
follows the hour input; CSS scroll-driven animation for the panel words (Firefox has no support). Browser support for
cross-document View Transitions: Chrome and Safari; Firefox falls back to a plain navigation.

## The master prompt's rubric (internal target 85/100; floor 70% per category)

| Category | Points | Score | Anchored on |
|---|---|---|---|
| Art direction and originality | 20 | 16 | r3/d-02-hero, d-panel1b, d-check-8pm: one object, loud field, a method per project; the idea passes the competitor test |
| Opening and still-frame impact | 15 | 12 | r3/d-00-first, d-01-open-1400, d-02-hero; the still frame is the poster |
| Motion and continuity | 20 | 16 | pace.json (16.7 ms median on every path); the block persists from the first frame to contact; recordings not yet made for this round |
| Typography and visual system | 15 | 12 | inspector: General Sans only, two colours, five steps |
| Content and storytelling | 10 | 8 | four panels with figure, range, source, line, fragment, button; the check; the résumé line-up |
| Mobile and accessibility | 10 | 8 | r3/m-*, landscape, 1024; Lighthouse accessibility 100 after the table headers and the sound button name |
| Performance and resilience | 10 | 8 | Lighthouse 92 / 100 / 100 / 100 on the gzip server, 419 KiB first view, no-JS and no-WebGL frames, context loss handled |
| Total | 100 | 80 | below the 85 target; no category below 70% |

What keeps it under 85: the opening is one event, not a sequence a stranger would remember for its choreography; the
object's material is flat Lambert; the phone has no exploration beyond scroll and the hour input.

## Motion scorecard

| Section | Role | Movement | In | Out | Quiet state | Fallback | Observed defect | Evidence |
|---|---|---|---|---|---|---|---|---|
| Opening | arrival | slips fly into the block, the sweep, the counts | from the poster | holds as the hero | the hero | poster, or reduced motion shows the final state | first frame on a cold load is the poster for as long as the module takes | r3/d-00-first, d-01-open-* |
| Hero | identity | pointer tilt, drag to turn | | the name scrolls away, the block holds | yes | none needed | none | r3/d-02-hero |
| Work 1 to 4 | the method | the operation scrubbed by scroll; the block returns to BLOCK between panels | words rise once | words leave with the panel | the operation's end state holds for the last third | reduced motion shows end states; no WebGL shows the still | the dbt strata reached the top bar in r2 (fixed) | r3/d-panel1b to d-panel4 |
| The check | consequence | the cut moves with the input | | | holds the hour | native range | none | r3/d-check-8pm, m-check |
| Experience | rest | the block settles small | | | yes | | none | r3/d-exp |
| Archive | the whole | the block spreads into the sheet and gathers | | | | the phone keeps the block closed | none | r3/d-archive-b |
| Contact | the close | the block rests; the e-mail is the statement | | | yes | | none | r3/d-contact |
| Top bar, buttons | feedback | 2 px lift, underline | | | | focus ring | none | |
