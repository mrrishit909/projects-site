# ServiceFlow — synthetic data generator specification (P04-WORK-03)

* Seed 20261026; 12 weeks 2026-07-06 .. 2026-09-27 UTC; 3 queues (billing, technical,
  onboarding) with priorities P1..P3; 18 agents with skills and shifts (two timezones, one
  DST-crossing weekend), breaks of 30 minutes; ~6,000 tickets with Poisson arrivals by hour-of-
  week intensity; a bot acknowledgement event on every ticket; ~8 % transfers; ~6 % reopens;
  surveys invited on 60 % of resolutions with 35 % response; SLA policies per priority.
* Training window weeks 1–8, holdout weeks 9–12 with a +20 % arrival intensity in the
  holdout (designed, disclosed).
* Designed relationships: the technical queue P1 tail is long (P90 ≫ mean); Monday 09–11 UTC
  is the capacity bind; agents with proficiency ≥ 4 resolve faster.
* Injected defects (manifest + replay events): bot acknowledgement labelled human, a reopen
  recorded as a new customer, an agent assigned an incompatible skill, two simultaneous
  services for one agent, a shift with break counted as available, a transfer that resets
  arrival, a simulation run with warm-up included, a DST shift, survey nonresponse skew.
* Output under 5 MB: events are the volume driver; keep one event row per state change.
