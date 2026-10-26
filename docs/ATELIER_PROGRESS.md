# Precision Atelier: progress file (durable; resume from here)

Directive: ~/Downloads/Precision_Atelier_Claude_Code_Master_Build_Prompt.md (read whole, 2026-10-25).
Visual target: ~/projects-site-evidence/atelier-2026-10-25/refs/precision-atelier-concept.png (the owner's concept image).
Evidence folder for this build: ~/projects-site-evidence/atelier-2026-10-25/
Repository: ~/projects-site, remote `private` (mrrishit909/projects-site), branch `unified-portfolio`. Never push `origin`.
Baseline commit before this build: bff4f13 (THE BLOCK). Baseline captures: evidence/baseline/.

## Current phase

All phases A to G DONE on the final build; H (delivery) in progress: committed on unified-portfolio and pushed to the
private remote (commit f48d7ca, docs commit follows). The public site is untouched.

## Verified state (facts)

- Suite: tests/portfolio-check.cjs, 106 checks, all passed on the final build (evidence/portfolio-check.txt).
- Lighthouse 12.8.2 (gzip): desktop perf 99 to 100, accessibility 100 on all four pages; mobile perf 86 to 94
  (home 89), accessibility 100. Mobile lab LCP 3.0 to 4.1 s (font swap on simulated slow 4G) is the recorded deviation.
- Frame pacing: p50 16.7 / p99 16.8 ms on every path at desktop 2x and phone 3x emulation; one compile frame in the
  opening (100 to 200 ms). Throttled 4x CPU with the GPU on: 250 ms of blocking on the home.
- Context loss x5 recovered; no-WebGL, poster missing, module delayed, Three.js failing all handled (gl-loss.json).
- Real Chrome 156: View Transition into a case study confirmed; Back restores scroll and focus; Replay, Skip, Pause.
- Recordings (14 clips with contact sheets) in evidence/recordings/final; captures r1, r2, r3; taste inspector run.
- Owner's visual verdict on the built page: NOT YET GIVEN (the real gate).

## Decisions

1. Direction: Precision Atelier (owner-selected). Taste draw conflict recorded in design/art-direction.md.
2. Modelling: procedural Three.js (docs/INSTRUMENT.md). Blender not used.
3. Type: Bricolage Grotesque condensed / Geist / JetBrains Mono, all vendored; Fontshare removed.
4. One stylesheet (atelier.css) for home, every case page, the archive, the 404; build.py templates rewritten.
5. Audio: synthesised, off by default; AUDITORY REVIEW NOT PERFORMED (docs/AUDIO.md).
6. Navigating away mid-opening counts as seen (Back never replays); the opening starts with the parts off-axis.
7. Phones: lite quality (no shadow, 320 px textures); the register leaves at the handoff (no room beside the words).
8. The Florida metric corrected to "On-time arrivals" everywhere it is written.
9. The reading block paints its own ivory; the canvas rises above it while the ground is ivory (static contrast tools
   and no-JS both see ink on ivory).

## Unresolved issues (remaining limitations)

- No real phone measured; mobile Lighthouse performance 86 to 94 against the 90 gate (lab LCP from the font swap).
- Auditory review not performed; sound ships off.
- No screen-reader (VoiceOver) walkthrough; 1024, 1920, phone landscape and 200% zoom not captured.
- The taste inspector's house rules conflict with the selected concept; defended in docs/REVIEW.md.
- The brass reads a shade paler than the concept's.
- The owner has not yet seen the built page; his verdict decides whether it goes public (owner publishes, never this
  session).

## Exact next actions

1. Owner reviews the private branch (local preview: `python3 -m http.server 8800` in ~/projects-site, open
   http://127.0.0.1:8800/). If approved, the owner merges/publishes to the public site himself.
2. If a real phone is available: measure pace and Lighthouse on it; subset Bricolage if mobile LCP matters.
3. A listening pass for the four cues; a VoiceOver walkthrough.
