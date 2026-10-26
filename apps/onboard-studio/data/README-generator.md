# Onboard Studio synthetic data generator

`data/generate.py` (stdlib only, specification: `docs/data-generator.md`) writes the published synthetic snapshot. One
`random.Random(seed)` stream and integer minutes since 2025-04-01T00:00Z make it deterministic: the same seed gives
byte-identical entity files and the same `dataset_hash`.

```sh
python data/generate.py --seed 20261026 --out web/public/data     # about 1 s, 4.9 MB
python data/generate.py --profile golden-shape-check               # field names vs tests/fixtures/golden
```

Options: `--data-dir` (where `injection-manifest.json` and `injection-events.json` go, default `data/`).

## Output

| File | Content |
|---|---|
| `web/public/data/<entity>.json` | `{"entity", "dataset_version", "rows"}` for the 13 golden entities plus `workflow_requirements` (one row per version: `{workflow_version_id, required_document_types}`, the D-05 block as rows). Row fields equal `tests/fixtures/golden/inputs.json`; extras: `kind` on every `calendar_intervals` row (D-06) and `pause_requested: true` on the 3 wrong-reason waits. |
| `web/public/data/manifest.json` | `dataset_version` (`os-<seed>-20261026`), `dataset_hash`, `generated_at` (real UTC; not hashed), `contract_version`, `generator` (name, seed, all parameters), `row_counts`, `designed_relationships`, `injection_manifest`. |
| `data/injection-manifest.json` (+ copy in `web/public/data/`) | The twelve injected defects `INJ-01..12` as `{id, test, entity, location, record_ids, description, expected_handling}` plus the designed relationships. |
| `data/injection-events.json` | Command inputs (with `headers`, `expected_error_code` or `expected_status`, `expected_handling`) for the defects that cannot live in the entity files. |

`dataset_hash` = sha256 over the concatenation, in entity-name order, of
`json.dumps(rows, sort_keys=True, separators=(",", ":"))` for each entity file (14 files, `workflow_requirements`
included).

## Size

740 cases over 2025-04-01 .. 2026-09-30 (snapshot cut 2026-09-30T23:59Z; later work is open), 40 organizations
(22 smb, 12 mid_market, 6 enterprise; 4 regions `reg-north/south/east/west`; four names of 60+ characters),
3,700 step instances (5 per case), about 4,400 assignments, 2,200 document versions, 3,600 approvals, 900 waits and
12,800 events. The spec asks for ~900 cases and ~15,000 events; the 5 MB cap on the published files (the three largest
files are `case_events`, `step_instances`, `assignments`) is why the volumes sit 5-20 % under it. `CASES` in
`generate.py` is the one knob; at 820 cases the files reach 5.4 MB.

## The workflow, calendar and people

* Calendar `cal-001`: Monday-Friday 09:00-17:00 UTC plus six whole-day `holiday` intervals (four weekdays and
  2026-02-14, 2026-07-04, both Saturdays: they subtract nothing). SLA 480 business minutes, pause policy
  `customer_info_requested`, `external_verification`.
* `wfv-001` (v1, published 2025-03-10): collect_documents, verify_identity, compliance_review, approve_account,
  activate_account in sequence. `wfv-002` (v2, published 2025-10-01; 60 % of later cases): verify_identity is gone
  (one handoff fewer) and collect_address_proof runs in parallel with collect_documents. Required documents: v1
  identity_proof + business_registration; v2 adds address_proof. approval_form is an optional extra at approve_account.
* Reviewers (role by id): rev-001..003 ops, rev-004..006 reviewer, rev-007..008 compliance. Assignees are `ops-*`,
  `cmp-*`, `acc-*`, never a `rev-*` (except the injected self-approvals). A step is ready exactly when the last
  mandatory prerequisite is approved (`ready_at` = that `approved_at`); a rejected document makes the step version 2
  and the single approval row carries that version implicitly; a reassignment closes the prior assignment and opens the next.
* Customer waits start at a working minute, never overlap within a case, and are placed in the customer-facing steps;
  a rejected document opens a wait for the resubmission. About 3 % of cases stall (an open wait or a decision that never
  comes) and, with the last days, form the open backlog (about 5 % of cases).

## Designed relationships (synthetic; measured by `group_metrics`, see `tests/test_generator.py`)

* v2 vs v1: active elapsed 5.9 h vs 9.2 h (-36 %), handoffs per case 0.88 vs 1.09 (-19 %).
* `enterprise` rework rate 0.29 vs 0.17 / 0.14 (identity_proof rejection probability 0.20 vs 0.11).
* `reg-north` paused time about 59 h vs 26-31 h (more waits per case, each 1.4x longer).
* Bottleneck at `approve_account` for `rev-004` (40 % of reviews, queue x3.6, review x3.4): mean decision latency 7.7 h
  vs 2-3 h; the step's ready-to-started wait is the longest of all steps.

## Where each defect lives

In the entity files (the pipeline must reject or flag them): INJ-01 two completed cases without an accepted required
document (rejected, `MISSING_REQUIRED_DOCUMENT`); INJ-02 two decision pairs (the later approval is rejected,
`DECISION_CONFLICT`, only that row); INJ-03 three pauses outside the working intervals (a Saturday, a Sunday, a weekday
holiday; accepted, 0 business hours, flagged); INJ-08 the two weekend holidays; INJ-09 three customer waits labelled
`internal_processing` / `document_review` / `manual_check` with `pause_requested: true` (the case and its rows are
rejected, `PAUSE_REASON_NOT_CONFIGURED`); INJ-10 two self-approvals (rejected, `SELF_APPROVAL`).

In `data/injection-events.json` only (replay through the API; `tests/test_generator.py` does it): INJ-02 the same
conflict through `approve-step` on in-review steps of open cases; INJ-04 an edit of the published `wfv-001`; INJ-05 a draft
`wfv-003` with a dependency cycle; INJ-06 two resubmissions that would overwrite an accepted document (plus a direct
UPDATE); INJ-07 two reassignments that drop the prior interval (`reassign-work` is a 501 extension command); INJ-11 a
reopen of a completed case; INJ-12 a migration that drops an accepted document (501 extension command). They are kept
out of the entity files because the seed would reject the cycle, collide on the overwrite and the conflicts, and the
triggers forbid the rest.

`generate.py` imports nothing from `domain/`; `tests/test_generator.py` checks it against the pipeline and the database.
