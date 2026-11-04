# ATELIER X: agent task graph and status

Written 2026-11-03 21:50 EST. The owner asked to "run everything at once till 10:00pm today", so the first window is 21:44 to 22:00 EST. Everything below the first section is the standing plan for the next windows.

## Right now (updated 2026-11-03, after the 22:00 window)

- Phases 0 to 5 documents: done (one squashed commit, private repo names removed).
- Phase 7 proof of concept 2 (THE SLAB, intro A): `motion/slab-lab.html`, a lab page only (not wired into build.py or the home). Intro 3.2 s with Skip/Esc/scroll/touch skip, reduced-motion and `#nointro` skip, crane up the face to one real aperture with the Florida drawing painted live from `motion/scenes/florida-flight-delays.js`, red field chapter, push into the aperture. Evidence (real GPU Chrome, DPR 2, 1440x900 and 390x844, intro frames t=0.3..3.4): `~/projects-site-evidence/atelier-x-2026-11-03/slab-proof/`. No console errors.
- Known proof defects: faint horizontal shading seams where the slab blocks meet (one-mesh slab needs BufferGeometryUtils, not in the vendored subset); the push-in end state (p 0.92) is the screen only; no poster/LCP work, no pacing measurement yet.
- 2026-11-04: all five concepts now have proofs at the same depth (intro + Florida chapter, desktop + phone, GPU Chrome DPR 2, no console errors): motion/foundry-lab, slab-lab, groundtruth-lab, reel-lab, array-lab; comparison page motion/concepts.html; contact sheet ~/projects-site-evidence/atelier-x-2026-11-03/contact-sheet.png. Owner-supplied sources researched (atlas section "Owner-supplied sources"); motionsites prompts are paid and not used.
- WAITING ON THE OWNER: verdict on the slab proof and the pick among the five concepts. Do not start Phase 6 (foundation) or prototype intro C before that.

## Decisions only the owner can make (none block the current window)

1. Pick the creative direction (or hybrid) from `docs/creative-direction.md` once it exists. Reviewer scores have not predicted this owner's verdict before; the pick is the owner's.
2. Approve the architecture recommendation in `docs/architecture.md` before any code.
3. Approve which private repositories, if any, may be described publicly (default: none).
4. Approve any production cutover of mrrishit909.github.io/projects/ (default: previews only).
5. Approve `agent-browser install` (downloads Chrome for Testing) if the existing Chrome via `--executable-path` proves insufficient.

## Dependency graph

```
Phase 0 env audit ─┬─► Phase 1 skills ──────────────┐
                   ├─► Phase 2 research (atlas) ────┼─► Phase 4 concepts ─► OWNER PICK ─► Phase 5 architecture plan ─► Phase 6 foundation
                   └─► Phase 3 inventory ───────────┘        ▲                                   ▲
                                                             │                                   │
                              intro storyboards (E) ─────────┘             architecture proposal (F, PROPOSED tonight)
Phase 6 ─► Phase 7 intro prototypes (2) ─► browser evaluation ─► Phase 8 portfolio ─► Phase 10 refinement ─► Phase 11 QA ─► Phase 12 preview deploy ─► Phase 13 adversarial review ─► Phase 14 delivery
Phase 3 inventory + Phase 5 shared packages ─► Phase 9 microsites (parallel, one agent per site, own branch/worktree) ─► same 10 to 13 gates
```

Parallel-safe: research and inventory; concept exploration and architecture proposal; later, independent microsites; QA across sites.
Serial by necessity: concept pick before design tokens; inventory before case-study content; shared packages before microsites; production evidence before acceptance.

## Role map (directive part 15) and ownership boundaries

| Role | Owner | Writes to | Reads from |
|---|---|---|---|
| A Program Orchestrator | this session | `docs/agent-task-graph.md`, `docs/final-acceptance.md`, memory | everything |
| B Repository Investigator | subagent | `docs/verified-project-inventory.md`, `data/atelier-inventory.json` | GitHub API |
| C Design Researcher | subagent | `docs/design-reference-atlas.md`, later `docs/reference-to-implementation-map.md` | the six platforms |
| D Creative Director | subagent | `docs/creative-direction.md`, later `docs/design-system.md` | taste history, atlas |
| E Motion Director | subagent | `docs/intro-storyboards.md`, `docs/motion-system.md` (with F) | storyboards, gsap/emil skills |
| F Frontend Architect | subagent | `docs/architecture.md`, shared packages | existing repos |
| G Interactive Graphics Engineer | subagent (Phase 7+) | intro and scene modules | storyboards |
| H Content Strategist | subagent (Phase 8) | case-study copy, positioning | inventory only (facts) |
| I Accessibility Engineer | subagent (Phase 10+) | `docs/accessibility-report.md` | built pages |
| J Performance Engineer | subagent (Phase 10+) | `docs/performance-report.md` | production builds |
| K QA Engineer | subagent (Phase 11) | tests, evidence harness output | production builds |
| L Independent Auditor | Codex + a fresh subagent that did not build the feature | `docs/quality-audit.md` | everything, adversarially |
| M Security and Privacy Reviewer | subagent (Phase 11) | `docs/security-review.md` | deps, build output |
| N Release Engineer | subagent (Phase 12) | workflows, `docs/deployment-report.md` | CI |
| O Marketing and Launch Strategist | subagent (Phase 14) | launch drafts (never published) | final site |

Rules: one writer per file; agents use branches or worktrees; concurrency capped at 5 agents on this machine; no agent is launched whose output is not on the dependency graph.

## Independent quality control ownership

- Build agents never grade their own work. Every visual claim needs a screenshot read by someone other than the builder (this session or a fresh auditor).
- Codex is the second model for architecture and audits; it is asked to find faults, not to agree.
- The ten audit layers of directive part 16 map to `docs/quality-audit.md`; findings carry severity, location, repro, evidence, expected, actual, correction, re-verification.

## Background: what already exists (so nobody rebuilds it blind)

- `~/projects-site` (branch `unified-portfolio` on the private remote): seven earlier homepage directions, 220+ generated case pages, Playwright check suite, evidence harness pattern; see `CLAUDE.md` there.
- `~/projects-next`: Next.js rebuild, designs rejected, local only.
- `~/projects-site-evidence/*`: screenshots and recordings of earlier rounds.
