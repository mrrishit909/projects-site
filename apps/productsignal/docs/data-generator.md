# ProductSignal — synthetic data generator specification (P06-WORK-03)

* Seed 20261026; 26 weeks 2026-04-06 .. 2026-10-04 UTC, `as_of` 2026-10-05T00:00:00Z; 600 accounts (plans
  free/team/business; segments smb/mid/enterprise; three IANA timezones; 2 % internal), about 1,800 users (1 % bots),
  anonymous visitors with identity links (rule version `v1`, about 70 % of signups linked from an anonymous visit),
  sessions and events (`visit`, `signup`, `onboarding_step_1..3`, `activated`, `feature_used`, `product_error`) with
  `received_at` delays (2 % delayed over 24 h, 1 % duplicates re-sent under new event ids), subscriptions for about
  35 % of accounts (USD).
* One onboarding experiment with two versions: v1 (allocation 50/50, planned_end 2026-08-02, frozen plan) with
  about 400 assigned accounts, true activation effect +8 percentage points, exposure rate about 85 %; v2 (a
  re-plan after v1, allocation 60/40) with about 150 accounts and a designed sample ratio mismatch. Analysis runs:
  three interim runs and one at planned_end for v1.
* Designed relationships: the treatment lifts activation but not week-4 retention; the business segment activates
  faster; guardrail error rate is equal across variants; revenue per assigned account is noisy and inconclusive.
* Injected defects (manifest + replay events, one per P06-TEST-01..12): user-level analysis of an account-randomised
  experiment, a treatment-dependent exclusion, interim peeking presented as final, an immature cohort, duplicate
  activation events, a late event that changes a funnel, an identity link applied backward, an ignored sample ratio
  mismatch, cherry-picked segments, zero control conversions, exposure before assignment, retention mixing exact-day
  and rolling definitions.
* Output under 5 MB: events are the volume driver; keep one row per event and let the cap win over the counts above
  (disclose the realised counts).
