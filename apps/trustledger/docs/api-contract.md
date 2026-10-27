# TrustLedger — API route inventory (backend contract, Mode A only)

Same envelopes, identity headers (roles analyst|steward|admin) and status codes as the other apps; lock order
(idempotency key, then dataset rows by id, then issue/candidate rows by id), 409 `CONCURRENT_UPDATE` after three
deadlock retries; actor-bound idempotency with `dataset_version` and the actor in the binding (409
`STALE_DATASET_VERSION`). Prefix `/api/v1/trustledger`.

**Identity (D-10 R7-03).** `X-Actor-Id` is the exact id of a registered owner (401 `UNKNOWN_ACTOR` if not; 403 `ACTOR_INACTIVE` if inactive); the role is the register's, and an
`X-Actor-Role` that differs is 403 `ROLE_MISMATCH` (a value outside analyst/steward/admin is 403 `ROLE_FORBIDDEN`). A proposer cannot decide or reverse their own candidate
(409 `SELF_REVIEW`).

| ID | Method and path | Transition | Hard validation | Milestone |
|---|---|---|---|---|
| C01 | POST …/commands/register-dataset | absent → cataloged | owner active, classification present | slice |
| C02 | POST …/commands/publish-definition | draft → reviewed → published | each step a new version row; history preserved; `status` = draft \| reviewed \| published; reviewer ≠ drafter (409 `SELF_REVIEW`), no skipped step (409 `INVALID_TRANSITION`: `REVIEW_REQUIRES_DRAFT`, `PUBLICATION_REQUIRES_REVIEW`), content unchanged since the reviewed version (409 `CONTENT_CHANGED`) | slice |
| C03 | POST …/commands/run-rule | active rule → measured result | eligible and failing counts, rule and weight versions | slice |
| C04 | POST …/commands/open-issue | failure → owned issue | run and severity linked | slice |
| C05 | POST …/commands/triage-issue | open → investigating | owner and due date | slice |
| C06 | POST …/commands/suggest-match | records → candidate | canonical pair order, features, explanation | slice |
| C07 | POST …/commands/approve-merge | candidate → linked | reviewer ≠ proposer (409 `SELF_REVIEW`); audit | slice |
| C08 | POST …/commands/reverse-merge | merged → reversed | restores both identities; history kept | slice |
| C09 | POST …/commands/disable-rule | active → disabled | reason; history retained | slice |
| C10 | POST …/commands/verify-remediation | claimed → resolved | successful rerun of the same rule version; a disabled rule is rerun too (`rule_disabled` in the result) | slice |
| C11 | POST …/commands/correct-dataset-rows | records → new record versions | `{dataset_id, reason, corrections: [{row_id, changes: {field: text\|integer\|boolean\|null}}]}`; append-only (`row_version`, `supersedes_row_id`, actor, server instant); 422 `UNKNOWN_ROW`, `ROW_ID_IMMUTABLE`, `NO_CHANGE`, `DUPLICATE_ROW`, `REASON_REQUIRED`; 404 `DATASET_UNKNOWN`; warning `CORRECTION_IS_NOT_VERIFICATION` while issues of the dataset are unresolved | review R7 |
| C12 | POST …/commands/record-refresh | dataset → refresh recorded | `{dataset_id, refreshed_at}`; append-only history; 422 `REFRESH_IN_FUTURE`, `REFRESH_BEFORE_REGISTRATION`, `TIMESTAMP_INVALID`; 409 `REFRESH_EXISTS` | review R7 |
| R | GET …/data/{entity} | reads | stable ordering, cursor | slice |
| M | GET …/metrics?from=&to=&as_of=&dataset_id=&weight_version=&group_by= | the twelve metrics | half-open window | slice |

Roles: C01, C03, C04, C05, C06, C11, C12 analyst, steward, admin; C02, C07, C08, C09, C10 steward, admin. Reads need no actor. Reads take `from`, `to` and `as_of` as
instants with a zone (`Z` or an offset); a naive value or a date is 422 `TIMESTAMP_INVALID` (D-10 R7-14). `GET …/data/{entity}` also serves `quality_rule_versions` (filter `rule_id`),
`dataset_refreshes` and, with `row_version` / `recorded_at`, the versions in `dataset_rows`.
