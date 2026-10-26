# Precision Atelier: progress file (durable; resume from here)

Directive v1: ~/Downloads/Precision_Atelier_Claude_Code_Master_Build_Prompt.md; directive v2 (specification, 2026-10-25):
~/Downloads/Precision_Atelier_Build_Directive_v2.md with its acceptance matrix and revision notes.
Visual target: ~/projects-site-evidence/atelier-2026-10-25/refs/precision-atelier-concept.png.
Evidence folder: ~/projects-site-evidence/atelier-2026-10-25/ (scripts in tests/evidence/, output via $EVIDENCE_OUT).
Repository: ~/projects-site, remote `private` (mrrishit909/projects-site), branch `unified-portfolio`. Never push `origin`.

## State (kept distinct)

- Specification revised: yes (v2, 2026-10-25).
- Prototype implemented: yes (f48d7ca, 2026-10-25).
- Review candidate corrected: yes, commit **9ecf79b** (2026-10-26), after the owner's audit of f48d7ca/2969d25
  (docs/DEFECTS.md D-01 to D-11).
- Representative experience accepted by the owner: **NO, PENDING** (gate D). Nothing here is accepted.
- Full site implemented: yes, provisionally, under the candidate (every portfolio-owned page on the shared system).
- Verification completed on the candidate: the suite (113 checks), fallbacks (84 captures), responsive (25 captures
  and two keyboard walks), throttled start-up, Lighthouse, pacing, context loss, lifecycle (three passes) and 16
  recordings with contact sheets all ran on 9ecf79b. Statuses per check: docs/EVIDENCE.md.
- Deployment: private branch only; the public site is unchanged.

## What still fails, is partial, untested or blocked (from docs/EVIDENCE.md)

- FAIL: mobile Lighthouse LCP on three of four pages (home 2.6, archive 2.6, long-title case 3.6 s against 2.5;
  the case page passes at 2.4). Improved from 3.0 to 4.1 s; next actions in docs/PERFORMANCE.md.
- PARTIAL: mobile composition and every phone figure (viewport emulation; no physical device); the route transition's
  interactive Chrome check was done on 2969d25, not repeated on 9ecf79b (the suite and lifecycle cover Back, scroll
  and focus); the lifecycle heap is single samples, not a leak verdict; the manual page review is a sample of four
  page types plus the flagships.
- NOT TESTED: the instrument package's front, side and three-quarter views and protected-region drawings (v2 item).
- BLOCKED: a screen-reader walkthrough (no tooling); an auditory review of the four cues (AUDITORY REVIEW NOT
  PERFORMED; sound ships off by default).
- OPEN defect D-11 (minor): on phones the fixed register crosses the words for a moment in the two unpinned sections.

## Decisions (this pass)

1. Posters are exported only from the lab's poster mode and are pixel-checked; the suite re-checks them.
2. The archive is an editorial index; thumbnails and their tool are gone.
3. Every case hero carries a still of its own arrangement as the fallback and the pre-render state.
4. Audio: Tier A as built (synthesised cues, off by default) with honest failure handling; the v2 default is Tier S,
   so the owner's tier decision stands open (remove the toggle, or keep it and perform a listening review).
5. The display font is an instanced subset (weight 600 to 800, width 75 to 85, Latin), 40 KB.
6. Phones hide nothing; short phones unpin the chapters and the register leaves after the hero.

## Exact next actions

1. The owner opens the preview (`python3 -m http.server 8800` in ~/projects-site, http://127.0.0.1:8800/) and the
   review package, and gives the gate D decision.
2. If accepted: measure on a physical phone, decide the audio tier, close D-11, and consider inlining the home's
   first-paint CSS and preloading the case still for the mobile LCP target.
3. If rejected: corrections through the shared system, then gate D again.
