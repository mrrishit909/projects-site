# ServiceFlow synthetic data generator

`data/generate.py` (stdlib only, specification: `docs/data-generator.md`) writes the published synthetic snapshot. A master
`random.Random(seed)` hands one child stream to each purpose (roster, customers, arrivals, tickets, dispatch, surveys, late
arrivals, injections), time is integer seconds from 2026-07-06T00:00:00Z, shifts are built with `zoneinfo`, and nothing
iterates a set of strings, so the same seed gives byte-identical entity files and the same `dataset_hash` (checked under
`PYTHONHASHSEED` 0, 1 and 2). The generator imports nothing from `domain/`: the queue discipline, the shift and break rules and
the metric definitions are restated from `docs/contracts.md` (D-01..D-06).

```sh
python data/generate.py --seed 20261026 --out web/public/data     # about 1.3 s, 4.84 MB (4,836,065 bytes)
python data/generate.py --profile golden-shape-check               # field names vs tests/fixtures/golden and data/seed.py COLUMNS
DATABASE_URL=postgresql://lab:lab@127.0.0.1:5432/serviceflow python -m pytest tests/test_generator.py   # also seeds Postgres (about 55 s)
```

Options: `--data-dir` (where `injection-manifest.json` and `injection-events.json` go, default `data/`).

## Output

| File | Content |
|---|---|
| `web/public/data/<entity>.json` | `{"entity", "dataset_version", "rows"}` for the 12 entities the domain ingests (`customers`, `queues`, `tickets`, `ticket_events`, `agents`, `skills`, `agent_skills`, `queue_skills`, `shifts`, `sla_policies`, `surveys`, `simulation_runs`) plus `shift_breaks` (the data-load-only table of 30-minute break intervals, columns of `0001_schema.sql`). Field names equal `tests/fixtures/golden/inputs.json` (and `data/seed.py` COLUMNS); every row carries every field, nulls included. |
| `web/public/data/manifest.json` | `dataset_version` (`sf-<seed>-20261026`), `dataset_hash`, `generated_at` (real UTC, not hashed), `contract_version` (`"v1"`), `generator` (name, seed, every parameter), `row_counts`, `designed_relationships` (with the realised numbers), `injection_manifest`, `stats`. |
| `data/injection-manifest.json` (+ copy in `web/public/data/`) | `INJ-01..09` as `{id, test, entity, location, record_ids, description, expected_handling}` (plus `detail` and, for the defects the domain rejects, `expected_rejections`) and the designed relationships. |
| `data/injection-events.json` | `EV-01..07`: replay-only command sequences (`steps`: command, headers, input envelope; the last step is the one that is checked) with `expected_status`, `expected_reason`, `expected` and `expected_handling`. |
| `web/public/data/golden/` | the hand-derived fixture (`tests/fixtures/golden/inputs.json`) in the same per-entity shape with a `manifest.json` (`dataset_version` `golden-v1`, the fixture's own hash, window, cutoffs, row counts) and `expected.json` (a copy of the fixture's expected values), so the web app can serve `?dataset=golden`. |

`dataset_hash` = sha256 over the concatenation, in entity-name order, of `json.dumps(rows, sort_keys=True,
separators=(",", ":"))` of each entity file (13 files). Timestamps are ISO-8601 UTC with a `Z` at second precision.
Durations are never stored: they are derived from event instants (minutes, 4 dp, by the domain).

## The simulated world

* 2026-07-06 .. 2026-09-27 (84 days, 12 weeks), snapshot cut `2026-09-27T23:59:59Z`. Weeks 1-8 are the training window,
  weeks 9-12 the holdout, which arrives 20 % harder by design (the generator draws Poisson counts per hour from the
  hour-of-week intensity x 1.2 in the holdout; the realisation is the first of a fixed series of attempts whose holdout/training
  rate ratio is within 1.5 points of +20 %: Poisson noise alone moves it by about 4 points at this volume). The attempt index and the discarded ratios are recorded in `manifest.json` `generator.parameters.arrival_realisation` (attempt 7; attempts 0 to 6 gave +12.86, +14.58, +22.82, +16.92, +12.69, +22.02, +30.46 %): a chosen realisation, not a measurement. The record is not part of `dataset_hash`.
* Queues `q-001` Billing, `q-002` Technical (both `fifo_within_priority`), `q-003` Onboarding (`fifo`); priorities P1..P3 with
  queue-specific mixes (technical P1 is 10 %); one skill per queue (`s-001..003`); SLA per priority, wall clock, calendar
  `cal-001` (24x7): P1 15 / 240 min, P2 60 / 1,440, P3 240 / 4,320 (first response / resolution).
