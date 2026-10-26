"""Shared helpers for the tests (imported, not auto-collected): fixtures, the DB fixtures, a population builder and the
driver that replays a fixture's ``inputs.json`` through the API commands.

Every database test gets a clean schema: ``migrate.reset`` drops the project's tables and ``apply_migrations`` recreates
them. Tests skip cleanly when DATABASE_URL is unset (the pure-domain tests never need it).
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterator

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "domain", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from api.app import PREFIX, create_app  # noqa: E402
from data import migrate, seed  # noqa: E402

GOLDEN = ROOT / "tests" / "fixtures" / "golden"
CLERK = {"X-Actor-Id": "usr-clerk01", "X-Actor-Role": "clerk"}
REVIEWER = {"X-Actor-Id": "usr-rev01", "X-Actor-Role": "reviewer"}
ADMIN = {"X-Actor-Id": "usr-adm01", "X-Actor-Role": "admin"}
VARIANTS = ["", "variant-rejected", "variant-empty"]


def golden_inputs(sub: str = "") -> dict[str, Any]:
    return copy.deepcopy(json.loads((GOLDEN / sub / "inputs.json").read_text()))


def golden_expected(sub: str = "") -> dict[str, Any]:
    return json.loads((GOLDEN / sub / "expected.json").read_text())


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class World:
    """A small dataset builder for rule tests: vendor ven-1 (USD) and ven-2 (EUR), PO lines, receipts, invoices, approvals."""

    def __init__(self, **tol: str) -> None:
        self.d: dict[str, Any] = {
            "contract_version": 1, "as_of": "2026-10-26T00:00:00Z", "snapshot_cutoffs": [],
            "tolerances": {"price_per_unit": "0.00", "rounding_per_line": "0.01", "rounding_per_invoice": "0.02", **tol},
            "vendors": [{"vendor_id": "ven-1", "vendor_name": "Acme", "tax_reference": "T1", "currency": "USD", "active": True},
                        {"vendor_id": "ven-2", "vendor_name": "Euro GmbH", "tax_reference": "T2", "currency": "EUR", "active": True}],
            "purchase_orders": [{"po_id": "po-1", "vendor_id": "ven-1", "ordered_at": "2026-10-01T09:00:00Z", "status": "open", "currency": "USD"},
                                {"po_id": "po-2", "vendor_id": "ven-2", "ordered_at": "2026-10-01T09:00:00Z", "status": "open", "currency": "EUR"}],
            "po_lines": [], "receipts": [], "invoices": [], "invoice_lines": [], "credit_notes": [],
            "approval_policies": [{"policy_id": "pol-v1", "version_number": 1, "amount_limit": "5000.00", "reviewer_role": "reviewer",
                                   "escalation_role": "admin", "effective_from": "2026-01-01T00:00:00Z"}],
            "approvals": [], "export_requests": [],
        }
        self.n = {"inv": 0, "rc": 0, "ap": 0}

    def pol(self, pid: str, po: str = "po-1", qty: str = "10", price: str = "20.00", code: str = "W") -> str:
        self.d["po_lines"].append({"po_line_id": pid, "po_id": po, "product_code": code, "quantity": qty, "unit_price": price})
        return pid

    def receipt(self, pol: str, qty: str, at: str = "2026-10-05T10:00:00Z", reversed: bool = False) -> str:
        self.n["rc"] += 1
        rid = f"rc-{self.n['rc']:03d}"
        self.d["receipts"].append({"receipt_id": rid, "po_line_id": pol, "received_quantity": qty, "received_at": at, "reversed": reversed})
        return rid

    def invoice(self, iid: str, lines: list[tuple], number: str | None = None, vendor: str = "ven-1", currency: str = "USD",
                date: str = "2026-10-06", at: str = "2026-10-06T09:00:00Z", rate: str = "0.10", freight: str = "0.00",
                discount: str = "0.00", declared: str | None = None, by: str = "usr-clerk01", digest: str | None = None) -> str:
        """``lines``: (invoice_line_id, po_line_id, quantity, unit_price[, line_amount]). ``declared`` defaults to the computed total."""
        from decimal import ROUND_HALF_UP, Decimal
        raw = sum((Decimal(l[2]) * Decimal(l[3]) for l in lines), Decimal(0))
        sub = raw.quantize(Decimal("0.01"), ROUND_HALF_UP)
        tax = (raw * Decimal(rate)).quantize(Decimal("0.01"), ROUND_HALF_UP)
        total = sub + tax + Decimal(freight) - Decimal(discount)
        self.n["inv"] += 1
        self.d["invoices"].append({
            "invoice_id": iid, "vendor_id": vendor, "invoice_number": number or iid.upper(), "invoice_date": date, "currency": currency,
            "tax_rate": rate, "freight": freight, "invoice_discount": discount, "declared_total": declared or str(total),
            "created_by": by, "source_sha256": digest or sha(f"bytes-{iid}"), "source_filename": f"{iid}.pdf",
            "idempotency_key": f"idem-{iid}", "imported_at": at})
        for l in lines:
            row = {"invoice_line_id": l[0], "invoice_id": iid, "po_line_id": l[1], "quantity": l[2], "unit_price": l[3]}
            if len(l) > 4:
                row["line_amount"] = l[4]
            self.d["invoice_lines"].append(row)
        return iid

    def approve(self, iid: str, actor: str = "usr-rev01", role: str = "reviewer", at: str = "2026-10-06T15:30:00Z",
                decision: str = "approve", reason: str | None = None) -> str:
        self.n["ap"] += 1
        aid = f"ap-{self.n['ap']:03d}"
        row = {"approval_id": aid, "invoice_id": iid, "actor_id": actor, "actor_role": role, "decision": decision, "decided_at": at}
        if reason:
            row["reason"] = reason
        self.d["approvals"].append(row)
        return aid

    def export(self, batch: str, key: str, ids: list[str], at: str = "2026-10-07T08:00:00Z") -> None:
        self.d["export_requests"].append({"batch_id": batch, "idempotency_key": key, "invoice_ids": ids, "exported_at": at})

    def credit(self, cid: str, iid: str, amount: str) -> None:
        self.d["credit_notes"].append({"credit_id": cid, "invoice_id": iid, "credit_amount": amount})

    def data(self) -> dict[str, Any]:
        return copy.deepcopy(self.d)


def pipeline(inputs: dict[str, Any]):
    from invoicebridge import run_pipeline
    return run_pipeline(inputs)


@pytest.fixture
def db_url() -> Iterator[str]:
    import psycopg
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL is not set")
    with psycopg.connect(url) as conn:
        migrate.reset(conn)
        migrate.apply_migrations(conn)
    yield url


@pytest.fixture
def conn(db_url: str) -> Iterator[Any]:
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(db_url, row_factory=dict_row, autocommit=True) as c:
        yield c


@pytest.fixture
def client(db_url: str):
    from fastapi.testclient import TestClient
    with TestClient(create_app(), raise_server_exceptions=False) as c:
        yield c


def count(conn, table: str) -> int:
    return conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]  # table is a test constant


_seq = {"n": 0}


def current_dataset_version() -> str:
    """The dataset_version the database names now ("ds-test" when none): commands carry the current version, as a client
    that has just read the data would (a stale version is 409)."""
    import psycopg
    url = os.environ.get("DATABASE_URL")
    if not url:
        return "ds-test"
    with psycopg.connect(url) as c:
        row = c.execute("SELECT dataset_version FROM dataset_versions ORDER BY created_at DESC, dataset_version DESC LIMIT 1").fetchone()
    return row[0] if row else "ds-test"


def command(client, name: str, input_: dict[str, Any], key: str | None = None, headers: dict[str, str] | None = None,
            request_id: str = "req-test", dataset_version: str | None = None):
    """POST one command with a fresh idempotency key unless ``key`` is given (default actor: the clerk)."""
    if key is None:
        _seq["n"] += 1
        key = f"key-{os.getpid()}-{_seq['n']}"
    body = {"request_id": request_id, "dataset_version": dataset_version or current_dataset_version(),
            "idempotency_key": key, "input": input_}
    return client.post(f"{PREFIX}/commands/{name}", json=body, headers=CLERK if headers is None else headers)


def rule_ids(response) -> list[str]:
    return [d["rule_id"] for d in response.json()["error"]["details"]]


def get(client, path: str, **params):
    return client.get(f"{PREFIX}{path}", params=params)


def import_input(inv: dict[str, Any], lines: list[dict[str, Any]]) -> dict[str, Any]:
    """C01 input from a fixture invoice row and its lines."""
    keys = ("invoice_id", "vendor_id", "invoice_number", "invoice_date", "currency", "tax_rate", "freight", "invoice_discount",
            "declared_total", "source_sha256", "source_filename", "imported_at")
    return {**{k: inv[k] for k in keys}, "lines": [{k: l[k] for k in ("invoice_line_id", "po_line_id", "quantity", "unit_price", "line_amount") if k in l}
                                                   for l in lines]}


def actor(user: str, role: str) -> dict[str, str]:
    return {"X-Actor-Id": user, "X-Actor-Role": role}


def drive(client, conn, inputs: dict[str, Any]) -> dict[str, Any]:
    """Replay ``inputs`` through the API: reference data by the data load, then C01, C02, C03, C04 per invoice (in book
    order), C07 for each approval, C09 for each export request. Returns the HTTP status of every call by name."""
    seed.seed(conn, inputs, reference_only=True)
    lines: dict[str, list] = {}
    for l in inputs["invoice_lines"]:
        lines.setdefault(l["invoice_id"], []).append(l)
    log: dict[str, Any] = {}
    imported = []
    for inv in sorted(inputs["invoices"], key=lambda i: (i["imported_at"], i["invoice_id"])):
        r = command(client, "import-invoice", import_input(inv, lines.get(inv["invoice_id"], [])), key=inv["idempotency_key"],
                    headers=actor(inv["created_by"], "clerk"))
        log[f"import:{inv['invoice_id']}"] = r.status_code
        if r.status_code == 200:
            imported.append(inv)
    for inv in imported:
        if command(client, "validate-invoice", {"invoice_id": inv["invoice_id"]}).status_code != 200:
            raise AssertionError("validate failed")
    for inv in imported:
        r = command(client, "find-duplicates", {"invoice_id": inv["invoice_id"]})
        log[f"dups:{inv['invoice_id']}"] = r.status_code
    book_order = sorted(imported, key=lambda i: (i["invoice_date"], i["imported_at"], i["invoice_id"]))
    for inv in book_order:
        row = conn.execute("SELECT status FROM invoices WHERE invoice_id = %s", (inv["invoice_id"],)).fetchone()
        if row["status"] != "merged":
            r = command(client, "match-three-way", {"invoice_id": inv["invoice_id"]})
            log[f"match:{inv['invoice_id']}"] = r.status_code
    known = {i["invoice_id"] for i in imported}
    for a in sorted(inputs["approvals"], key=lambda a: (a["decided_at"], a["approval_id"])):
        if a["invoice_id"] in known and a["decision"] == "approve":
            r = command(client, "approve-invoice", {"invoice_id": a["invoice_id"], "approval_id": a["approval_id"], "decided_at": a["decided_at"]},
                        headers=actor(a["actor_id"], a["actor_role"]))
            log[f"approve:{a['approval_id']}"] = r.status_code
    for e in inputs["export_requests"]:
        r = command(client, "export-payable", {"batch_id": e["batch_id"], "invoice_ids": e["invoice_ids"], "exported_at": e["exported_at"]},
                    key=e["idempotency_key"], headers=REVIEWER)
        log[f"export:{e['idempotency_key']}:{e['exported_at']}"] = r.status_code
    return log


def random_world(seed: int) -> dict[str, Any]:
    """A seeded random population exercising every rule: cumulative consumption, several lines, a foreign currency, an
    unknown PO line, price and rounding differences, same-bytes and identity duplicates, reversed receipts, approvals
    (self, wrong role, over the limit, rejects), exports (repeats), credits and snapshot cutoffs."""
    import random
    rnd = random.Random(seed)
    w = World(price_per_unit=rnd.choice(["0.00", "0.00", "0.05"]), rounding_per_line=rnd.choice(["0.01", "0.02"]))
    lines_pool = [w.pol("pol-a", qty="40", price="20.00"), w.pol("pol-b", qty="30", price="7.50"),
                  w.pol("pol-c", qty="25.5", price="100.125", code="C"), w.pol("pol-e", po="po-2", qty="50", price="3.00")]
    days = [f"2026-10-{d:02d}" for d in range(2, 12)]
    for pl in lines_pool:
        for _ in range(rnd.randint(2, 5)):
            w.receipt(pl, str(rnd.choice([4, 6, 8, 12, "9.5", "0.3333"])), at=f"{rnd.choice(days)}T{rnd.randint(0, 23):02d}:00:00Z",
                      reversed=rnd.random() < 0.15)
    inv_ids = []
    for n in range(rnd.randint(4, 12)):
        iid = f"inv-{n + 1:03d}"
        lines = []
        for k in range(rnd.randint(1, 3)):
            pl = rnd.choice(lines_pool + (["pol-zzz"] if rnd.random() < 0.05 else []))
            base = {"pol-a": "20.00", "pol-b": "7.50", "pol-c": "100.125", "pol-e": "3.00"}.get(pl, "1.00")
            price = base if rnd.random() < 0.9 else rnd.choice(["20.01", "7.55", "100.130", "3.06", "2.95"])
            qty = str(rnd.choice([1, 2, 2, 3, 4, "1.5", "0.25", "2.7500"]))
            line = [f"{iid}-{k + 1}", pl, qty, price]
            if rnd.random() < 0.15:
                from decimal import ROUND_HALF_UP, Decimal
                line.append(str((Decimal(qty) * Decimal(price)).quantize(Decimal("0.01"), ROUND_HALF_UP) + Decimal(rnd.choice(["0", "0.01", "0.02", "-0.01"]))))
            lines.append(tuple(line))
        vendor, cur = ("ven-2", "EUR") if rnd.random() < 0.15 else ("ven-1", "USD")
        if rnd.random() < 0.04:
            cur = "EUR" if cur == "USD" else "USD"            # currency mismatch against the PO
        day = rnd.choice(days)
        number = rnd.choice([f"INV-{n}", f"INV-{n}", f"INV-{n}", f"inv {n}", f"INV-{n % 3}"])
        w.invoice(iid, lines, number=number, vendor=vendor, currency=cur, date=day,
                  at=f"{day}T{rnd.randint(0, 22):02d}:{rnd.randint(0, 59):02d}:00Z", rate=rnd.choice(["0.10", "0", "0.075", "0.2"]),
                  freight=rnd.choice(["0.00", "5.00", "1.25"]), discount=rnd.choice(["0.00", "0.00", "2.50"]),
                  by=rnd.choice(["usr-clerk01", "usr-clerk02", "usr-rev01"]),
                  digest=sha("shared") if rnd.random() < 0.06 else None)
        if rnd.random() < 0.12:
            last = w.d["invoices"][-1]
            from decimal import Decimal
            last["declared_total"] = str(Decimal(last["declared_total"]) + Decimal(rnd.choice(["0.01", "0.02", "0.03", "-0.02", "1.00"])))
        inv_ids.append(iid)
    for iid in inv_ids:
        if rnd.random() < 0.7:
            for _ in range(rnd.choice([1, 1, 2])):
                role = rnd.choice(["reviewer", "reviewer", "admin", "clerk"])
                actor_id = rnd.choice(["usr-rev01", "usr-rev02", "usr-clerk01", "usr-adm01"])
                reject = rnd.random() < 0.15
                w.approve(iid, actor=actor_id, role=role, at=f"2026-10-{rnd.randint(6, 14):02d}T{rnd.randint(0, 23):02d}:30:00Z",
                          decision="reject" if reject else "approve", reason="no" if reject else None)
    for k in range(rnd.randint(0, 4)):
        ids = rnd.sample(inv_ids + ["inv-nope"], rnd.randint(1, min(3, len(inv_ids))))
        w.export(f"bat-{rnd.randint(1, 3)}", f"key-{rnd.randint(1, 4)}", ids, at=f"2026-10-{rnd.randint(7, 15):02d}T08:00:00Z")
    for k in range(rnd.randint(0, 3)):
        w.credit(f"cn-{k + 1}", rnd.choice(inv_ids), rnd.choice(["1.00", "5.00", "10.00"]))
    w.d["snapshot_cutoffs"] = sorted({f"2026-10-{rnd.randint(3, 12):02d}T{rnd.randint(0, 23):02d}:00:00Z" for _ in range(rnd.randint(1, 3))})
    w.d["as_of"] = rnd.choice(["2026-10-26T00:00:00Z", "2026-10-10T12:00:00Z", "2026-10-07T00:00:00Z"])
    return w.data()


class Desk:
    """An API session over a seeded reference dataset (vendors, POs, receipts, policy): import, validate, match, approve ..."""

    def __init__(self, client, conn, world: World | None = None) -> None:
        self.client, self.conn = client, conn
        self.w = world or self.default_world()
        seed.seed(conn, self.w.data(), reference_only=True)
        self.n = 0

    @staticmethod
    def default_world() -> World:
        w = World()
        w.pol("pol-1", qty="10", price="20.00")
        w.receipt("pol-1", "6")
        return w

    def post(self, name: str, input_: dict[str, Any], who: dict[str, str] | None = None, **kw):
        return command(self.client, name, input_, headers=who, **kw)

    def imp(self, iid: str, lines: list[tuple] | None = None, who: dict[str, str] | None = None, key: str | None = None, **kw):
        """C01 as the clerk. ``lines``: (line id, po line, quantity, unit price). Header defaults: INV number = id, 10 % tax."""
        lines = lines or [(f"{iid}-1", "pol-1", "6", "20.00")]
        dataset_version = kw.pop("dataset_version", None)
        from decimal import ROUND_HALF_UP, Decimal
        raw = sum((Decimal(l[2]) * Decimal(l[3]) for l in lines), Decimal(0))
        rate = Decimal(kw.pop("tax_rate", "0.10"))
        total = raw.quantize(Decimal("0.01"), ROUND_HALF_UP) + (raw * rate).quantize(Decimal("0.01"), ROUND_HALF_UP) \
            + Decimal(kw.get("freight", "0.00")) - Decimal(kw.get("invoice_discount", "0.00"))
        body = {"invoice_id": iid, "vendor_id": "ven-1", "invoice_number": iid.upper(), "invoice_date": "2026-10-06", "currency": "USD",
                "tax_rate": str(rate), "freight": "0.00", "invoice_discount": "0.00", "declared_total": str(total),
                "source_sha256": sha(f"bytes-{iid}"), "source_filename": f"{iid}.pdf", "imported_at": "2026-10-06T09:00:00Z",
                "lines": [{"invoice_line_id": l[0], "po_line_id": l[1], "quantity": l[2], "unit_price": l[3]} for l in lines], **kw}
        return self.post("import-invoice", body, who or CLERK, key=key, dataset_version=dataset_version)

    def ready(self, iid: str, lines: list[tuple] | None = None, **kw) -> dict[str, Any]:
        """Import, validate and match one invoice; returns the match result."""
        r = self.imp(iid, lines, **kw)
        assert r.status_code == 200, r.text
        assert self.post("validate-invoice", {"invoice_id": iid}).status_code == 200
        m = self.post("match-three-way", {"invoice_id": iid})
        assert m.status_code == 200, m.text
        return m.json()["result"]

    def approve(self, iid: str, who: dict[str, str] | None = None, **kw):
        return self.post("approve-invoice", {"invoice_id": iid, **kw}, who or REVIEWER)

    def status(self, iid: str) -> str:
        return self.conn.execute("SELECT status FROM invoices WHERE invoice_id = %s", (iid,)).fetchone()["status"]
