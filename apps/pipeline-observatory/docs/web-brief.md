# Pipeline Observatory — static site brief (Mode B)

Visual direction (P08-GOAL-03): an **engineering observatory**. Dark slate `#161b22` ground, pale text `#d7dde5`,
electric cyan `#19d3f2` (text on dark `#7fe3f5`; on pale `#0b7a8c`), rule `#2b3340`, muted `#8a96a6`, alert amber
`#e8b63a` for stale and blocked states. Type: a mono for everything measured, a compact sans for reading. Principal
representations: **run evidence** (tasks, attempts, logs and quality results of one run on a timeline) and the **DAG**
(sources → models → publications with freshness drawn on the nodes, independent of job colour). Must not resemble the
other labs.

Routes under `/projects-site/labs/pipeline-observatory/`: `/` landing; `/overview/` platform overview (entry: freshness
independent of green job status; ingestion age beside it); `/dag/` dependency graph (entry); `/runs/` run detail
(entry: steps, attempts, logs, the golden batch's 10/8/1/1 and the replay); `/sources/` source contract (schema and
version comparison); `/quarantine/` quarantine desk (entry: invalid rows and retry disposition, simulated); `/gate/`
quality gate (entry: critical checks and the publication decision; a failed run never replaces the publication);
`/backfill/` backfill console (partitions, overlaps, progress); `/incidents/` incident timeline (detection, diagnosis,
verified recovery); `/benchmark/` benchmark evidence (measured hardware, size, duration from CI); `/evidence/`;
`/case-study/` (entry: delivery guarantees and failure experiments). Same routing, manifest, honesty, motion and
Playwright evidence rules as the other apps.