* 18 agents with skills and proficiency 1-5 (29 `agent_skills` rows, two with a later `effective_from`: agt-005 onboarding from
  2026-08-03 and agt-015 billing from 2026-08-17, respected by the dispatcher), `max_concurrent` 1, in two timezones.
  Berlin (`Europe/Berlin`, UTC+2 all window): agt-001..009 (early 07-15, mid 09-17, late 11-19 local; agt-007 part time; agt-004
  works Tue-Sat and agt-006 Sun-Thu to cover the weekend). Santiago (`America/Santiago`): agt-010..012 (08-16), agt-013 part time,
  agt-014/015 (12-20), agt-016 (Sat/Sun 10-18, Mon-Wed 12-20), agt-017/018 (Sat/Sun nights 18:00-02:00, Mon-Wed 14-22).
  Two leave days per agent on Tue-Fri (never Mondays, never 2026-09-04..06). 1,020 shifts of 6 or 8 hours, each with a 30-minute
  break taken at the first idle moment after a planned time (42-55 % into the shift); the 1,018 taken breaks are in `shift_breaks`
  (the two Sunday 2026-09-27 night shifts start at 21:00Z and their breaks fall after the snapshot cut).
* **The DST weekend: America/Santiago, Sat 2026-09-05 / Sun 2026-09-06.** Clocks jump from UTC-04:00 to UTC-03:00 at
  2026-09-06T04:00:00Z (00:00 local). Shifts are declared in local wall-clock time and converted with `zoneinfo`; the night crew
  agt-017 and agt-018 works Sat 18:00 to Sun 02:00 local, which is 22:00Z to 05:00Z: **420 minutes, not 480**. agt-017's row is
  right; agt-018's is the injected defect INJ-08. Every other Santiago shift starts one hour earlier in UTC from 2026-09-06
  (08:00 local is 12:00Z before and 11:00Z after); Berlin does not move.
* Dispatch: arrivals, shifts, breaks and work are one event loop. An idle agent on shift (longest idle first) takes the best
  waiting ticket among the queues whose skill they hold (priority then arrival time inside a `fifo_within_priority` queue;
  `fifo` queues rank every ticket as P2) that fits before the end of the shift; a 10-60 s pick-up lag follows. Handling is
  lognormal by queue and priority, scaled by the agent's proficiency in the queue's skill (x1.30, 1.15, 1.00, 0.85, 0.72 for
  1..5). A human reply is recorded 1-4 minutes into the first service; 12 % of tickets (and every long one) are paused for 10-50
  minutes and resumed by the same agent; about 8 % are transferred 5-12 minutes into service (to another queue, waiting restarts
  there, the arrival never moves); about 6 % are reopened 2-30 hours after a resolution (one more cycle). Chat and phone
  customers abandon with a patience of about 35 / 18 minutes (55 % of them are impatient). Every ticket gets a bot
  acknowledgement (`acknowledged_bot`, actor `bot-001`) 3-9 seconds after creation. A few replies and pauses (1 %) are logged
  late: their `event_id` follows the order the log received them, their `occurred_at` is unchanged (P04-FLOW-01).
* Surveys: 60 % of final resolutions are invited (1-60 minutes after), 35 % of those respond; the response probability falls
  with a poor experience (a missed target, a transfer, a reopen) and with the score, so CSAT among responders is higher than
  among everyone invited (INJ-09). Three simulation runs describe the technical queue at the Monday bind from the training
  window only (rate, mean handling, priority mix, agents on shift): `sim-001` baseline, `sim-002` one more agent, `sim-003`
  the holdout intensity; 720-minute horizon, 120 warm-up minutes, seed 20261026.

## Size and the volume cap

Total **4.84 MB** (4,836,065 bytes in the 13 entity files plus manifests). Events are the volume driver: 21,948 rows (5.74 per
ticket) are 3.62 MB at about 165 bytes a row, because every row carries all seven fields. The specification asks for about 6,000
tickets **and** under 5 MB; with every field present these cannot both hold (6,000 tickets x 5.7 events x 165 bytes is 5.7 MB
before any other file), so the 5 MB cap wins: the generator targets 3,700 expected tickets (3,826 realised). The cap that keeps
the budget: one event row per state change, no separate `queued` row at creation (`created` carries the queue; `queued` appears
only when a reopened ticket re-enters its queue), one human reply recorded per ticket, no second reply after a transfer, 1,004
customers. The knob is `TICKETS_TARGET` in `data/generate.py`; the size test fails if it is raised past the budget.

