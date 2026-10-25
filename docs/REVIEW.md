# Review passes: THE BLOCK (2026-10-25)

Both passes are separate review passes by the same session that built the page, judged on screenshots, contact sheets
and recordings after the implementation, in the formats the installed skills prescribe. No external reviewer was
available. The owner's visual approval remains the real gate.

Evidence: `~/projects-site-evidence/redesign-2026-10-25/` baseline/ (THE HALL, commit adc1d7c), r1 to r3 (THE BLOCK
first pass, commit 2d0763a), r4 to r6 and r5x (second pass), recordings/final/ (webm clips with six-frame contact
sheets, plus the Chrome GIF), `.taste-skill/inspect/`, pace.json, pace-before-2d0763a.json, gl-loss.json, lh-*.json,
portfolio-check.txt.

## Baseline defect report (THE HALL, before any change, 2026-10-25 morning)

1. Blurry project presentation: 224 wall screens were 4096 px atlas cells (about 250 px each) scaled up to a metre-wide
   screen; titles were unreadable (baseline/d-room1.png). Cause: source resolution, not a filter.
2. The gate was a ring and a counter on black: nothing of the site in the first frame (baseline/d-gate.png).
3. A dark corridor and a thumbnail wall, against the owner's rules.
4. Lag: not reproduced on this Mac (16.7 ms median, nothing over 33 ms); the four live CRT canvases plus the post pass
   were the likely cost on a weaker GPU (Lighthouse TBT reached 1,020 ms under load). Recorded, not reproduced.
5. The cylinder (THE TOWER) had already been removed in THE HALL.

## First pass (commit 2d0763a): rounds 1 to 3

See the git history of this file for the full rounds. Round 3 scored design 8 · usability 8 · creativity 8.5 · content
8 (overall 8.1) and the master prompt's rubric at 80/100, with these honest remainders: the opening was one event rather
than a sequence; the object's material was flat and floated on the field; the phone had no exploration; the
cross-document transition, context loss and real-phone pacing were untested.

## Second pass (this commit): what changed, by remainder

