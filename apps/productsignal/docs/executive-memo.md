# Executive memo: should the onboarding change ship, stop, or get more investigation? (P06-ART-07)

**Synthetic data throughout:** one onboarding experiment in a generated world (seed 20261026, dataset `ps-20261026-20261026`, generator hash `12672f9c39402517083bbbbe9164cbefe3435361dff086eb0d9e16e60f9b66f8`, code revision `fdf911a`, as-of 2026-10-05T00:00:00Z). Nothing here is a claim about a real product or a real customer, and no benefit of shipping is claimed. Three kinds of statement are kept apart: **OBSERVED** (what this log shows, reconciled to the independent SQL reference and the Python domain: `sql-analysis.md`), **SIMULATED / constructed** (what the generator built in: a designed +8.00 point treatment effect, a designed sample-ratio mismatch in v2, an injected instrumentation gap) and **HYPOTHETICAL** (what a real team might gain: not claimed).
How to read it without installing anything: the decision first, then the evidence table, the options, the uncertainty and the limits; every figure is a decimal fraction (six places) or a count over a named population, lifts are percentage points (pp), and each is quoted from `sql-analysis.md`.

## Decision
* **v1 (the first onboarding experiment, 400 accounts, final run an-004 at planned_end 2026-08-02): ship, as a staged rollout, with the weakness of the evidence stated.** The pre-specified rule is met: a final run, a plan frozen before any outcome was read, a valid plan hash, a sample ratio that is OK and an interval that excludes zero. It is **conclusive by a hair**: the Newcombe 95% interval is **+0.000812 to +0.186863** (+0.08 to +18.69 pp), so zero is barely outside it. The recommendation is "the change raises activation, size uncertain", not "the change raises activation by 9.5 points".
* **v2 (the re-plan, 154 accounts): record `inconclusive`.** Its sample ratio is a MISMATCH (62 control and 92 treatment accounts against a 0.60 / 0.40 plan, chi-square 25.004329, p below 0.000001); the rules block both `ship` and `stop`, and the site shows no v2 lift. v2 can neither confirm nor contradict v1.
* **The published v1 lift sits inside an injected instrumentation gap** (INJ-10): published **+9.50 pp**, drawn **+11.50 pp** (a constructed figure: the generator knows 4 activations the gap suppressed), **+9.96 pp excluding the 11 gap accounts** (interval +0.35 to +19.32). The gap, if anything, understates the lift; it is disclosed here, in the manifest and on the result page beside "conclusive by a hair", and is not corrected (the domain cannot see it).
* A decision is evidence, not a release: recording it writes no product state (P06-FLOW-10); the product owner ships.

## Evidence (OBSERVED, per run and arm)
Intention to treat on the mature assigned accounts (an account is mature when its seven days are complete); the unit is the account; the run sees only what existed by its cutoff (D-08).

| Run (cutoff) | Status | Assigned (control / treatment) | Mature | Activated | Conversion | Lift (pp) | Newcombe 95% interval | Sample ratio |
|---|---|---|---|---|---|---|---|---|
| an-001 (2026-05-18) | interim | 77 / 78 | 65 / 64 | 18 / 25 | 0.276923 / 0.390625 | +11.37 | -0.048312 to +0.268068 | OK (0.006452) |
| an-002 (2026-06-15) | interim | 127 / 126 | 114 / 115 | 34 / 48 | 0.298246 / 0.417391 | +11.91 | -0.004952 to +0.238174 | OK (0.003953) |
| an-003 (2026-07-13) | interim | 177 / 176 | 164 / 164 | 53 / 68 | 0.323171 / 0.414634 | +9.15 | -0.012863 to +0.193048 | OK (0.002833) |
| **an-004 (2026-08-02)** | **final** | **200 / 200** | **200 / 200** | **63 / 82** | **0.315000 / 0.410000** | **+9.50** | **+0.000812 to +0.186863** | **OK (0.000000)** |
| v2 an-005 (2026-10-04) | final | 62 / 92 | outcomes withheld | | | withheld | withheld | **MISMATCH (25.004329)** |

