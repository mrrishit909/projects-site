"""Synthetic data generator: determinism, shapes, sizes, injected defects, designed relationships."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "domain", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_spec = importlib.util.spec_from_file_location("ra_generate", ROOT / "data" / "generate.py")
gen = importlib.util.module_from_spec(_spec)
sys.modules["ra_generate"] = gen
_spec.loader.exec_module(gen)

from revenue_atlas.metrics import group_metrics  # noqa: E402
from revenue_atlas.pipeline import run_pipeline  # noqa: E402

SEED = 20261026
GOLDEN = json.loads((ROOT / "tests" / "fixtures" / "golden" / "inputs.json").read_text())


def _run(tmp: Path):
    out, meta = tmp / "out", tmp / "meta"
    manifest = gen.write_all(SEED, out, meta)
    return out, meta, manifest


def _load(out: Path) -> dict:
    data = {"contract": "v1", "reporting_currency": "USD"}
    for name in gen.ENTITIES:
        doc = json.loads((out / f"{name}.json").read_text())
        assert doc["entity"] == name
        data[name] = doc["rows"]
    return data


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("gen")
    out, meta, manifest = _run(tmp)
    return {"out": out, "meta": meta, "manifest": manifest, "data": _load(out),
            "inj": json.loads((meta / "injection-manifest.json").read_text()),
            "events": json.loads((meta / "injection-events.json").read_text())["events"]}


@pytest.fixture(scope="module")
def inputs(built):
    return {k: v for k, v in built["data"].items()}


@pytest.fixture(scope="module")
def result(inputs):
    return run_pipeline(inputs, include_returns=True)


def test_two_runs_give_identical_files_and_hash(tmp_path, built):
    out2, meta2, m2 = _run(tmp_path)
    assert m2["dataset_hash"] == built["manifest"]["dataset_hash"]
    for name in gen.ENTITIES:
        assert (out2 / f"{name}.json").read_bytes() == (built["out"] / f"{name}.json").read_bytes()
    assert (meta2 / "injection-events.json").read_bytes() == (built["meta"] / "injection-events.json").read_bytes()
    assert (meta2 / "injection-manifest.json").read_bytes() == (built["meta"] / "injection-manifest.json").read_bytes()


def test_manifest_fields_and_hash_recipe(built):
    m = json.loads((built["out"] / "manifest.json").read_text())
    assert m["dataset_version"] == f"ra-{SEED}-20261026" and m["contract_version"] == "v1"
    assert m["generator"]["name"] == "generate.py" and m["generator"]["seed"] == SEED
    assert m["generator"]["parameters"]["orders"] == 2400
    assert m["injection_manifest"] == "injection-manifest.json"
    assert len(m["designed_relationships"]) == 3
    datetime.strptime(m["generated_at"], "%Y-%m-%dT%H:%M:%SZ")
    h = hashlib.sha256()
    for name in sorted(gen.ENTITIES):
        rows = json.loads((built["out"] / f"{name}.json").read_text())["rows"]
        h.update(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode())
    assert h.hexdigest() == m["dataset_hash"]
    assert m["row_counts"] == {n: len(built["data"][n]) for n in gen.ENTITIES}
    assert (built["out"] / "injection-manifest.json").read_text() == (built["meta"] / "injection-manifest.json").read_text()


def test_different_seed_changes_hash(tmp_path, built):
    m = gen.write_all(SEED + 1, tmp_path / "o", tmp_path / "m")
    assert m["dataset_hash"] != built["manifest"]["dataset_hash"]


def test_shapes_match_golden_and_formats(built):
    data = built["data"]
    for name, g in GOLDEN.items():
        if isinstance(g, list):
            assert all(set(r) == set(g[0]) for r in data[name]), name
    money = lambda s: isinstance(s, str) and len(s.split(".")[-1]) == 2  # noqa: E731
    assert all(money(r["unit_price"]) for r in data["order_lines"])
    assert all(money(r["discount_amount"]) and money(r["approved_by"] and "0.00") for r in data["discounts"])
    assert all(money(r["shipping_cost"]) for r in data["shipments"])
    assert all(money(r["credit_amount"]) for r in data["returns"])
    assert all(money(r["unit_cost"]) for r in data["cost_versions"])
    assert all(money(r["quota_amount"]) for r in data["quotas"])
    assert all(len(r["rate"].split(".")[1]) == 6 for r in data["exchange_rates"])
    assert all(isinstance(r["quantity"], int) for r in data["order_lines"])
    assert all(isinstance(r["shipped_quantity"], int) for r in data["shipment_lines"])
    assert all(r["reason_code"] in {"volume", "promo", "goodwill", "price_match"} for r in data["discounts"])
    assert {r["segment"] for r in data["customers"]} == {"smb", "mid_market", "enterprise"}
    assert {r["region_id"] for r in data["customers"]} == set(gen.REGIONS)
    assert {r["category_id"] for r in data["products"]} == set(gen.CATEGORIES)
    assert max(len(r["customer_name"]) for r in data["customers"]) >= 60


def test_counts_within_spec_ranges(built):
    c = built["manifest"]["row_counts"]
    d = built["data"]
    assert len({r["customer_id"] for r in d["customers"]}) == 48
    assert c["products"] == 36 and c["orders"] == 2400
    assert 5500 <= c["order_lines"] <= 6500
    assert 2300 <= c["shipments"] <= 3000
    assert 0.30 <= c["discounts"] / c["order_lines"] <= 0.40
    shipped_lines = len(d["shipment_lines"])
    assert 0.04 <= c["returns"] / shipped_lines <= 0.08
    assert len({r["rep_id"] for r in d["quotas"]}) == 8 and c["quotas"] == 8 * 8
    foreign = {o["customer_id"] for o in d["orders"] if o["currency"] in ("EUR", "CAD")}
    assert 0.15 <= len(foreign) / 48 <= 0.25
    cancelled = [o for o in d["orders"] if o["status"] == "cancelled"]
    assert len(cancelled) == 5
    shipped_orders = {s["order_id"] for s in d["shipments"]}
    assert all(o["order_id"] not in shipped_orders for o in cancelled)
    assert all(o["order_id"] in shipped_orders for o in d["orders"] if o["status"] != "cancelled")
    per_order = {}
    for s in d["shipments"]:
        per_order[s["order_id"]] = per_order.get(s["order_id"], 0) + 1
    assert 0.10 <= sum(1 for v in per_order.values() if v == 2) / len(per_order) <= 0.30
    assert sum(p.stat().st_size for p in built["out"].glob("*.json")) < 5_000_000
    for r in d["shipments"]:
        assert "2024-10-01" <= r["shipped_at"][:10] <= "2026-09-30"


def test_fx_covers_every_shipment_and_credit_date_except_injected_two(built):
    d = built["data"]
    have = {(r["currency"], r["rate_date"]) for r in d["exchange_rates"]}
    need = {(s["currency"], s["shipped_at"][:10]) for s in d["shipments"] if s["currency"] in ("EUR", "CAD")}
    sl_ship = {s["shipment_line_id"]: s["shipment_id"] for s in d["shipment_lines"]}
    ship_ccy = {s["shipment_id"]: s["currency"] for s in d["shipments"]}
    need |= {(ship_ccy[sl_ship[r["shipment_line_id"]]], r["credit_date"]) for r in d["returns"]
             if ship_ccy[sl_ship[r["shipment_line_id"]]] in ("EUR", "CAD")}
    missing = need - have
    injected = {(m["currency"], m["rate_date"]) for m in built["inj"]["injections"][3]["missing"]}
    assert len(injected) == 2
    shipment_needs = {(s["currency"], s["shipped_at"][:10]) for s in d["shipments"]
                      if s["currency"] in ("EUR", "CAD")}
    assert injected <= shipment_needs
    # every shipment date outside the two injected gaps has a rate
    assert shipment_needs - have == injected
    # credit dates: only a return credited on an injected date may lack a rate
    assert missing <= injected
    days = (date(2026, 9, 30) - date(2024, 10, 1)).days + 1
    assert len(d["exchange_rates"]) == 2 * days - 2
    assert {r["reporting_currency"] for r in d["exchange_rates"]} == {"USD"}


def test_injection_manifest_lists_every_defect(built):
    inj = built["inj"]["injections"]
    assert [i["id"] for i in inj] == [f"INJ-{n:02d}" for n in range(1, 12)]
    for i in inj:
        assert {"id", "test", "entity", "record_ids", "description", "expected_handling"} <= set(i)
        assert i["record_ids"]
    ev = built["events"]
    assert len([e for e in ev if e["injection"] == "INJ-06"]) == 4
    assert len([e for e in ev if e["injection"] == "INJ-07"]) == 1
    assert len([e for e in ev if e["injection"] == "INJ-05" and e["command"] == "ingest-sales"]) == 1
    ret_ids = {r["shipment_line_id"] for r in built["data"]["returns"]}
    for e in ev:
        if e["command"] == "post-a-partial-return":
            assert e["input"]["shipment_line_id"] not in ret_ids
    # events are not in the entity files
    sl_ids = [s["shipment_line_id"] for s in built["data"]["shipment_lines"]]
    assert len(sl_ids) == len(set(sl_ids))


def test_pipeline_ingest_rejects_exactly_three_malformed_orders(result, built):
    rej = result.ingest.rejected
    assert {r.reason_code for r in rej} <= {"CURRENCY_NOT_ISO4217"}
    bad = [r for r in rej if r.entity == "orders"]
    assert sorted(r.id for r in bad) == sorted(built["inj"]["injections"][0]["record_ids"])
    assert sorted(r.raw_row["currency"] for r in bad) == ["EU", "US$", "usd"]
    bad_ids = {r.id for r in bad}
    for r in rej:
        if r.entity == "order_lines":
            assert r.raw_row["order_id"] in bad_ids
    assert any(r.entity == "shipment_lines" for r in rej) and any(r.entity == "shipments" for r in rej)


def test_pipeline_quarantines_designed_defects(result, built):
    q = {}
    for r in result.quarantined:
        q.setdefault(r.reason_code, set()).add(r.id)
    by = {i["id"]: i for i in built["inj"]["injections"]}
    assert set(by["INJ-02"]["affected_shipment_line_ids"]) <= q["COST_VERSION_AMBIGUOUS"]
    assert set(by["INJ-03"]["affected_shipment_line_ids"]) <= q["COST_VERSION_MISSING"]
    fx_ship = set(by["INJ-04"]["affected_shipment_ids"])
    sl_to_ship = {s["shipment_line_id"]: s["shipment_id"] for s in built["data"]["shipment_lines"]}
    assert fx_ship and {s for s in q["FX_RATE_MISSING"] if s in sl_to_ship and sl_to_ship[s] in fx_ship}
    assert len(by["INJ-02"]["affected_shipment_line_ids"]) > 0 and len(by["INJ-03"]["affected_shipment_line_ids"]) > 0
    # returns on quarantined lines cascade as SHIPMENT_LINE_UNKNOWN; nothing else is quarantined
    assert set(q) <= {"COST_VERSION_AMBIGUOUS", "COST_VERSION_MISSING", "FX_RATE_MISSING", "SHIPMENT_LINE_UNKNOWN"}
    quarantined_lines = q["COST_VERSION_AMBIGUOUS"] | q["COST_VERSION_MISSING"] | q["FX_RATE_MISSING"]
    ret_sl = {r["return_id"]: r["shipment_line_id"] for r in built["data"]["returns"]}
    assert all(ret_sl[i] in quarantined_lines for i in q["SHIPMENT_LINE_UNKNOWN"])


def test_contribution_margin_is_non_null_string_and_residual_zero(result):
    cm = result.metrics["contribution_margin"]
    assert isinstance(cm, str) and cm != ""
    assert result.metrics["allocation_residual"] == "0.00"
    assert result.excluded_shipment_lines == []


def test_unassigned_and_territory_change_show_up(result, built):
    regions = {f.region_id for f in result.facts}
    assert "UNASSIGNED" in regions
    un = built["inj"]["injections"][8]["record_ids"]
    assert {f.customer_id for f in result.facts if f.region_id == "UNASSIGNED"} == set(un)
    for cid in built["inj"]["injections"][7]["record_ids"]:
        assert len({f.region_id for f in result.facts if f.customer_id == cid}) == 2


def test_zero_gross_orders_carry_freight(result, built):
    ids = set(built["inj"]["injections"][10]["record_ids"])
    fs = [f for f in result.facts if f.order_id in ids]
    assert fs and all(str(f.gross_sales) in ("0", "0.00", "0.000000") or f.gross_sales == 0 for f in fs)
    assert sum(f.freight for f in fs) > 0


def _rate(m, num, den):
    return float(m[num]) / float(m[den])


def test_designed_relationship_west_discount_doubles(result):
    from revenue_atlas.metrics import Window
    cut = datetime(2026, 3, 1, tzinfo=timezone.utc)
    start = datetime(2024, 10, 1, tzinfo=timezone.utc)
    end = datetime(2026, 10, 1, tzinfo=timezone.utc)
    before = group_metrics(result.facts, lambda f: f.region_id, (start, cut))
    after = group_metrics(result.facts, lambda f: f.region_id, (cut, end))
    w_b, w_a = float(before["reg-west"]["discount_rate"]), float(after["reg-west"]["discount_rate"])
    assert w_a / w_b > 1.6, (w_b, w_a)
    for r in ("reg-north", "reg-south", "reg-east"):
        ratio = float(after[r]["discount_rate"]) / float(before[r]["discount_rate"])
        assert 0.7 < ratio < 1.35, (r, ratio)


def test_designed_relationship_fixtures_cost_rises_18_percent(built):
    d = built["data"]
    cat = {p["product_id"]: p["category_id"] for p in d["products"]}
    def avg_ratio(cat_id):
        before, after = {}, {}
        for cv in d["cost_versions"]:
            if cat[cv["product_id"]] != cat_id or cv["valid_to"] is None and cv["valid_from"] < "2026-01-01":
                continue
            if cv["valid_from"] <= "2025-12-31" and (cv["valid_to"] or "9999") > "2025-12-31":
                before[cv["product_id"]] = float(cv["unit_cost"])
            if cv["valid_from"] <= "2026-01-31" and (cv["valid_to"] or "9999") > "2026-01-31":
                after[cv["product_id"]] = float(cv["unit_cost"])
        ks = before.keys() & after.keys()
        return sum(after[k] for k in ks) / sum(before[k] for k in ks)
    assert 1.15 <= avg_ratio("cat-fixtures") <= 1.21
    for c in ("cat-apparel", "cat-tools", "cat-packaging", "cat-safety", "cat-office"):
        assert avg_ratio(c) < 1.05
    # prices are constant per product and currency
    prices = {}
    ord_ccy = {o["order_id"]: o["currency"] for o in d["orders"]}
    prod_of = {}
    for ln in d["order_lines"]:
        if ln["unit_price"] == "0.00":
            continue
        prices.setdefault((ln["product_id"], ord_ccy[ln["order_id"]]), set()).add(ln["unit_price"])
    assert all(len(v) == 1 for v in prices.values())


def test_designed_relationship_enterprise_apparel_returns_3x(result, built):
    d = built["data"]
    seg = {}
    for c in d["customers"]:
        seg[c["customer_id"]] = c["segment"]
    cat = {p["product_id"]: p["category_id"] for p in d["products"]}
    ea_u = ea_r = ot_u = ot_r = 0
    for f in result.facts:
        if seg[f.customer_id] == "enterprise" and cat[f.product_id] == "cat-apparel":
            ea_u += f.shipped_quantity
            ea_r += f.returned_quantity
        else:
            ot_u += f.shipped_quantity
            ot_r += f.returned_quantity
    assert ea_u > 0 and ot_u > 0
    ratio = (ea_r / ea_u) / (ot_r / ot_u)
    assert 2.0 <= ratio <= 4.5, ratio


@pytest.fixture
def seeded_conn():
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL is not set")
    import psycopg
    from data import migrate
    with psycopg.connect(url, autocommit=True) as c:
        migrate.reset(c)
        migrate.apply_migrations(c)
        yield c


def test_seed_generated_data_into_postgres(seeded_conn, inputs):
    from data import seed
    from revenue_atlas.ingest import validate_batch
    out = seed.seed(seeded_conn, inputs)
    ing = validate_batch(inputs)
    assert out["skipped"] == len(ing.rejected) and out["skipped"] > 3
    for ent in seed.INSERT_ORDER:
        n = seeded_conn.execute(f"SELECT count(*) FROM {ent}").fetchone()[0]  # ent is a constant
        assert n == len(ing.accepted[ent]) == out["inserted"][ent], ent
    assert seeded_conn.execute("SELECT count(*) FROM orders").fetchone()[0] == 2400 - 3
    assert seeded_conn.execute("SELECT count(*) FROM customers").fetchone()[0] == len(inputs["customers"])
    second = seed.seed(seeded_conn, inputs)
    assert all(v == 0 for v in second["inserted"].values())
