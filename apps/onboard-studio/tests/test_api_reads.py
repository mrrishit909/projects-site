"""Reads: GET /data/{entity} (none, one, stable pages, invalid filter, reversed window) and GET /metrics."""
import pytest

from api.app import PREFIX

from support_db import client, conn, count, db_url, drive_to_completion, golden_expected, rule_ids, seeded  # noqa: F401


def get(client, path, **params):
    return client.get(f"{PREFIX}{path}", params=params)


def add_orgs(conn, n):
    for i in range(n):
        conn.execute("INSERT INTO organizations VALUES (%s, %s, %s, %s, %s)",
                     (f"org-{i + 10:03d}", f"Org {i}", "smb" if i % 2 else "ent", "emea",
                      f"2026-02-{i + 1:02d}T00:00:00Z"))


def test_read_none(client):
    r = get(client, "/data/cases")
    assert r.status_code == 200
    body = r.json()
    assert body["data"] == [] and body["meta"]["total_count"] == 0 and body["meta"]["next_cursor"] is None
    assert body["meta"]["dataset_version"] == "unversioned" and body["meta"]["contract_version"] == "v1"
    assert body["warnings"] == []


def test_read_one(client, seeded):
    r = get(client, "/data/cases")
    body = r.json()
    assert [c["case_id"] for c in body["data"]] == ["case-001"] and body["meta"]["total_count"] == 1
    assert body["data"][0]["opened_at"] == "2026-03-06T16:00:00Z" and body["data"][0]["completed_at"] == "2026-03-09T10:00:00Z"
    assert body["meta"]["dataset_version"].startswith("ds-")
    sla = get(client, "/data/sla_rules").json()["data"][0]
    assert sla["business_minutes"] == "480" and sla["pause_policy"] == ["customer_info_requested"]


def test_pages_are_stable_with_no_duplicates_or_gaps(client, conn):
    add_orgs(conn, 7)
    seen, cursor, pages = [], None, 0
    while True:
        params = {"limit": 3} | ({"cursor": cursor} if cursor else {})
        body = get(client, "/data/organizations", **params).json()
        seen += [o["organization_id"] for o in body["data"]]
        pages += 1
        assert body["meta"]["total_count"] == 7
        cursor = body["meta"]["next_cursor"]
        if cursor is None:
            break
    assert pages == 3 and seen == [f"org-{i + 10:03d}" for i in range(7)]
    again = get(client, "/data/organizations", limit=3).json()["data"]
    assert [o["organization_id"] for o in again] == seen[:3]          # the same request gives the same page


def test_pages_stay_stable_when_a_row_is_added_between_requests(client, conn):
    add_orgs(conn, 4)
    first = get(client, "/data/organizations", limit=2).json()
    conn.execute("INSERT INTO organizations VALUES ('org-000', 'Early', 'smb', 'emea', '2026-01-01T00:00:00Z')")
    second = get(client, "/data/organizations", limit=2, cursor=first["meta"]["next_cursor"]).json()
    ids = [o["organization_id"] for o in first["data"] + second["data"]]
    assert ids == ["org-010", "org-011", "org-012", "org-013"]       # the later insert sorts before the cursor


def test_exact_page_boundary_has_no_next_cursor(client, conn):
    add_orgs(conn, 4)
    body = get(client, "/data/organizations", limit=4).json()
    assert len(body["data"]) == 4 and body["meta"]["next_cursor"] is None


def test_equality_filters_and_time_window(client, conn):
    add_orgs(conn, 6)
    body = get(client, "/data/organizations", segment="smb").json()
    assert body["meta"]["total_count"] == 3 and {o["segment"] for o in body["data"]} == {"smb"}
    body = get(client, "/data/organizations", **{"from": "2026-02-02", "to": "2026-02-04"}).json()
    assert [o["organization_id"] for o in body["data"]] == ["org-011", "org-012"]      # [from, to) is half-open
    assert body["meta"]["applied_filters"]["from"] == "2026-02-02T00:00:00Z"
    assert get(client, "/data/organizations", segment="nothing").json()["data"] == []


def test_filters_on_cases_and_required_flag(client, seeded):
    assert get(client, "/data/cases", status="completed").json()["meta"]["total_count"] == 1
    assert get(client, "/data/cases", status="open").json()["meta"]["total_count"] == 0
    assert get(client, "/data/step_definitions", required="true").json()["meta"]["total_count"] == 2
    r = get(client, "/data/step_definitions", required="maybe")
    assert r.status_code == 422 and rule_ids(r) == ["INVALID_FILTER"]


@pytest.mark.parametrize("path,params,status,rule", [
    ("/data/cases", {"colour": "red"}, 422, "INVALID_FILTER"),
    ("/data/cases", {"from": "not-a-date"}, 422, "INVALID_FILTER"),
    ("/data/cases", {"to": "2026-13-45"}, 422, "INVALID_FILTER"),
    ("/data/cases", {"cursor": "%%%"}, 422, "INVALID_CURSOR"),
    ("/data/cases", {"cursor": "WyJhIiwiYiJd"}, 422, "INVALID_CURSOR"),      # wrong width for this entity
    ("/data/cases", {"limit": 0}, 422, None),
    ("/data/cases", {"limit": 201}, 422, None),
    ("/data/cases", {"limit": "many"}, 422, None),
    ("/data/step_definitions", {"from": "2026-01-01"}, 422, "FILTER_NOT_SUPPORTED"),
    ("/data/nonsense", {}, 404, "ENTITY_UNKNOWN"),
])
def test_invalid_reads(client, path, params, status, rule):
    r = get(client, path, **params)
    assert r.status_code == status
    if rule:
        assert rule_ids(r) == [rule]
    assert "request_id" in r.json() and "error" in r.json()