## Designed relationships (numbers in `manifest.designed_relationships` and `stats.designed`)

* The technical queue P1 tail is long: resolution (measured from the original arrival) over 142 completed tickets has mean
  247 min and P90 619 min, P90 / mean 2.51 (15 % of technical P1 are major incidents that wait hours for engineering). The test
  recomputes it with the domain on the accepted population.
* Monday 09-11 UTC is the capacity bind: 1.33 arrivals per staffed hour against 0.98 for the next 2-hour block and 0.43 for the
  median block (blocks with at least 24 staffed hours; capacity = shift minus the break pro rata; surge x2.4 on those two hours,
  no leave on Mondays).
* Proficiency >= 4 resolves faster: mean handling per service interval 35.9 min (n 1,946) against 39.5 min (n 3,039); relative
  to the queue and priority mean 0.896 against 1.066.
* Holdout intensity +20.0 % (2.135 against 1.779 tickets per hour), designed and disclosed; the domain's `holdout_report` flags it.
* Other realised figures (`manifest.stats`): 7.9 % of tickets transferred, 6.3 % reopened, 5.5 % abandoned, invitation rate
  59.5 % of completions, response rate 34.9 %, CSAT among responders 0.864 against 0.759 among all invited, occupancy 0.425.

## Defects: where each one lives

`expected_rejections` are what `validate_batch` must return; dependents of a rejected ticket carry `TICKET_REJECTED` (D-05).

| Defect | In entity files | In events | Domain handling |
|---|---|---|---|
| INJ-01 bot acknowledgement labelled human (4 `replied_human` events by `bot-001`) | yes, `ticket_events` | EV-01 (C01 re-ingest) | each event rejected `BOT_AS_HUMAN_REPLY`; first response uses the real human reply |
| INJ-02 reopen recorded as a new customer (4 follow-up tickets, 4 new customer rows created at the ticket instant) | yes, `tickets`, `customers` | EV-02 (C06 reopen: one contact, reopen_count 1) | not detectable by the domain: two arrivals, the original's reopen missing from `disclosures`; the manifest is the analyst check |
| INJ-03 agent assigned an incompatible skill (3 tickets, one per queue) | yes | EV-03 (C03 refused `AGENT_NOT_QUALIFIED`) | whole ticket rejected `AGENT_NOT_QUALIFIED` |
| INJ-04 two simultaneous services for one agent (3 tickets) | yes | EV-04 (C01 re-ingest) | the later ticket rejected `CONCURRENCY_EXCEEDED`, the earlier start stays |
| INJ-05 shift with the break counted as available (3 shifts, `break_minutes` 0, break recorded in `shift_breaks`) | yes, `shifts` | EV-05 (C03 inside the break, `AGENT_ON_BREAK`; loads `shift_breaks.json`) | accepted; staffed time +30 min each; reconciliation with `shift_breaks` finds it |
| INJ-06 transfer that resets the arrival (3 tickets, `created_at` = transfer instant) | yes | EV-06 (C01 re-ingest) | whole ticket rejected `TRANSFER_RESETS_ARRIVAL` |
| INJ-07 simulation run with the warm-up included | no (the clean `simulation_runs` declare 120) | EV-07 (C08 with warm-up 0, same seed and config) | accepted; `statistics.warmup_excluded` 0 and a lower mean wait than the warmed run |
| INJ-08 DST shift (agt-018, Sat 2026-09-05: 480 min recorded, 420 real) | yes, `shifts` | | accepted; +60 staffed minutes; found by recomputing the end with `timeutil.local_to_utc` from the agent's zone |
| INJ-09 survey nonresponse skew | yes, `surveys` (318 unanswered invitations after a poor experience, 30 listed) | | disclosed (`disclosures.csat`: nonresponse, "not random"); realised rates in `stats` |

## Domain behaviours and gaps found while generating (unchanged, recorded for the owners of `domain/` and `data/`)

* `data/seed.py` has no loader for `shift_breaks` (the table is data-load only), so the file is loaded by the test itself; EV-05
  needs it in the table.
* The break rule of D-05 deducts a break only when the window covers the whole shift. A window that cuts a shift (a Sunday-night
  shift across the training/holdout boundary or the window end) counts the full overlap as available time, so the staffed minutes
  of adjacent windows add up to more than those of the whole window. `shift_breaks` now makes a declared-interval rule possible.
