"""The project's check: recount the headline numbers from the raw CSV in pandas (no dbt, no SQL) and compare
them with the dbt marts exported in results/. dbt's own 31 tests run with `dbt build`; this checks the logic
from the outside.

    ./venv/bin/python check.py
"""
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent


def main():
    raw = pd.read_csv(HERE / "data" / "raw" / "online_retail_ii.csv", dtype=str, keep_default_na=False)
    assert len(raw) == 1_067_371
    keep = ~((raw["sheet"] == "Year 2009-2010") & (raw["invoice_date"] >= "2010-12-01"))
    d = raw[keep].drop(columns="sheet").drop_duplicates()
    assert keep.sum() == 1_044_848 and len(d) == 1_033_036, (keep.sum(), len(d))

    d = d.assign(quantity=d["quantity"].astype(int), price=d["price"].astype(float),
                 month=d["invoice_date"].str[:7], amount=lambda x: x["quantity"] * x["price"])
    product = d["stock_code"].str.match(r"^\d{5}") | d["stock_code"].str.startswith("DCGS") | d["stock_code"].isin(["PADS", "SP1002"])
    normal = ~d["invoice"].str.startswith(("C", "A"))
    sales = d[normal & product & (d["quantity"] > 0) & (d["price"] > 0)]
    cancelled = d[d["invoice"].str.startswith("C")]

    monthly = pd.read_csv(HERE / "results" / "monthly_revenue.csv")
    monthly["month"] = monthly["month"].str[:7]
    m = monthly.set_index("month")
    assert len(sales) == 1_003_357
    assert abs(sales["amount"].sum() - m["revenue"].sum()) < 0.01
    assert abs(-cancelled["amount"].sum() - m["cancelled_value"].sum()) < 0.01
    by_month = sales.groupby("month")["amount"].sum()
    assert (by_month - m["revenue"]).abs().max() < 0.01, "monthly revenue differs"
    assert (sales.groupby("month")["invoice"].nunique() == m["orders"]).all()

    known = sales[sales["customer_id"] != ""]
    first = known.groupby("customer_id")["month"].min()
    assert first.size == 5_852
    assert (first.value_counts().sort_index() == m.loc[first.value_counts().sort_index().index, "new_customers"]).all()

    cohorts = pd.read_csv(HERE / "results" / "cohort_retention.csv")
    cohorts["cohort_month"] = cohorts["cohort_month"].str[:7]
    jan = first[first == "2010-01"].index
    back = known[known["customer_id"].isin(jan) & (known["month"] == "2010-02")]["customer_id"].nunique()
    row = cohorts[(cohorts["cohort_month"] == "2010-01") & (cohorts["months_since_first"] == 1)].iloc[0]
    assert row["cohort_size"] == len(jan) and row["active_customers"] == back

    guest = sales.loc[sales["customer_id"] == "", "amount"].sum() / sales["amount"].sum()
    print(f"OK: 1,033,036 lines after the sheet overlap and repeats; {len(sales):,} sale lines = "
          f"£{sales['amount'].sum():,.2f} matches dbt by month; {first.size:,} customers and new-customer counts match; "
          f"Jan 2010 cohort {len(jan)} -> {back} back in Feb; guest share {guest:.1%}")


if __name__ == "__main__":
    main()
