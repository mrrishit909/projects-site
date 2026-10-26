# SupplyScope — static site brief (Mode B)

Visual direction (P03-GOAL-03): a **warehouse planning atlas**. Graphite `#2a2d31` ground for
the header band, pale grey paper `#eef0f2` for reading, safety orange `#f26a1b` (text on paper
`#b84d0e`), rule `#c8ccd2`, ink `#15171a`. Type: condensed grotesque for labels, tabular
numerals. Principal representation: **inventory trajectories** (stock on hand, position, reorder
point and target over time, with receipts and stockouts marked) and the **reorder workbench**
table. Must not resemble Revenue Atlas, Onboard Studio or the portfolio.

Routes under `/projects-site/labs/supplyscope/`: `/` landing; `/overview/` planning overview
(entry); `/skus/` SKU detail with trajectory (entry); `/locations/`; `/suppliers/`;
`/forecast/` evaluation (entry: baselines vs model on rolling folds); `/reorder/` workbench
(entry: draft orders with the golden arithmetic visible); `/simulator/`; `/capital/`;
`/draft/` purchase draft export; `/case-study/` (entry). Same routing, manifest, honesty,
motion and Playwright evidence rules as the other two apps. The TypeScript domain mirrors the
Python ledger reconstruction, replenishment arithmetic and WAPE, checked against the golden
fixture (position 60 → order 72; position 80 → 0).
