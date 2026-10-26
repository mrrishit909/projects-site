# Precision Atelier: progress file (durable; resume from here)

Directive v1: ~/Downloads/Precision_Atelier_Claude_Code_Master_Build_Prompt.md; directive v2 (specification, 2026-10-25):
~/Downloads/Precision_Atelier_Build_Directive_v2.md with its acceptance matrix and revision notes; the refinement
directive (2026-10-26, pasted: "still generic and insufficiently cinematic") is answered by design/journey.md.
Visual target: ~/projects-site-evidence/atelier-2026-10-25/refs/precision-atelier-concept.png.
Evidence folder: ~/projects-site-evidence/atelier-2026-10-25/ (scripts in tests/evidence/, output via $EVIDENCE_OUT).
Repository: ~/projects-site, remote `private` (mrrishit909/projects-site), branch `unified-portfolio`. Never push `origin`.

## State (kept distinct)

- Specification revised: yes (v2, 2026-10-25).
- Prototype implemented: yes (f48d7ca, 2026-10-25).
- Review candidate corrected: yes, 9ecf79b (2026-10-26) after the owner's audit (D-01 to D-11).
- Refinement candidate built: yes, **the commit named below** (2026-10-26): the instrument rebuilt (41 parts, five
  assemblies, the dial), the authored opening, the representative journey recomposed (hero, Selected work close-up,
  chapter 1 wide with the hour event, the case page holding the arrangement, Back). Ledger D-12 to D-18.
- Representative experience accepted by the owner: **NO, PENDING** (gate D). Nothing here is accepted.
- Broad rollout: **HELD**. Chapters 2 to 4, the instrument chapter, about, archive and contact keep the 9ecf79b
  composition (they still render the rebuilt object through the shared states). The plan for them is in
  design/journey.md section 4.
- Verification completed on the refinement candidate: the suite (113 checks), journey frames before and after,
  the lab views, 18 recordings with contact sheets, pacing, throttled start-up, Lighthouse, fallbacks (84 captures),
  responsive (27 entries), context loss (five cycles), lifecycle (three passes), a real-Chrome check of the
  transition. Statuses per check: docs/EVIDENCE.md; figures: docs/PERFORMANCE.md round 5; the critical review:
  docs/REVIEW.md round 5.
- Deployment: private branch only; the public site is unchanged.

## What still fails, is partial, untested or blocked

- FAIL: mobile Lighthouse LCP on three of four pages (home 2.6, archive 2.6, long-title case 3.6 s against 2.5;
  the case page 2.4), unchanged by this pass; the opening's one compile frame on desktop (133 ms against 50 ms,
  before the first motion); home mobile TBT 230 ms under Lighthouse's software GL.
- PARTIAL: every phone figure is viewport emulation (no physical device); the lifecycle heap is single samples; the
  cross-document transition's intermediate frames were not captured.
- NOT TESTED: the instrument package's protected-region drawings.
- BLOCKED: a screen-reader walkthrough (no tooling); the auditory review (AUDITORY REVIEW NOT PERFORMED; sound off
  by default; the click now sits at the seating, the texture at the unlocking, unheard).
- OPEN D-11 (minor): on phones the fixed register crosses the words briefly in the unpinned sections (Selected work,
  the instrument chapter). After Back the hour input returns to 8 a.m. in Playwright (bfcache kept it in Chrome).

## Decisions (this pass)

1. The instrument is five assemblies with a recognisable mechanism (the dial); the exploded composition is authored
   per assembly, not evenly spaced.
2. The opening is a close-up that pulls back, with one cause (the dial aligns, the core seats) propagating into the
   unlocking; 3.0 s; Skip and Replay kept; reduced motion keeps the still composition.
3. Only the representative journey was recomposed; the rest is held for acceptance (directive section 12).
4. Chapter actions are View project and Code; the demo link lives on the case page's Evidence field.
5. Chapter kickers ("01 / Business intelligence") and the stage notes were removed; the dbt counter stays until
   chapter 2 is recomposed.

## Exact next actions

1. The owner opens the preview (`python3 -m http.server 8800` in ~/projects-site, http://127.0.0.1:8800/) and the
   recordings `recordings/refine/journey-desktop.webm` and `journey-phone.webm`, and gives the gate D decision on the
   journey.
2. If accepted: apply design/journey.md section 4 to chapters 2 to 4 (the pipeline across the width with the tests as
   pins, the forecast with the chart large, the passage close-up), the instrument chapter (assembly selection with a
   one-line purpose), about (the engraved plate as the ground), archive (the register lying flat); then the sound
   timing review, the physical phone, D-11, the mobile LCP actions.
3. If rejected: corrections through the shared system on the journey only, then gate D again.
