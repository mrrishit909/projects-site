# Review: Precision Atelier (2026-10-25)

A separate critical review pass by the same session that built the page, judged on the captures, contact sheets,
recordings and the real-Chrome checks after the implementation. No external reviewer was available; independence is
not claimed. The owner's visual verdict on the built page is the real gate.

Evidence: `~/projects-site-evidence/atelier-2026-10-25/` baseline/ (THE BLOCK), refs/ (the concept image), spike/ and
spike2/ (the lab), r1/ (first page build), r2/ (after the composition fixes), r3/ (final), taste/ (inspector), recordings/final/,
pace.json, gl-loss.json, lh-*.json, portfolio-check.txt.

## Round 1 (r1): defects found by looking

1. The chapter's buttons collided with a bottom-left chapter label and the evidence fragment overlapped the object: the
   label removed, the buttons moved into the text column, the fragment given the right column's full height and the
   object raised to 46%. Fixed in r2.
2. The instrument was invisible on the ivory sections (an opaque reading block over the fixed canvas): the block made
   transparent on the home with JavaScript (opaque without it), the ground switching at the handoff. Fixed in r2.
3. The timeline's forecast bars ran off the right edge: the spread tightened. Fixed in r2.
4. The star schema's pins crossed through the fact table: they now run from the plate's corners. Fixed in r2.
5. Phone: the controls wrapped to a third row over the object; the marks collided with the nav: the bar re-gridded
   (brand and controls on one row, nav below) and chapters padded under it. Fixed in r2.
6. The headline waited for the sequence: it is now in the first frame (only the lead, the buttons and the corner lines
   arrive with the words).

## Round 2 (r2): what the inspectors said, and the dispositions

Taste inspector (16 FAIL, 10 WARN): overflow at 768 px (real: the marks' grid; fixed), small text at 390 (real: the
marks were 10 px; now 12 px), a tight line-height (real: leads now 1.4), an emoji-looking pause glyph (real: drawn in
CSS now), an edge-text block at 390 (checked in the fold capture: the corner lines sit inside the gutter; the inspector
measured the bar's controls), a 456 px blank at 7132 px on the phone (the handoff and About's top padding: the one
designed rest). Defended as the selected direction: eyebrow labels, "01 /" numbering, tracked uppercase labels, thin
rules, three typefaces (display, reading, figures), the three-line headline (the concept stacks three words), "no
pictures" (the inspector cannot see the WebGL instrument or the four live canvases), "lopsided" sections (the empty
half is the object's room), "grey body" and "1:1 contrast" (the inspector sampled the canvas and the html ground; the
suite's computed contrasts are 9.1:1 for muted-on-green and 5.5:1 for muted-on-ivory), "font not dealt" (the sheet was
dealt for THE BLOCK this morning and is superseded by the owner's selection).

Impeccable detector (47): 42 low-contrast findings are the ivory sections' ink tokens measured against the html's
green by a static reader; in the browser the ground switches to ivory before any ink text is visible (suite section 4)
and without JavaScript the reading block paints its own ivory. Real: 10 px marks (fixed to 12 px), tight leading (fixed),
summary cells flush to their rule (padded). Numbered section labels: the concept's device, kept.

## Round 3 (r3 and the recordings): defects found by looking at the contact sheets

7. The opening's first second showed the assembled register flying apart before reassembling (the parts started at
   their assembled positions and travelled out to their approach distances): the instrument now starts with the
   arrival offsets applied when the opening is going to play (`startOut`). Fixed; opening-fresh-sheet.jpg.
8. Phone: the register overlapped the list in Selected work, the controls in the system chapter and the footer at
   Contact (a fixed object on a one-column page). Decision: it sits small above the list, at 48% in the system chapter,
   and leaves at the handoff on phones (a deliberate exit; the ivory sections have no room beside the words).
   phone-walk-sheet.jpg.
9. Phone: the chapter's primary button fell below the fold at 390x844, 360x800 and 390x700: the object room shrank to
   30 svh (24 svh on short phones, where the lead is hidden), the title and lead tightened, the hour label made
   visually hidden. Verified on all four chapters at the three sizes.
10. Tablet 768: the four marks overflowed the page by 13 px; now two columns under 1100 px.
11. Lighthouse mobile reported TBT 3,020 ms on the home; traced to software GL in its headless Chrome. The real
    throttled JavaScript cost is about 250 ms (docs/PERFORMANCE.md). Phones now run the lite quality with smaller
    textures anyway.

## Round 4 (2026-10-26 audit, review candidate 9ecf79b): the owner's findings, reproduced and corrected

The findings were treated as defects to verify (docs/DEFECTS.md D-01 to D-10), not as claims to defend.

