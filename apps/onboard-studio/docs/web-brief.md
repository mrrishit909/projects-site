# Onboard Studio — static site brief (Mode B)

Visual direction (P02-GOAL-03): a **tactile process studio**. Paper ground `#f7f3ec`, indigo
paths `#2b3a8f` (text on paper `#1f2a66`), amber exceptions `#d98b1a`, rule `#d9d2c3`, ink
`#1b1d24`. Type: a geometric sans for labels (system stack), tabular numerals. Timeline first:
the principal representation is the **case timeline** (events, assignments, waiting intervals
and document versions on one business-hours axis with calendar gaps shaded) and the
**workflow canvas** (an ordered, accessible list of steps with dependency arrows drawn in SVG).
Must not resemble Revenue Atlas or the portfolio's Precision Atelier.

Routes under the injected base `/projects-site/labs/onboard-studio/`: `/` landing;
`/intake/` case intake (progressive form, browser-memory simulation); `/queue/` work queue;
`/cases/` case timeline (entry); `/workflow/` canvas (entry); `/documents/` document review;
`/sla/` SLA explorer (business vs calendar time, entry); `/bottlenecks/`; `/versions/`
comparison; `/simulation/`; `/case-study/` (entry). Same routing mechanism (per-route
index.html copies), data manifest, honesty labels, reduced motion, keyboard rules and
Playwright evidence at 360/768/1280/1920 as Revenue Atlas (`apps/revenue-atlas/docs/web-brief.md`).
The TypeScript domain mirrors the Python calendar arithmetic and is checked against the golden
fixture (calendar 66 h, business 2 h, active 1 h / 2 h).
