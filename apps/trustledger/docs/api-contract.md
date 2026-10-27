# TrustLedger — API route inventory (backend contract, Mode A only)

Same envelopes, identity headers (roles analyst|steward|admin) and status codes as the other apps; lock order
(idempotency key, then dataset rows by id, then issue/candidate rows by id), 409 `CONCURRENT_UPDATE` after three
deadlock retries; actor-bound idempotency with `dataset_version` and the role in the binding (409
`STALE_DATASET_VERSION`). Prefix `/api/v1/trustledger`.

| ID | Method and path | Transition | Hard validation | Milestone |
|---|---|---|---|---|
| C01 | POST …/commands/register-dataset | absent → cataloged | owner active, classification present | slice |
| C02 | POST …/commands/publish-definition | draft → reviewed → published | new version row; history preserved | slice |
| C03 | POST …/commands/run-rule | active rule → measured result | eligible and failing counts, rule and weight versions | slice |
| C04 | POST …/commands/open-issue | failure → owned issue | run and severity linked | slice |
| C05 | POST …/commands/triage-issue | open → investigating | owner and due date | slice |
| C06 | POST …/commands/suggest-match | records → candidate | canonical pair order, features, explanation | slice |
| C07 | POST …/commands/approve-merge | candidate → linked | reviewer ≠ proposer; audit | slice |
| C08 | POST …/commands/reverse-merge | merged → reversed | restores both identities; history kept | slice |
| C09 | POST …/commands/disable-rule | active → disabled | reason; history retained | slice |
| C10 | POST …/commands/verify-remediation | claimed → resolved | successful rerun of the same rule version | slice |
| R | GET …/data/{entity} | reads | stable ordering, cursor | slice |
| M | GET …/metrics?from=&to=&as_of=&dataset_id=&weight_version=&group_by= | the twelve metrics | half-open window | slice |

Roles: C01, C03, C04, C05, C06 analyst, steward, admin; C02, C07, C08, C09, C10 steward, admin. Reads need no actor.