| Remainder from the first pass | What was done | Evidence that shows it |
|---|---|---|
| Opening was a set of effects | A sequence: anticipation (the slips loosen from the top down, 0.8 s), the signature event (a band of light passes down and collects each row, the counts roll with it, 1.4 s), resolution (settle, 0.4 s), handoff (the block holds while the name scrolls off, the field turns at the first panel). Replay control added; AbortController tears down listeners; the timeline is killed before a new one; reduced motion runs a band-only version | recordings/final/opening-fresh-sheet.jpg (0.4 s loose, 1.2 s the band mid-block with counts at 95 / 93, 2.1 s collected), opening-replay-sheet.jpg, opening-reduced.webm; r5/d-01-open-1400.png |
| Material flat, the object floated | A shadow-casting key light with a shadow-only ground under the block (the owner's rule is no blur, not no shadows), per-slip material variation, a lower hemisphere tone, the key light aimed at the block's stage | r6/d-02-hero.png, d-panel4.png (the opened halves cast onto the ground), d-check-8pm.png |
| The forecast state was drawn to an invented shape | The bend state now lays out the last 24 months of the project's real series (Aug 2024 to Jul 2026, US Census via FRED, read from the repository's data file) and 12 months ahead that follow last year's shape and fan by the backtest's error at each horizon (the project's own backtest_by_horizon.csv). The label says exactly that | r6/d-panel3.png, m-panel3.png; `featured.json` `series` and `fan`; recordings/final/panel3-sheet.jpg |
| The slip count could be read as a record count | The hero card says the block stands for the records and is not a count; the storyboard records 1,440 as an artistic construction | r6/d-02-hero.png (card) |
| Each transformation needed a label | One line per panel names the operation and what it stands for (star schema; dbt's three layers and 31 tests; the real series and the fan; the cited slip) | r6/d-panel1b..4 |
| Fragment small, labels unreadable | The fragment is 540 px wide on desktop (was 400) and is itself a link into the case study; at 2x device scale the Florida dashboard's hour labels, the dbt node names and the 10-K question read (zoom check in r6/d-panel1b, d-panel2) | r6 panels |
| Experience: the object sat over the table | The block rests at 84% / 28%, scale 0.4, clear of the table's last column | r6/d-exp.png |
| Mobile: no exploration | Judged: turning the block adds nothing a reader needs on a phone; the operations themselves are the exploration and run on scroll. The block takes the top 40svh at 60% scale so each operation reads whole; no drag on touch, by design | r6/m-panel1b, m-panel2, m-panel3; recordings/final/phone-walk.webm |
| Cross-document transition untested | Verified in real Chrome 156 (desktop): entry from a panel title carries `title` and `cover` names into the case study; Back returns to the same scroll (2,775 px) with focus on the clicked title; Forward and Back again; three rapid clicks produce one navigation and one history entry; a direct case-study load and its Home link land on `#feature-<slug>` at the panel; no opening replays on return | recordings/final/case-entry-return-chrome.gif, case-entry-return-sheet.jpg; suite checks 10 |
| Context loss untested | Forced through WEBGL_lose_context five times: on loss the poster shows and the page stays navigable (the hour input still updates the figure, scroll and field colour work); on restore the canvas draws again (15.3% paper pixels), one requestAnimationFrame loop before and after (60 per second), JS heap flat at 6 MB across the cycles, no errors. Also: WebGL unavailable (poster, counts final, Replay harmless), the poster missing (no error, the canvas carries), the module delayed 4 s (name and nav readable at 1 s, the sequence runs on arrival) | gl-loss.json |
| Pacing lacked p99 and project changes | p99 and max added; project jumps and Replay added; heap recorded | pace.json |

## Critique (taste skill format), round 4 on r6 and the sheets

```
ROUND 4
Seen in one second: a white block of records on a red field under a huge name, with a shadow that puts it on the floor.
Idea (one sentence): the body of work is one block of record slips that each project machines; the opening is the check reading and filing every record.
Live thing: the departure hour cuts the block at the published rate; Replay; drag on desktop.
Layout words: hero=statement+object / work=split x4 (pinned, four operations, each labelled) / check=split with a control / experience=figure+line-up with the object resting / archive=search+line-up+sheet / contact=e-mail statement. No two neighbours share a layout.
Scores: design 8.5 · usability 8.5 · creativity 8.5 · content 8.5 → overall 8.5
Caps applied: none the page earns. Inspector FAILs remaining and their disposition are listed below.
Remaining, honestly:
1. The first frame on a cold load is the poster for as long as the module takes; on a 4 s delay the visitor reads the hero before the sequence starts (by design: no fake loader).
2. The opening's first rendered frame costs one long task (shader compile with the shadow map, 100 to 130 ms) on this Mac; the poster covers it.
3. The archive sheet is the one state that reads as a wall; kept because the archive is one.
4. No real phone was measured.
```

Inspector (`inspect.mjs`, final run): the 768 px headline wraps were a real defect (the fragment forced a second grid
column at tablet width) and are fixed; "lopsided" and "empty screens" are the canvas object the DOM inspector cannot
see (r6 shows the block in every one of those screens); "reduced-hidden" is the name stub and the Skip button, which
are only shown once the h1 has scrolled away or while the sequence runs; no photographs by the brief; the pinned words
never cross the fragment.

Impeccable detector on index.html and home.css: four findings, all defended: two "cramped padding" hits are the full-bleed
chapters whose children carry the gutter themselves; two "overused font" hits are Geist, used only inside the projects'
own interface fragments.

Impeccable critique (degraded, single context by the owner's instruction): design specificity holds (the object is this
analyst's records; the four operations are these projects' methods; the forecast columns are the project's real series).
Heuristics unchanged from the first pass except visibility of status 4 (Replay and Skip are discoverable, the counts and
the chapter label follow). Bolder was applied in the first pass (the experience figure). Overdrive: the fragment-to-cover
View Transition is now verified in a real browser; a second direction (a Web Audio tick on the hour input) remains
unbuilt.

## The master prompt's rubric (85/100 target; floor 70% per category)

| Category | Points | First pass | Now | What changed, visibly |
|---|---|---|---|---|
| Art direction and originality | 20 | 16 | 17 | the forecast is the real series; every operation is labelled; the count is explained |
| Opening and still-frame impact | 15 | 12 | 13 | a three-beat sequence with a Replay; the still has a grounded object with a shadow |
| Motion and continuity | 20 | 16 | 17 | the carry-over per boundary is documented and the field cuts on Replay; the transition into the case study is verified |
| Typography and visual system | 15 | 12 | 13 | the tablet wrap defect fixed; the operation line added in the body step |
| Content and storytelling | 10 | 8 | 9 | the labels, the real series, the not-a-count note |
| Mobile and accessibility | 10 | 8 | 8 | judged and documented rather than added; Lighthouse accessibility 100; no real phone |
| Performance and resilience | 10 | 8 | 9 | context loss, no WebGL, missing poster and slow module exercised; pacing with p99 |
| Total | 100 | 80 | 86 | |

## Motion scorecard

| Section | Role | Movement | In | Out | Quiet state | Fallback | Observed defect | Evidence |
|---|---|---|---|---|---|---|---|---|
| Opening | arrival | loosen, the band collects, settle, counts roll | from the poster | holds as the hero | the hero | poster; reduced: band only | the first rendered frame is a long task | opening-fresh-sheet.jpg |
| Hero | identity | pointer tilt, drag | | the name scrolls off, the block holds | yes | | none | r6/d-02-hero |
| Work 1 to 4 | the method | the operation scrubbed by scroll, from BLOCK each time | words rise once | words leave | the end state holds for the last third | reduced: end states; no WebGL: the still | none | panel1..4-sheet.jpg |
| The check | consequence | the cut moves with the input | | | holds the hour | native range | none | check-sweep.webm, r6/d-check-8pm |
| Experience | rest | the block settles small, clear of the table | | | yes | | none | r6/d-exp |
| Archive | the whole | the block spreads into the sheet and gathers | | | | phone keeps the block closed | none | r6/d-archive-b |
| Contact | the close | the block rests; the e-mail is the statement | | | yes | | none | r6/d-contact |
| Into a case study | continuity | the title and the fragment travel into the heading and the cover | | Back reverses | | plain navigation where unsupported | none | case-entry-return-chrome.gif |
