-- 04_approvals_under_policy_versions.sql: who approved what under policy v1 and v2, and what separation of duties refused (P05-ART-04, D-04, D-06, D-09.1).
-- Question: which matched invoices may advance to approval, and by whom?
-- Needs 00_book.sql (ib_facts: `commit` rows = the first POLICY-VALID approval of each invoice, `reject` rows = reject decisions with
-- their refusal code, NULL when valid). The policy in force at a decision is the latest `effective_from` not after `decided_at`
-- (pol-v1 5000.00 from 2025-10-01, pol-v2 8000.00 from 2026-04-01; neither carries an escalation role). A limit is compared with the
-- invoice total in the invoice's OWN currency, with no conversion (the contract has no dated rate): a GBP and a USD invoice of 5,000.00
-- meet the same limit. Money below is per currency and never summed across currencies.
-- OBSERVED rows describe the synthetic history. The block `v1_counterfactual` is HYPOTHETICAL and says so in its first column.

-- @@ decisions_by_policy_version
WITH dec AS (
    SELECT a.approval_id, a.invoice_id, a.decision, p.policy_id, p.version_number, p.amount_limit
    FROM approvals a
    JOIN LATERAL (SELECT * FROM approval_policies ap WHERE ap.effective_from <= a.decided_at
                  ORDER BY ap.effective_from DESC, ap.version_number DESC, ap.policy_id COLLATE "C" DESC LIMIT 1) p ON TRUE
),
v AS (SELECT d.*, EXISTS (SELECT 1 FROM ib_facts f WHERE f.kind = 'commit' AND f.c = '2026-10-01T02:00:00Z' AND f.ref = d.approval_id) AS valid_approval,
             EXISTS (SELECT 1 FROM ib_facts f WHERE f.kind = 'reject' AND f.c = '2026-10-01T02:00:00Z' AND f.ref = d.approval_id AND f.code IS NULL) AS valid_reject
      FROM dec d)
SELECT policy_id, version_number, amount_limit,
       count(*) FILTER (WHERE decision = 'approve') AS approve_decisions,
       count(*) FILTER (WHERE valid_approval) AS valid_approvals,
       count(*) FILTER (WHERE decision = 'reject') AS reject_decisions,
       count(*) FILTER (WHERE valid_reject) AS valid_rejections
FROM v GROUP BY policy_id, version_number, amount_limit ORDER BY version_number;

-- @@ approvals_by_policy_and_currency
SELECT p.policy_id, i.currency, count(*) AS valid_approvals, round(sum(i.total), 2) AS approved_total, round(max(i.total), 2) AS largest_invoice,
       round(avg(extract(epoch FROM (a.decided_at - v.imported_at)) / 60)::numeric, 4) AS mean_minutes_to_approval
FROM ib_facts f
JOIN approvals a ON a.approval_id = f.ref
JOIN ib_run i ON i.c = f.c AND i.invoice_id = f.invoice_id
JOIN invoices v ON v.invoice_id = f.invoice_id
JOIN LATERAL (SELECT * FROM approval_policies ap WHERE ap.effective_from <= a.decided_at
              ORDER BY ap.effective_from DESC, ap.version_number DESC, ap.policy_id COLLATE "C" DESC LIMIT 1) p ON TRUE
WHERE f.kind = 'commit' AND f.c = '2026-10-01T02:00:00Z'
GROUP BY p.policy_id, i.currency ORDER BY p.policy_id COLLATE "C", i.currency COLLATE "C";

-- @@ approval_time_by_currency
-- Minutes from import to the first policy-valid approval, per currency (4 dp); pending invoices are not in it (they are counted in 06).
SELECT i.currency, count(*) AS valid_approvals, round(avg(extract(epoch FROM (a.decided_at - v.imported_at)) / 60)::numeric, 4) AS mean_minutes_to_approval,
       round(max(extract(epoch FROM (a.decided_at - v.imported_at)) / 60)::numeric, 4) AS longest_minutes
FROM ib_facts f
JOIN approvals a ON a.approval_id = f.ref
JOIN ib_run i ON i.c = f.c AND i.invoice_id = f.invoice_id
JOIN invoices v ON v.invoice_id = f.invoice_id
WHERE f.kind = 'commit' AND f.c = '2026-10-01T02:00:00Z'
GROUP BY i.currency ORDER BY i.currency COLLATE "C";

-- @@ limit_bands
-- Valid approvals by the policy in force and the size band of the invoice total (own currency): a total above pol-v1's limit can only be
-- approved after pol-v2 takes effect on 2026-04-01.
SELECT p.policy_id, CASE WHEN i.total <= 5000 THEN 'total up to 5000.00' ELSE 'total above 5000.00 up to 8000.00' END AS band,
       i.currency, count(*) AS valid_approvals
FROM ib_facts f
JOIN approvals a ON a.approval_id = f.ref
JOIN ib_run i ON i.c = f.c AND i.invoice_id = f.invoice_id
JOIN LATERAL (SELECT * FROM approval_policies ap WHERE ap.effective_from <= a.decided_at
              ORDER BY ap.effective_from DESC, ap.version_number DESC, ap.policy_id COLLATE "C" DESC LIMIT 1) p ON TRUE
