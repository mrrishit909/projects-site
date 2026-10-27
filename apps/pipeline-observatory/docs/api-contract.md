# Pipeline Observatory — API route inventory (backend contract, Mode A only)

Same envelopes, identity headers (roles engineer|operator|admin) and status codes as the other apps; lock order
(idempotency key, then source rows by id, then run/backfill rows by id), 409 `CONCURRENT_UPDATE` after three deadlock
retries; actor-bound idempotency with `dataset_version` and the role in the binding (409 `STALE_DATASET_VERSION`);
server-stamped instants. Prefix `/api/v1/pipeline-observatory`.

| ID | Method and path | Transition | Hard validation | Milestone |
|---|---|---|---|---|
| C01 | POST …/commands/fetch-source-page | cursor → raw page | retry-after honoured; cursor loop refused | slice |
| C02 | POST …/commands/validate-contract | raw → accepted / duplicate / quarantined | schema and semantic checks; nothing dropped | slice |
| C03 | POST …/commands/commit-batch | staged → durable batch + checkpoint | one transaction; replay idempotent on source_key | slice |
| C04 | POST …/commands/transform-models | staging → analytical tables | key and relationship tests | slice |
| C05 | POST …/commands/run-quality-gate | candidate → pass / block | fail closed on critical | slice |
| C06 | POST …/commands/publish-snapshot | passed candidate → current | atomic pointer; failed run never publishes | slice |
| C07 | POST …/commands/inject-fault | healthy → controlled failure | sandbox only; recorded | slice |
| C08 | POST …/commands/request-backfill | range → scheduled partitions | half-open; overlap refused | slice |
| C09 | POST …/commands/recover-incident | failed run → verified recovered | reconcile before closing | slice |
| C10 | POST …/commands/archive-evidence | completed run → release evidence | hashes and retention mapping | extension |
| R | GET …/data/{entity} | reads | stable ordering, cursor | slice |
| M | GET …/metrics?from=&to=&cutoff=&source_id=&group_by= | the twelve metrics | half-open window | slice |

Roles: C01–C05, C08 engineer, operator, admin; C06, C07, C09, C10 operator, admin. Reads need no actor.