* **Relative lift 0.301587** at the final run; exposure 175 of 200 (0.875000) in control and 174 of 200 (0.870000) in treatment, reported beside intention to treat (never a denominator).
* **Three looks before the final one all showed 9 to 12 points and none excluded zero**; the second was within 0.005 of doing so. Interim runs cannot support a ship (P06-TEST-03): the recorded answer is the pre-specified final run only. Late events changed none of the v1 activation counts at any run (investigation 08).
* **The guardrail does not object** (the prespecified `product_error_rate`, 7-day window): 31 of 200 (0.155000) against 30 of 200 (0.150000), -0.50 pp, interval -0.076005 to +0.066018, verdict OK. "No harm shown" is not "no harm": the interval allows up to about 6.6 points more errors under treatment.
* **Nothing else moves enough to decide on:** week-4 retention 71 of 200 (0.355000) against 62 of 200 (0.310000), -4.50 pp, interval -0.136053 to +0.047102 (includes zero: the treatment lifts activation but there is no sign it lifts week-4 retention); revenue per assigned account USD 97.83 against USD 130.95, difference 33.12, Welch interval -25.59 to +91.83 (includes zero; noisy by design).
* **Tracking quality is not what limits the decision:** of 12,552 event rows 124 were re-sent duplicates (dropped), 237 arrived more than 24 hours late (0.019070), 30 had an unknown identity, and 11,979 were analysed; 0.697121 of the real users are reached by an identity link. A late batch changes only a later funnel, never a published run.

## Options
| Option | What the evidence says | What it needs or risks |
|---|---|---|
| **Ship v1 (staged)** (recommended) | The pre-specified rule is met; the lift is +9.50 pp (+9.96 excluding the gap accounts, drawn +11.50); the guardrail shows no harm; v2 does not contradict it | Treat the size as uncertain (+0.08 to +18.69 pp); widen only after a follow-up read of week-4 retention and revenue, which the experiment does not show to move; keep the guardrail on |
| **Stop** | Not supported: no harm is shown and the primary outcome is positive; a stop would need a harmful guardrail or a failed rule | Would discard a lift that the rule calls conclusive; blocked for v2 by the mismatch |
| **More investigation (`inconclusive`)** | Defensible if a wrong ship is costly: the lower bound is 0.08 pp, v2 could not replicate, week-4 retention and revenue show nothing | A properly randomised replication (v2's randomiser is the defect, not the idea) and a long enough window to read week-4 retention; the cost is delay |

## Uncertainty
* **One draw.** The world was drawn once from the seed; the realised +9.50 pp is one realisation of a designed +8.00 pp effect. An interval that barely excludes zero would, on another draw, plausibly include it.
* **Four choices were made after looking at earlier drafts of the data** (disclosed in the manifest): v1's randomisation was changed from a fair coin (223 / 177, p 0.021) to permuted blocks; `product_error` was changed from per-account to 8% per session after an unrealistic guardrail gap; v2's enrolment start and the number of bounce visitors were tuned; the INJ-06 candidate window was widened. They shape the sample-ratio result of v1 and the guardrail result; they do not depend on the activation outcome, but the world is not a neutral draw.
* **The gap.** 11 of the 400 v1 accounts (5 control, 6 treatment) have no `activated` event because the instrumentation was missing before 2026-04-08; the published lift (+9.50) is below the drawn (+11.50) and the third figure (+9.96) is a sensitivity analysis that drops them from both arms. A reader who prefers the sensitivity figure still gets a conclusive interval (+0.35 to +19.32 pp).
* **Peeking.** Three interim runs were logged; the decision rests on the final run only, so the interim looks do not inflate the stated error, but they show how easily an early read would have swung (+11.91 pp with a lower bound of -0.004952).
* **Multiplicity of outcomes.** Retention and revenue were not decision rules; a favourable difference there would have been exploratory, and the ones observed include zero.

## Limitations
* Synthetic accounts and events: no real users, no real revenue, no seasonality, one product surface. The relationships were designed, so recovering them shows the pipeline works, not that a product has them.
* v1 passes the sample-ratio check by construction (permuted blocks) and v2 fails it by construction (3 of 5 accounts to treatment); neither says anything about a real randomiser.
* Segments are exploratory: the business plan activates sooner and more often (0.527778, median 9.62 hours, over accounts never assigned to the treatment) and is a correlation of the generated world, not a cause (P06-DOMAIN-05).
* The public site is a static demo; its registry and decision screens simulate their actions in browser memory and nothing ships from them. The transactional behaviour (C01 to C10) is verified separately on hosted runners against a transient PostgreSQL.
* **Excel and Power BI were not run.** The analyst workbook (`workbook.md`) was recalculated by LibreOffice headless only; the BI package (`bi-package.md`) has no `.pbix` and its DAX-like measures were not executed in any engine, only recomputed in Python from the CSV facts. This memo does not support any statement about a realised benefit or a saving.

## Recommendation
Record `ship` for v1 on run an-004 as a staged rollout, citing the guardrail review and this memo's gap caveat; read week-4 retention and revenue again before widening; record `inconclusive` for v2 and rerun it with a randomiser that follows its plan. If the cost of a wrong ship is high, choose `inconclusive` for v1 instead: the evidence supports "positive, size uncertain", and both choices are consistent with it. Claims stay consistent with the public case study (`productsignal/project.json`) and the resume bullets (`resume-bullets.md`).