WHERE f.kind = 'commit' AND f.c = '2026-10-01T02:00:00Z'
GROUP BY p.policy_id, 2, i.currency ORDER BY p.policy_id COLLATE "C", 2, i.currency COLLATE "C";

-- @@ matched_not_approved_over_limit
-- Matched at the cutoff, not approved, and above the limit of the policy in force at the cutoff (pol-v2, 8000.00): no escalation role exists,
-- so nobody may approve them (D-07). By currency, in each currency's own units.
WITH pol AS (SELECT amount_limit FROM approval_policies WHERE effective_from <= '2026-10-01T02:00:00Z' ORDER BY effective_from DESC, version_number DESC LIMIT 1)
SELECT i.currency, count(*) AS matched_not_approved, count(*) FILTER (WHERE i.total > (SELECT amount_limit FROM pol)) AS above_the_limit,
       round(sum(i.total) FILTER (WHERE i.total > (SELECT amount_limit FROM pol)), 2) AS above_the_limit_total
FROM ib_run i
WHERE i.c = '2026-10-01T02:00:00Z' AND i.matched
  AND NOT EXISTS (SELECT 1 FROM ib_facts f WHERE f.kind = 'commit' AND f.c = i.c AND f.invoice_id = i.invoice_id)
GROUP BY i.currency ORDER BY i.currency COLLATE "C";

-- @@ v1_counterfactual
-- HYPOTHETICAL: what pol-v1 (limit 5000.00, no escalation role) would have done to the approvals given after pol-v2 took effect. Nothing in
-- the data says these invoices would have waited or been escalated; the row only counts approvals whose total is above 5000.00.
SELECT 'HYPOTHETICAL: approvals under pol-v2 above the pol-v1 limit' AS statement, i.currency, count(*) AS approvals
FROM ib_facts f
JOIN approvals a ON a.approval_id = f.ref
JOIN ib_run i ON i.c = f.c AND i.invoice_id = f.invoice_id
WHERE f.kind = 'commit' AND f.c = '2026-10-01T02:00:00Z' AND a.decided_at >= '2026-04-01T00:00:00Z' AND i.total > 5000
GROUP BY i.currency ORDER BY i.currency COLLATE "C";

-- @@ separation_of_duties
-- Every refusal the rules can make, counted from facts. The snapshot has none: the generator approves only with an actor other than the
-- creator and inside the limit, so these zeros show the rules were never tripped here, not that they are untested (tests/test_rules.py and
-- the replay event INJ-06 exercise them).
WITH d AS (
    SELECT a.approval_id, a.invoice_id, a.actor_id, a.actor_role, a.decision, a.decided_at, i.created_by, i.imported_at,
           p.reviewer_role, p.escalation_role, p.amount_limit, r.total AS run_total
    FROM approvals a
    JOIN invoices i ON i.invoice_id = a.invoice_id
    LEFT JOIN LATERAL (SELECT * FROM approval_policies ap WHERE ap.effective_from <= a.decided_at
                       ORDER BY ap.effective_from DESC, ap.version_number DESC LIMIT 1) p ON TRUE
    LEFT JOIN ib_run r ON r.c = '2026-10-01T02:00:00Z' AND r.invoice_id = a.invoice_id
)
SELECT check_name, n FROM (
    SELECT 1 AS ord, 'approve decisions recorded' AS check_name, count(*) FILTER (WHERE decision = 'approve') AS n FROM d
    UNION ALL SELECT 2, 'approve decisions that are policy-valid (the committed invoices)', count(*) FROM ib_facts WHERE kind = 'commit' AND c = '2026-10-01T02:00:00Z'
    UNION ALL SELECT 3, 'SELF_APPROVAL: approver is the invoice creator', count(*) FILTER (WHERE decision = 'approve' AND actor_id = created_by) FROM d
    UNION ALL SELECT 4, 'ROLE_OR_LIMIT: role not allowed, or total above the limit in force', count(*) FILTER (WHERE decision = 'approve' AND run_total IS NOT NULL
        AND NOT (escalation_role = actor_role OR (reviewer_role = actor_role AND run_total <= amount_limit))) FROM d
    UNION ALL SELECT 5, 'BEFORE_IMPORT: decided before the invoice was imported', count(*) FILTER (WHERE decision = 'approve' AND decided_at < imported_at) FROM d
    UNION ALL SELECT 6, 'reject decisions recorded', count(*) FILTER (WHERE decision = 'reject') FROM d
    UNION ALL SELECT 7, 'reject decisions that are valid', count(*) FROM ib_facts WHERE kind = 'reject' AND c = '2026-10-01T02:00:00Z' AND code IS NULL
    UNION ALL SELECT 8, 'SELF_DECISION: rejecter is the invoice creator', count(*) FILTER (WHERE decision = 'reject' AND actor_id = created_by) FROM d
    UNION ALL SELECT 9, 'deciding actors who also created other invoices (allowed: the rule is per invoice)', count(DISTINCT actor_id) FILTER (WHERE actor_id IN (SELECT created_by FROM invoices)) FROM d
    UNION ALL SELECT 10, 'distinct deciding actors', count(DISTINCT actor_id) FROM d
    UNION ALL SELECT 11, 'distinct invoice creators', count(DISTINCT created_by) FROM invoices
) z ORDER BY ord;
