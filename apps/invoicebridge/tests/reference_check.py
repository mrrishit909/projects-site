#!/usr/bin/env python3
"""Independent reference calculation for the InvoiceBridge golden fixtures (P05-GOLD-01..11).

Standard library only; imports nothing from the application. Recomputes every figure in
expected.json from inputs.json (import, identity and duplicate merge, three-way match with
cumulative consumption, approval, export) and compares leaf by leaf. Money: Decimal strings
with 2 dp, quantities and unit-price variances 4 dp, rates 6 dp, minutes 4 dp (see CALCULATION.md,
DECISIONS). Rounding is ROUND_HALF_UP. Contract v1, decisions D-01..D-04.

Usage:
  python3 -I reference_check.py                # check everything, exit 0 only if all OK
  python3 -I reference_check.py --write-hashes # check, then (if all OK) write HASHES.json
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from decimal import Decimal as D, ROUND_HALF_UP
from pathlib import Path

GOLDEN = Path(__file__).resolve().parent / "fixtures" / "golden"
FIXTURES = [("golden", ""), ("variant-rejected", "variant-rejected/"), ("variant-empty", "variant-empty/")]
HASHED = ["inputs.json", "expected.json", "CALCULATION.md",
          "variant-rejected/inputs.json", "variant-rejected/expected.json",
          "variant-empty/inputs.json", "variant-empty/expected.json"]
ENTITIES = [("vendors", "vendor_id"), ("purchase_orders", "po_id"), ("po_lines", "po_line_id"),
            ("receipts", "receipt_id"), ("invoices", "invoice_id"), ("invoice_lines", "invoice_line_id"),
            ("credit_notes", "credit_id"), ("approval_policies", "policy_id"), ("approvals", "approval_id")]
CODES = ["QUANTITY_BLOCKED", "PRICE_VARIANCE", "NO_PO_LINE", "ROUNDING_EXCEPTION", "CURRENCY_MISMATCH"]
RULE_VERSION = "1"
C2, C4, C6 = D("0.01"), D("0.0001"), D("0.000001")
failures = 0
checks = 0


def report(ok, name, expected, got):
    global failures, checks
    checks += 1
    if ok:
        print(f"OK {name} {got}")
    else:
        failures += 1
        print(f"MISMATCH {name} expected {expected!r} got {got!r}")


def ts(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def m2(x):
    return x.quantize(C2, rounding=ROUND_HALF_UP)


def s2(x):
    return str(m2(x))


def s4(x):
    return str(x.quantize(C4, rounding=ROUND_HALF_UP))


def s6(x):
    return str(x.quantize(C6, rounding=ROUND_HALF_UP))


def norm_number(n):
    """D-01 (decision D-P5-6): upper-case, keep letters and digits only."""
    return re.sub(r"[^A-Z0-9]", "", n.upper())


def invoice_amounts(inv, lines):
    """D-02: subtotal at line precision, tax on the unrounded subtotal, each rounded, declared order."""
    raw = sum((D(l["quantity"]) * D(l["unit_price"]) for l in lines), D(0))
    sub = m2(raw)
    tax = m2(raw * D(inv["tax_rate"]))
    total = sub + tax + D(inv["freight"]) - D(inv["invoice_discount"])
    return sub, tax, total


def ingest(data):
    acc = {e: [] for e, _ in ENTITIES}
    rej = []

    def reject(ent, idk, row, code):
        rej.append({"entity": ent, "id": row[idk], "status": "rejected", "reason_code": code, "raw_row": row})

    ids = {e: set() for e, _ in ENTITIES}
    for r in data["vendors"]:
        acc["vendors"].append(r); ids["vendors"].add(r["vendor_id"])
    for r in data["purchase_orders"]:
        if r["vendor_id"] in ids["vendors"]:
            acc["purchase_orders"].append(r); ids["purchase_orders"].add(r["po_id"])
        else:
            reject("purchase_orders", "po_id", r, "UNKNOWN_VENDOR")
    for r in data["po_lines"]:
        if r["po_id"] not in ids["purchase_orders"]:
            reject("po_lines", "po_line_id", r, "UNKNOWN_PO")
        elif D(r["quantity"]) <= 0:
            reject("po_lines", "po_line_id", r, "NON_POSITIVE_QUANTITY")
        else:
            acc["po_lines"].append(r); ids["po_lines"].add(r["po_line_id"])
    for r in data["receipts"]:
        if r["po_line_id"] not in ids["po_lines"]:
            reject("receipts", "receipt_id", r, "UNKNOWN_PO_LINE")
        elif D(r["received_quantity"]) <= 0:
            reject("receipts", "receipt_id", r, "NON_POSITIVE_QUANTITY")
        else:
            acc["receipts"].append(r)
    # invoices are atomic: an invalid line or vendor rejects the header and every sibling line
    lines_by_inv = {}
    for l in data["invoice_lines"]:
        lines_by_inv.setdefault(l["invoice_id"], []).append(l)
    for inv in data["invoices"]:
        ls = lines_by_inv.get(inv["invoice_id"], [])
        bad_vendor = inv["vendor_id"] not in ids["vendors"]
        bad_lines = {l["invoice_line_id"] for l in ls if D(l["quantity"]) <= 0}
        if bad_vendor or bad_lines:
            reject("invoices", "invoice_id", inv, "UNKNOWN_VENDOR" if bad_vendor else "DEPENDENT_REJECTED")
            for l in ls:
                reject("invoice_lines", "invoice_line_id", l,
                       "NON_POSITIVE_QUANTITY" if l["invoice_line_id"] in bad_lines else "DEPENDENT_REJECTED")
        else:
            acc["invoices"].append(inv); ids["invoices"].add(inv["invoice_id"])
            acc["invoice_lines"].extend(ls)
    for ent, idk in (("credit_notes", "credit_id"), ("approvals", "approval_id")):
        for r in data[ent]:
            if r["invoice_id"] in ids["invoices"]:
                acc[ent].append(r)
            else:
                reject(ent, idk, r, "DEPENDENT_REJECTED")
    acc["approval_policies"] = list(data["approval_policies"])
    rej.sort(key=lambda r: (r["entity"], r["id"]))

    # D-01 identity: (vendor_id, normalised number, invoice_date, computed total); earliest import is canonical
    by_inv = {i["invoice_id"]: [l for l in acc["invoice_lines"] if l["invoice_id"] == i["invoice_id"]] for i in acc["invoices"]}
    groups = {}
    for inv in sorted(acc["invoices"], key=lambda i: (i["imported_at"], i["invoice_id"])):
        total = invoice_amounts(inv, by_inv[inv["invoice_id"]])[2]
        key = f'{inv["vendor_id"]}|{norm_number(inv["invoice_number"])}|{inv["invoice_date"]}|{s2(total)}'
        groups.setdefault(key, []).append(inv)
    merged, merged_into = [], {}
    for key, members in groups.items():
        for dup in members[1:]:
            merged_into[dup["invoice_id"]] = members[0]["invoice_id"]
            merged.append({"entity": "invoices", "id": dup["invoice_id"], "status": "merged", "reason_code": "DUPLICATE_IDENTITY",
                           "merged_into": members[0]["invoice_id"], "group_key": key, "source_sha256": dup["source_sha256"]})
    merged.sort(key=lambda r: r["id"])
    counts = {e: {"accepted": len(acc[e]), "rejected": sum(1 for r in rej if r["entity"] == e), "merged": 0} for e, _ in ENTITIES}
    counts["invoices"]["accepted"] -= len(merged_into)
    counts["invoices"]["merged"] = len(merged_into)
    merged_lines = sum(len(by_inv[i]) for i in merged_into)
    counts["invoice_lines"]["accepted"] -= merged_lines
    counts["invoice_lines"]["merged"] = merged_lines
    groups_detected = sum(1 for m in groups.values() if len(m) > 1)
    return acc, rej, merged, merged_into, counts, by_inv, groups_detected


def match_run(data, acc, merged_into, by_inv, cutoff):
    """D-03 at a cutoff: receipts received_at <= cutoff, invoices imported_at <= cutoff, in
    (invoice_date, imported_at, invoice_id) order; matched invoices consume received quantity."""
    tol_price = D(data["tolerances"]["price_per_unit"])
    tol_round = D(data["tolerances"]["rounding_per_invoice"])
    c = ts(cutoff)
    pol = {l["po_line_id"]: l for l in acc["po_lines"]
           if ts(next(p["ordered_at"] for p in acc["purchase_orders"] if p["po_id"] == l["po_id"])) <= c}
    po_cur = {p["po_id"]: p["currency"] for p in acc["purchase_orders"]}
    net = {k: D(0) for k in pol}
    for r in acc["receipts"]:
        if not r["reversed"] and ts(r["received_at"]) <= c and r["po_line_id"] in net:
            net[r["po_line_id"]] += D(r["received_quantity"])
    consumed = {k: D(0) for k in pol}
    results, invs = [], {}
    cand = [i for i in acc["invoices"] if i["invoice_id"] not in merged_into and ts(i["imported_at"]) <= c]
    for inv in sorted(cand, key=lambda i: (i["invoice_date"], i["imported_at"], i["invoice_id"])):
        sub, tax, total = invoice_amounts(inv, by_inv[inv["invoice_id"]])
        reasons, local, rows = set(), {}, []
        for l in sorted(by_inv[inv["invoice_id"]], key=lambda l: l["invoice_line_id"]):
            q, pr = D(l["quantity"]), D(l["unit_price"])
            p = pol.get(l["po_line_id"])
            row = {"invoice_line_id": l["invoice_line_id"], "invoice_id": inv["invoice_id"], "rule_version": RULE_VERSION,
                   "status": "matched", "reason_code": None, "available_quantity": None, "quantity_variance": None, "price_variance": None}
            if p is None:
                row.update(status="exception", reason_code="NO_PO_LINE")
            elif po_cur[p["po_id"]] != inv["currency"]:
                row.update(status="exception", reason_code="CURRENCY_MISMATCH")
            else:
                avail = net[p["po_line_id"]] - consumed[p["po_line_id"]] - local.get(p["po_line_id"], D(0))
                qv, pv = q - avail, pr - D(p["unit_price"])
                row.update(available_quantity=s4(avail), quantity_variance=s4(qv), price_variance=s4(pv))
                if qv > 0:
                    row.update(status="exception", reason_code="QUANTITY_BLOCKED")
                elif abs(pv) > tol_price:
                    row.update(status="exception", reason_code="PRICE_VARIANCE")
                local[p["po_line_id"]] = local.get(p["po_line_id"], D(0)) + q
                row["_qv"], row["_pr"], row["_p"] = qv, pr, p["po_line_id"]
            if row["reason_code"]:
                reasons.add(row["reason_code"])
            rows.append(row)
        diff = abs(D(inv["declared_total"]) - total)
        if diff > tol_round:
            reasons.add("ROUNDING_EXCEPTION")
        ok = not reasons
        if ok:
            for k, v in local.items():
                consumed[k] += v
        results.extend(rows)
        invs[inv["invoice_id"]] = {"sub": sub, "tax": tax, "total": total, "diff": diff, "types": sorted(reasons), "matched": ok}
    q = {"pol": pol, "net": net, "consumed": consumed}
    return results, invs, q


def quantities(q, results):
    pol, net, cons = q["pol"], q["net"], q["consumed"]
    rni = sum((max(net[k] - cons[k], D(0)) for k in pol), D(0))
    rni_val = sum((max(net[k] - cons[k], D(0)) * D(pol[k]["unit_price"]) for k in pol), D(0))
    blocked = [r for r in results if r["reason_code"] == "QUANTITY_BLOCKED"]
    b_q = sum((r["_qv"] for r in blocked), D(0))
    b_v = sum((r["_qv"] * r["_pr"] for r in blocked), D(0))
    return {
        "ordered_quantity": s4(sum((D(p["quantity"]) for p in pol.values()), D(0))),
        "net_received_quantity": s4(sum(net.values(), D(0))),
        "accepted_invoiced_quantity": s4(sum(cons.values(), D(0))),
        "open_to_receive_quantity": s4(sum((max(D(pol[k]["quantity"]) - net[k], D(0)) for k in pol), D(0))),
        "open_to_invoice_quantity": s4(sum((max(D(pol[k]["quantity"]) - cons[k], D(0)) for k in pol), D(0))),
        "received_not_invoiced_quantity": s4(rni),
        "received_not_invoiced_value": s2(rni_val),
        "invoiced_not_received_quantity": s4(b_q),
        "invoiced_not_received_value": s2(b_v),
    }


def compute(data):
    acc, rejected, merged, merged_into, counts, by_inv, groups_detected = ingest(data)
    results, invs, q = match_run(data, acc, merged_into, by_inv, data["as_of"])
    inv_row = {i["invoice_id"]: i for i in acc["invoices"]}
    # approvals (D-04): separation of duties, policy effective at decision time, role and limit
    approved, invalid, approved_at = set(), [], {}
    for a in sorted(acc["approvals"], key=lambda a: (a["decided_at"], a["approval_id"])):
        i = inv_row[a["invoice_id"]]
        st = invs.get(a["invoice_id"])
        pols = [p for p in acc["approval_policies"] if ts(p["effective_from"]) <= ts(a["decided_at"])]
        pol = max(pols, key=lambda p: ts(p["effective_from"])) if pols else None
        if a["decision"] != "approve":
            continue
        code = None
        if st is None or not st["matched"]:
            code = "NOT_MATCHED"
        elif a["actor_id"] == i["created_by"]:
            code = "SELF_APPROVAL"
        elif pol is None or a["actor_role"] != pol["reviewer_role"] or st["total"] > D(pol["amount_limit"]):
            code = "ROLE_OR_LIMIT"
        if code:
            invalid.append({"approval_id": a["approval_id"], "reason_code": code})
        elif a["invoice_id"] not in approved:
            approved.add(a["invoice_id"]); approved_at[a["invoice_id"]] = a["decided_at"]
    # export: idempotent by idempotency_key; one row per (invoice_id, batch_id)
    seen, rows, exported, batches, repeats = set(), [], set(), 0, 0
    for r in data["export_requests"]:
        if r["idempotency_key"] in seen:
            repeats += 1
            continue
        seen.add(r["idempotency_key"]); batches += 1
        for iid in sorted(r["invoice_ids"]):
            if iid in approved and iid not in exported:
                i = inv_row[iid]
                amt = s2(invs[iid]["total"])
                payload = "|".join([iid, i["vendor_id"], i["invoice_number"], i["invoice_date"], i["currency"], amt])
                rows.append({"export_id": f'exp-{r["batch_id"]}-{iid}', "invoice_id": iid, "batch_id": r["batch_id"],
                             "exported_at": r["exported_at"], "vendor_id": i["vendor_id"], "invoice_number": i["invoice_number"],
                             "invoice_date": i["invoice_date"], "currency": i["currency"], "amount": amt,
                             "content_hash": hashlib.sha256(payload.encode()).hexdigest()})
                exported.add(iid)
    status = {}
    for iid, st in invs.items():
        status[iid] = "exported" if iid in exported else "approved" if iid in approved else "matched" if st["matched"] else "exception"
    for iid, tgt in merged_into.items():
        status[iid] = "merged"
    docs_inv = {}
    for i in sorted(acc["invoices"], key=lambda i: i["invoice_id"]):
        iid = i["invoice_id"]
        if iid in invs:
            st = invs[iid]; sub, tax, total, diff, types = st["sub"], st["tax"], st["total"], st["diff"], st["types"]
        else:
            sub, tax, total = invoice_amounts(i, by_inv[iid]); diff = abs(D(i["declared_total"]) - total); types = []
        d = {"status": status[iid], "subtotal": s2(sub), "tax": s2(tax), "freight": s2(D(i["freight"])),
             "invoice_discount": s2(D(i["invoice_discount"])), "total": s2(total), "declared_total": s2(D(i["declared_total"])),
             "rounding_difference": s2(diff), "exception_types": types}
        if iid in merged_into:
            d["merged_into"] = merged_into[iid]
        docs_inv[iid] = d
    match_rows = [{k: v for k, v in r.items() if not k.startswith("_")} for r in sorted(results, key=lambda r: r["invoice_line_id"])]
    good = [iid for iid, s in status.items() if s in ("matched", "approved", "exported")]
    sub_t = sum((invs[i]["sub"] for i in good), D(0)); tax_t = sum((invs[i]["tax"] for i in good), D(0))
    tot_t = sum((invs[i]["total"] for i in good), D(0))
    oblig = [i for i in good if status[i] in ("approved", "exported")]
    oblig_t = sum((invs[i]["total"] for i in oblig), D(0))
    by_reason = {c: 0 for c in CODES}
    exc = []
    for iid in sorted(invs):
        for t in invs[iid]["types"]:
            by_reason[t] += 1
            exc.append({"exception_id": f"exc-{len(exc) + 1:03d}", "invoice_id": iid, "exception_type": t, "owner_id": None, "status": "open"})
    eligible = len(invs)
    flagged = sum(1 for i in invs.values() if i["types"])
    minutes = [(ts(approved_at[i]) - ts(inv_row[i]["imported_at"])).total_seconds() / 60 for i in sorted(approved)]
    mean = None if not minutes else s4(sum((D(str(x)) for x in minutes), D(0)) / len(minutes))
    credits, cseen = D(0), set()
    for c in acc["credit_notes"]:
        if c["credit_id"] not in cseen and status.get(c["invoice_id"]) in ("approved", "exported"):
            cseen.add(c["credit_id"]); credits += D(c["credit_amount"])
    exp_total = sum((D(r["amount"]) for r in rows), D(0))
    snaps = {}
    for cut in data["snapshot_cutoffs"]:
        r2, _, q2 = match_run(data, acc, merged_into, by_inv, cut)
        snaps[cut] = quantities(q2, r2)
    return {
        "contract_version": data["contract_version"],
        "ingest": {"counts": counts, "rejected_records": rejected, "merged_records": merged},
        "documents": {"invoices": docs_inv, "match_results": match_rows},
        "metrics": {
            "matched": {"invoice_count": len(good), "amount_before_tax": s2(sub_t), "tax": s2(tax_t), "total": s2(tot_t)},
            "obligations": {"count": len(oblig), "total": s2(oblig_t)},
            "exceptions": {"open_count": len(exc), "unowned_count": sum(1 for e in exc if e["owner_id"] is None),
                           "by_reason": by_reason, "records": exc},
            "duplicates": {"groups_detected": groups_detected, "rows_merged": len(merged_into), "unresolved_groups": 0},
            "quantities": quantities(q, results),
            "snapshots": snaps,
            "rates": {"eligible_invoices": eligible,
                      "straight_through_rate": None if eligible == 0 else s6(D(eligible - flagged) / D(eligible)),
                      "exception_rate": None if eligible == 0 else s6(D(flagged) / D(eligible))},
            "processing": {"approved_count": len(approved), "mean_minutes": mean,
                           "pending_count": sum(1 for i in invs if i not in approved)},
            "approvals": {"valid_count": len(approved), "invalid_records": invalid},
            "payable": {"approved_total": s2(oblig_t), "credit_total": s2(credits), "approved_payable": s2(oblig_t - credits)},
            "export": {"requests_received": len(data["export_requests"]), "batches_created": batches,
                       "repeat_requests_returned_prior": repeats, "rows": rows,
                       "exclusions": [{"invoice_id": i, "reason_code": "EXCEPTION_OPEN" if status[i] == "exception" else "NOT_APPROVED"}
                                      for i in sorted(invs) if status[i] in ("exception", "matched")],
                       "accepted_export_total": s2(exp_total), "eligible_approved_total": s2(oblig_t),
                       "difference": s2(exp_total - oblig_t)},
        },
    }


def flatten(x, path=""):
    if isinstance(x, dict):
        out = {}
        for k, v in x.items():
            out.update(flatten(v, f"{path}.{k}" if path else k))
        return out
    if isinstance(x, list):
        if not x:
            return {path + "[]": "empty"}
        out = {}
        for i, v in enumerate(x):
            out.update(flatten(v, f"{path}[{i}]"))
        return out
    return {path: x}


def no_floats(x, where):
    if isinstance(x, float):
        report(False, f"{where}.no_float", "no float", x)
    elif isinstance(x, dict):
        [no_floats(v, where) for v in x.values()]
    elif isinstance(x, list):
        [no_floats(v, where) for v in x]


def spec_sentence():
    """P05-GOLD-01 recomputed from the sentence alone, then compared with golden/expected.json."""
    exp = json.loads((GOLDEN / "expected.json").read_text())
    sub = D(6) * D("20.00"); tax = m2(sub * D("0.10")); total = sub + tax
    m = exp["metrics"]
    for name, want, got in (("spec.first_invoice_before_tax", "120.00", s2(sub)), ("spec.first_invoice_tax", "12.00", s2(tax)),
                            ("spec.first_invoice_total", "132.00", s2(total)),
                            ("spec.expected_matched_before_tax", s2(sub), m["matched"]["amount_before_tax"]),
                            ("spec.expected_matched_total", s2(total), m["matched"]["total"]),
                            ("spec.expected_obligations", "1/132.00", f'{m["obligations"]["count"]}/{m["obligations"]["total"]}'),
                            ("spec.second_invoice_blocked", "1", str(m["exceptions"]["by_reason"]["QUANTITY_BLOCKED"]))):
        report(want == got, name, want, got)
    blocked_would_be = D(4) > D(10) * 0 + D(6) - D(6)   # 4 invoiced > 6 received - 6 already invoiced
    report(blocked_would_be, "spec.second_invoice_exceeds_available", True, blocked_would_be)


def check_fixture(label, prefix):
    data = json.loads((GOLDEN / (prefix + "inputs.json")).read_text())
    exp = json.loads((GOLDEN / (prefix + "expected.json")).read_text())
    no_floats(exp, label)
    got = compute(data)
    fe, fg = flatten(exp), flatten(got)
    for k in fe:
        report(k in fg and fg[k] == fe[k], f"{label}.{k}", fe[k], fg.get(k, "<missing>"))
    for k in fg:
        if k not in fe:
            report(False, f"{label}.{k}", "<absent>", fg[k])


def sha(rel):
    return hashlib.sha256((GOLDEN / rel).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-hashes", action="store_true")
    args = ap.parse_args()
    spec_sentence()
    for label, prefix in FIXTURES:
        check_fixture(label, prefix)
    hp = GOLDEN / "HASHES.json"
    if args.write_hashes:
        if failures:
            print(f"NOT WRITING HASHES: {failures} mismatch(es)")
        else:
            hp.write_text(json.dumps({"algorithm": "sha256", "sha256": {p: sha(p) for p in HASHED}}, indent=2) + "\n")
            print(f"OK wrote {hp.name}")
    elif hp.exists():
        stored = json.loads(hp.read_text())["sha256"]
        for p in HASHED:
            report(stored.get(p) == sha(p), f"hash.{p}", stored.get(p), sha(p))
    else:
        report(False, "hash.HASHES.json", "present", "missing")
    print("ALL OK" + f" ({checks} checks)" if not failures else f"{failures} MISMATCH(ES) of {checks} checks")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