12. The posters carried the lab's controls on an opaque ground (D-01): reproduced by decoding the webp; the lab's hidden
    attribute had been overridden by its own display rule and the ground was painted by the html element. Corrected at
    the source (the lab's poster mode), in the tool (export refused unless clean, pixels checked) and in the suite
    (every poster and still decoded and checked). Anchored description of the result: a transparent ground, the object
    with its contact shadow, no control strip, no corner artefact.
13. The archive was a thumbnail wall (D-02): replaced by an editorial index of rows (number, title as the link, kind,
    tools, year and status). The dialog preview, search, clause queries, tabs, empty state, reset, deep links and the
    old-address forwards are unchanged. The thumbnail assertions were replaced, not weakened (the reason is in the
    ledger).
14. Case pages without WebGL left the hero's right half empty (D-03): every page now carries a transparent still of
    its own arrangement, rendered by the same clean-export workflow, visible until the first frame and whenever
    WebGL, the module or JavaScript is missing; verified on four page types under seven conditions (fallbacks/).
15. The sound control changed before audio existed (D-04): the control now reports "on" only when the context runs,
    says when audio is unavailable, stores no preference on failure, and never resumes while paused; the suite stubs a
    failing constructor and a refused resume and dispatches visibility changes while paused.
16. Gate statuses were overstated (D-05): the matrix uses VERIFIED PASS, FAIL, PARTIAL, NOT TESTED, BLOCKED and NOT
    APPLICABLE, with code inspection recorded apart from runtime; the progress summary follows the detailed rows.
17. Mobile LCP and the compile frame (D-06, D-07): the display font instanced to its roles and subset (131 to 40 KB),
    the Geist preload dropped, the module fetched at low priority, the textures prepared in yielded tasks, the shaders
    compiled once before the first frame, the case still loaded eagerly. The before and after figures are in
    docs/PERFORMANCE.md; where a target is still missed it is recorded as FAIL against that target.
18. Phones hid the chapter lead and secondary buttons at tight heights (responsive audit): nothing is hidden now; on
    short phones the chapter is unpinned so every line and button is reached by scrolling, and the register leaves
    after the hero so the fixed object never crosses the words.
19. The previous review archive referenced evidence outside itself (D-09): tools/package.sh bundles the site at the
    tested commit, the evidence folder, the scripts (tests/evidence), conditions, a manifest and checksums, and diffs
    the packaged site against the commit.

## The website-playbook rubric (graded on r3 and the recordings)

| Criterion | Intended outcome | Implementation decision | Evidence inspected | Status | Remaining correction |
|---|---|---|---|---|---|
| Point of view | an engineered instrument that is the body of work, in every section | one object, six arrangements, the atelier's two grounds, the engraved words on every case page | r3 desktop and phone stops, film strips | Strong | |
| Typography | a heavy condensed statement, a plain reading face, figures in mono | Bricolage condensed 800 / Geist / JetBrains Mono, vendored | r3, the long-title case page | Strong | 12 sizes on the home (the inspector wants five); the scale is deliberate but could be pruned |
| Colour | racing green, ivory, champagne with roles | tokens with measured contrast; champagne darkened as text on ivory | suite contrasts, build check | Strong | |
| Hierarchy | statement, object, one line, one figure, one action per screen | the chapter template | r3 chapters, phone | Strong | |
| Imagery | the instrument and the projects' own interfaces | the WebGL object plus four live canvases and 223 covers | r3, case pages | Strong | no footage (none honest exists) |
| Motion | assembly, transformations, a handoff, rests | the opening, the chapter blends, the ground switch, pause, reduced motion | recordings/final, pace.json | Strong | the first rendered frame is one long task under the poster |
| Mobile | a composed phone: object above, words below | the 44 svh room, one row of marks, the bar in two rows | r3/m-*, phone-walk.webm | Mixed | viewport emulation only; no real device |
| Invisible quality | measured speed, access, resilience | Lighthouse, the suite, context loss, no-WebGL, no-JS | docs/PERFORMANCE.md, gl-loss.json | Strong | no VoiceOver pass; INP unmeasured |

## The directive's weighting (target 90/100, no category under 80% of its points)

| Category | Points | Score | Visible behaviour the score cites |
|---|---|---|---|
| Cinematic opening and continuity | 20 | 17 | the parts arrive on axes and lock (click), unlock into the hero, the same object is handed to chapter 1 and transforms four times, rests on ivory; measured 3.1 s; Skip and Replay verified; the first WebGL frame is a long task under the poster (opening-fresh-sheet.jpg) |
| Instrument and art direction | 20 | 17 | 32 bevelled parts in brushed brass, lacquer and marble under an authored environment; the engraving reads; the concept's composition is matched (r3/d-02-hero vs refs); the brass is a shade paler than the concept's |
| Typography and composition | 15 | 13 | the condensed statement, the protected text column, the marks; the size scale is wide |
| Project storytelling and page consistency | 15 | 13 | four chapters with their own arrangements, figures and definitions; 223 pages on one template with summaries; the thin pages stay honest |
| Interaction and usability | 10 | 9 | hour input, test counter, arrangement buttons, separate slider, turn buttons and keys, drag, pause, sound; Back restores scroll and focus |
| Mobile and accessibility | 10 | 8 | composed phone screens, 44 px targets, one h1, landmarks, skip link, reduced motion, no-JS; no real phone, no screen-reader pass |
| Performance and resilience | 10 | 9 | see docs/PERFORMANCE.md; context loss recovered; no WebGL, poster missing, module failing all handled |
| Total | 100 | 86 | below the 90 target: the remaining points are the real-phone measurement, the screen-reader pass, the paler brass and the opening's compile frame |

Audio: separate checklist in docs/AUDIO.md; AUDITORY REVIEW NOT PERFORMED.

## Critique-and-revision cycle

One full cycle happened between r1 and r2 (six defects above), and a second between r2 and r3 (the inspector's real
findings, the View Transition opt-in that the first Chrome check showed missing, the Back-during-opening replay, the
tablet overflow). Changed behaviour was re-tested by the suite and by hand in Chrome.
