# Onboard Studio — synthetic data generator specification (P02-WORK-03)

`data/generate.py` (stdlib only) writes the published snapshot deterministically.

* Default: seed 20261026, 18 months 2025-04-01 .. 2026-09-30 UTC, calendar `cal-001`
  Monday–Friday 09:00–17:00 UTC with 6 holidays (two on weekends, which subtract nothing),
  40 organizations in 3 segments and 4 regions, two workflow templates with versions v1 and v2
  (v2 removes one handoff and adds a parallel document step), ~900 cases, ~4,500 step
  instances, ~5,500 assignments, ~2,800 document versions, ~3,600 approvals, ~1,100 waiting
  intervals, ~15,000 case events; SLA 480 business minutes with pause_policy
  ["customer_info_requested", "external_verification"].
* Designed relationships (documented as synthetic): v2 cases have ~35 % lower active elapsed
  time and ~20 % fewer handoffs than v1; the `enterprise` segment has ~2x the rework rate
  (identity_proof rejections); region `reg-north` has longer customer waiting because its
  cases pause more often; a bottleneck at step "approve_account" for reviewer `rev-004`.
* Injected defects (listed in `data/injection-manifest.json`, replay-only ones in
  `data/injection-events.json`): 2 cases completed with a required document missing, 2 pairs
  of conflicting decisions on one step version, 3 pauses outside working intervals, 1
  workflow version edited after publication (as an attempted mutation event), 1 dependency
  cycle in a draft version, 2 resubmissions that would overwrite (as attempted mutation), 2
  reassignments that drop prior intervals (attempted), the weekend holidays, 3 customer
  waits labelled as work (wrong reason code), 2 self-approvals, 1 reopen after completion, 1
  migration that would drop an accepted document.
* Output: `web/public/data/<entity>.json` + `manifest.json` (dataset_version
  `os-<seed>-<yyyymmdd>`, dataset_hash over sorted entity files, generated_at, counts,
  parameters, designed relationships); total under 5 MB.
