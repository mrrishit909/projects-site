# TrustLedger — synthetic data generator specification (P07-WORK-03)

* Seed 20261026; 12 weeks of rule runs 2026-07-13 .. 2026-10-04 (daily runs), `as_of` 2026-10-05T00:00:00Z; 40
  datasets across 6 source systems with 420 fields, 18 owners (3 inactive), 30 published metric definitions with 45
  versions and 15 definition changes, 60 quality rules (completeness, validity, uniqueness, relationship, timeliness)
  with versions and two weight versions (change on 2026-09-01), about 4,500 rule runs, about 600 issues with triage,
  claimed closes and verified resolutions, lineage with 80 declared and 70 observed edges (12 undeclared observed, 10
  inferred), 2,000 synthetic customer records across 3 systems with 400 match candidates, 220 reviewed merges and 15
  reversals; synthetic truth for match precision held only in the fixture/manifest.
* Designed relationships: one dataset with a near-perfect weighted score and an open critical key failure; the
  inactive owners leave 5 datasets uncovered; the weight change on 2026-09-01 moves scores without any rule change;
  issues owned by one team resolve twice as fast; the oldest open issues are all claimed-not-verified.
* Injected defects (manifest + replay events, one per P07-TEST-01..12): critical failure under a high score, a
  disabled rule's vanished history, a shared name-and-address pair, silently excluded null foreign keys, a weight
  change without a version, an irreversible merge, an inactive owner counted as covered, inferred lineage shown as
  observed, an issue closed without a rerun, a duplicate pair stored both ways, a definition rewritten in place, a
  denominator change between compared runs.
* Output under 5 MB: rule runs and customer records are the volume drivers; let the cap win and disclose counts.