def test_reversed_and_empty_windows_are_invalid(client, seeded):
    for lo, hi in (("2026-03-10", "2026-03-01"), ("2026-03-10", "2026-03-10")):
        r = get(client, "/data/cases", **{"from": lo, "to": hi})
        assert r.status_code == 422 and rule_ids(r) == ["INVALID_WINDOW"]
        r = get(client, "/metrics", **{"from": lo, "to": hi})
        assert r.status_code == 422 and rule_ids(r) == ["INVALID_WINDOW"]


# --- metrics -------------------------------------------------------------------------------------

CUTS = "2026-03-07T12:00:00Z,2026-03-09T12:00:00Z"


@pytest.mark.parametrize("state", ["pause_eligible", "pause_not_eligible"])
def test_metrics_equal_expected_golden_through_the_api(client, seeded, state):
    r = get(client, "/metrics", cutoff=CUTS, state=state)
    assert r.status_code == 200
    assert r.json()["data"]["metrics"] == golden_expected()["states"][state]["metrics"]
    assert r.json()["meta"]["applied_filters"]["state"] == state


def test_metrics_without_state_use_the_configured_policy(client, seeded):
    m = get(client, "/metrics", cutoff=CUTS).json()["data"]["metrics"]
    assert m == golden_expected()["states"]["pause_eligible"]["metrics"]


def test_metrics_window_is_half_open_on_opened_at(client, seeded):
    opened = "2026-03-06T16:00:00Z"
    assert get(client, "/metrics", **{"from": opened}).json()["data"]["metrics"]["completed_eligible_cases"] == 1
    assert get(client, "/metrics", **{"to": opened}).json()["data"]["metrics"]["empty_population"] is True
    assert get(client, "/metrics", **{"from": "2026-03-06T16:00:01Z"}).json()["meta"]["total_count"] == 0


def test_metrics_default_cutoff_is_now(client, seeded):
    m = get(client, "/metrics").json()["data"]["metrics"]
    assert list(m["open_backlog_at_cutoff"].values()) == [0]


@pytest.mark.parametrize("by,keys", [("organization", ["org-001"]), ("segment", ["smb"]), ("region", ["emea"]),
                                     ("workflow_version", ["wfv-001"])])
def test_metrics_group_by(client, seeded, by, keys):
    body = get(client, "/metrics", group_by=by, cutoff=CUTS).json()["data"]
    assert body["group_by"] == by and list(body["groups"]) == keys
    assert body["groups"][keys[0]]["business_cycle_time_hours"] == "2.0000"


def test_metrics_group_by_splits_a_second_organization(client, seeded, conn):
    conn.execute("INSERT INTO organizations VALUES ('org-002', 'Other', 'ent', 'apac', '2026-02-01T00:00:00Z')")
    drive_to_completion(client)       # case-100 belongs to org-001; retarget it to org-002 before grouping
    conn.execute("ALTER TABLE cases DISABLE TRIGGER cases_no_reopen")
    conn.execute("UPDATE cases SET organization_id = 'org-002' WHERE case_id = 'case-100'")
    conn.execute("ALTER TABLE cases ENABLE TRIGGER cases_no_reopen")
    groups = get(client, "/metrics", group_by="segment").json()["data"]["groups"]
    assert list(groups) == ["ent", "smb"]
    assert groups["ent"]["business_cycle_time_hours"] == "0.7500" and groups["smb"]["business_cycle_time_hours"] == "2.0000"


@pytest.mark.parametrize("params,rule", [({"group_by": "colour"}, "INVALID_GROUP_BY"), ({"state": "maybe"}, "INVALID_STATE"),
                                         ({"cutoff": "soon"}, "INVALID_FILTER"), ({"from": "x"}, "INVALID_FILTER")])
def test_metrics_invalid_parameters(client, seeded, params, rule):
    r = get(client, "/metrics", **params)
    assert r.status_code == 422 and rule_ids(r) == [rule]


def test_metrics_report_the_rejected_rows_and_flag_pauses(client, conn):
    from data import seed
    from support_db import golden_inputs
    seed.seed(conn, golden_inputs("variant-rejected"))
    body = get(client, "/metrics", cutoff=CUTS).json()
    assert body["meta"]["exclusions"]["rejected_records"] == 10
    conn.execute("UPDATE waiting_intervals SET starts_at = '2026-03-07T10:00:00Z', ends_at = '2026-03-08T10:00:00Z'")
    body = get(client, "/metrics", cutoff=CUTS).json()
    assert [w["code"] for w in body["warnings"]] == ["PAUSE_OUTSIDE_WORKING_INTERVAL"]
    assert body["data"]["metrics"]["paused_business_overlap_hours"] == "0.0000"


def test_audit_events_are_readable_and_filterable(client, seeded):
    from support_db import open_case
    open_case(client)
    body = get(client, "/data/audit_events", action="create-case").json()
    assert body["meta"]["total_count"] == 1 and body["data"][0]["entity_id"] == "case-100"
    assert body["data"][0]["occurred_at"].endswith("Z")
