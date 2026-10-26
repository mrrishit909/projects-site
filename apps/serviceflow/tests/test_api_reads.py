"""Reads through the HTTP API: entity pages, filters, windows, cursors and the metrics endpoint."""
import pytest

from api.app import PREFIX
from serviceflow.contract import GROUP_KEYS, METRIC_KEYS

from data import seed
from support_db import World, at, client, conn, db_url, get, golden_expected, golden_inputs, load, rule_ids, seeded  # noqa: F401

CUTS = ",".join(golden_inputs()["backlog_cutoffs"])
WINDOW = {"from": golden_inputs()["window_start"], "to": golden_inputs()["window_end"]}


def many_tickets(n=7) -> World:
    w = World(window=(0, 480))
    for i in range(1, n + 1):
        w.ticket(f"t-{i:02d}", i * 10, priority="P1" if i % 3 == 0 else "P2", channel="chat" if i % 2 else "email",
                 queue="q-1" if i % 2 else "q-2")
    return w


# --- entities ---------------------------------------------------------------------------------------------------

def test_every_entity_is_readable_and_ordered_by_key(client, seeded):
    for entity, key in (("customers", "customer_id"), ("queues", "queue_id"), ("tickets", "ticket_id"),
                        ("ticket_events", "event_id"), ("agents", "agent_id"), ("skills", "skill_id"),
                        ("agent_skills", "agent_skill_id"), ("shifts", "shift_id"), ("sla_policies", "sla_policy_id"),
                        ("surveys", "survey_id"), ("simulation_runs", "simulation_id"), ("dataset_versions", "dataset_version")):
        body = get(client, f"/data/{entity}").json()
        keys = [r[key] for r in body["data"]]
        assert keys == sorted(keys) and body["meta"]["total_count"] == len(keys) > 0, entity
    assert get(client, "/data/queue_skills").json()["data"] == [{"queue_id": "q-001", "skill_id": "s-001"}]


def test_envelope_meta_and_event_columns(client, seeded):
    body = get(client, "/data/ticket_events", limit=1).json()
    assert set(body) == {"data", "meta", "warnings"}
    assert set(body["data"][0]) == {"event_id", "ticket_id", "event_type", "occurred_at", "actor_id", "queue_id", "agent_id"}
    assert body["data"][0]["occurred_at"] == "2026-07-06T09:00:00Z"
    m = body["meta"]
    assert m["contract_version"] == 1 and m["total_count"] == 18 and m["next_cursor"] and m["dataset_version"].startswith("ds-")
    assert {"generated_at", "applied_filters", "exclusions", "code_sha"} <= set(m)


def test_paging_has_no_duplicates_or_gaps(client, conn):
    load(conn, many_tickets(7))
    seen, cursor = [], None
    while True:
        params = {"limit": 3, **({"cursor": cursor} if cursor else {})}
        body = get(client, "/data/tickets", **params).json()
        seen += [t["ticket_id"] for t in body["data"]]
        cursor = body["meta"]["next_cursor"]
        if not cursor:
            break
    assert seen == [f"t-{i:02d}" for i in range(1, 8)]


def test_exact_page_boundary_has_no_next_cursor(client, conn):
    load(conn, many_tickets(4))
    body = get(client, "/data/tickets", limit=4).json()
    assert len(body["data"]) == 4 and body["meta"]["next_cursor"] is None


def test_a_row_inserted_before_the_cursor_does_not_shift_the_next_page(client, conn):
    load(conn, many_tickets(6))
    first = get(client, "/data/tickets", limit=2).json()
    conn.execute("INSERT INTO tickets VALUES ('t-000', 'c-1', 'q-1', 'P2', now(), 'email')")
    second = get(client, "/data/tickets", limit=2, cursor=first["meta"]["next_cursor"]).json()
    assert [t["ticket_id"] for t in first["data"] + second["data"]] == ["t-01", "t-02", "t-03", "t-04"]


def test_equality_filters_and_the_half_open_time_window(client, conn):
    load(conn, many_tickets(6))
    body = get(client, "/data/tickets", priority="P1").json()
    assert [t["ticket_id"] for t in body["data"]] == ["t-03", "t-06"] and body["meta"]["total_count"] == 2
    body = get(client, "/data/tickets", **{"from": at(20), "to": at(40)}).json()
    assert [t["ticket_id"] for t in body["data"]] == ["t-02", "t-03"]                  # [from, to): minute 40 is out
    assert body["meta"]["applied_filters"]["from"] == "2026-07-06T09:20:00Z"
    assert get(client, "/data/tickets", channel="nothing").json()["data"] == []
    body = get(client, "/data/ticket_events", event_type="created", ticket_id="t-02").json()
    assert len(body["data"]) == 1
    assert get(client, "/data/queues", active="true").json()["meta"]["total_count"] == 2
    assert get(client, "/data/agents", active="false").json()["data"] == []


def test_simulation_events_keep_four_decimals(client, seeded):
    rows = get(client, "/data/simulation_events", event_type="resolved").json()["data"]
    assert [(r["simulation_event_id"], r["event_at"]) for r in rows] == [("se-004", "10.0000"), ("se-005", "20.0000"), ("se-006", "30.0000")]
    assert get(client, "/data/simulation_runs").json()["data"][0]["warmup_minutes"] == "0.0000"


def test_rejected_records_are_readable_with_their_raw_rows(client, conn):
    seed.seed(conn, golden_inputs("variant-rejected"))
    body = get(client, "/data/rejected_records", reason_code="AGENT_NOT_QUALIFIED").json()
    assert [(r["entity"], r["id"]) for r in body["data"]] == [("tickets", "t-004")] and body["data"][0]["raw_row"]["ticket_id"] == "t-004"
    assert get(client, "/data/rejected_records").json()["meta"]["total_count"] == 9
    assert get(client, "/data/tickets").json()["meta"]["exclusions"] == {"rejected_records": 9}


@pytest.mark.parametrize("path,params,status,rule", [
    ("/data/tickets", {"colour": "red"}, 422, "INVALID_FILTER"),
    ("/data/tickets", {"from": "not-a-date"}, 422, "INVALID_FILTER"),
    ("/data/tickets", {"to": "2026-13-45"}, 422, "INVALID_FILTER"),
    ("/data/tickets", {"cursor": "%%%"}, 422, "INVALID_CURSOR"),
    ("/data/tickets", {"cursor": "WyJhIiwiYiJd"}, 422, "INVALID_CURSOR"),          # wrong width for this entity
    ("/data/tickets", {"limit": 0}, 422, None),
    ("/data/tickets", {"limit": 201}, 422, None),
    ("/data/tickets", {"limit": "many"}, 422, None),
    ("/data/queue_skills", {"from": "2026-01-01"}, 422, "FILTER_NOT_SUPPORTED"),
    ("/data/queues", {"active": "maybe"}, 422, "INVALID_FILTER"),
    ("/data/nonsense", {}, 404, "ENTITY_UNKNOWN"),
])
def test_invalid_reads(client, path, params, status, rule):
    r = get(client, path, **params)
    assert r.status_code == status
    if rule:
        assert rule_ids(r) == [rule]
    assert "request_id" in r.json() and "error" in r.json()


def test_reversed_and_empty_windows_are_invalid(client, seeded):
    for lo, hi in (("2026-07-10", "2026-07-01"), ("2026-07-10", "2026-07-10")):
        r = get(client, "/data/tickets", **{"from": lo, "to": hi})
        assert r.status_code == 422 and rule_ids(r) == ["INVALID_WINDOW"]
        r = get(client, "/metrics", **{"from": lo, "to": hi})
        assert r.status_code == 422 and rule_ids(r) == ["INVALID_WINDOW"]


def test_reads_need_no_identity(client, seeded):
    assert get(client, "/data/tickets").status_code == 200 and get(client, "/metrics").status_code == 200


# --- metrics ----------------------------------------------------------------------------------------------------

def test_metrics_equal_expected_golden_through_the_api(client, seeded):
    r = get(client, "/metrics", cutoff=CUTS, **WINDOW)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["metrics"] == golden_expected()["metrics"] and list(data["metrics"]) == list(METRIC_KEYS)
    assert data["group_by"] == "none" and data["window"] == {"from": WINDOW["from"], "to": WINDOW["to"]}
    m = r.json()["meta"]
    assert m["applied_filters"]["cutoff"] == golden_inputs()["backlog_cutoffs"] and m["total_count"] == 3


def test_metrics_disclosures_sit_beside_the_numbers(client, seeded):
    d = get(client, "/metrics", **WINDOW).json()["data"]["disclosures"]
    assert d["csat"] == {"completed_tickets": 3, "invited": 2, "valid_responses": 1, "nonresponse": 1, "note": d["csat"]["note"]}
    assert "nearest rank" in d["p90_method"] and d["reopened_tickets"] == 0 and d["bot_events_ignored_for_first_response"] == 3
    assert d["open_overdue_at_window_end"] == 0


def test_metrics_without_a_window_use_the_recorded_span(client, seeded):
    r = get(client, "/metrics")
    d = r.json()["data"]
    assert d["window"]["from"] == "2026-07-06T09:00:00Z" and d["window"]["to"] == "2026-07-06T09:30:01Z"
    assert d["metrics"]["arrival_count"] == 3 and d["metrics"]["completion_count"] == 3


def test_metrics_window_is_half_open_over_the_api(client, seeded):
    d = get(client, "/metrics", **{"from": "2026-07-06T09:00:00Z", "to": "2026-07-06T09:30:00Z"}).json()["data"]["metrics"]
    assert (d["arrival_count"], d["completion_count"]) == (3, 2)


@pytest.mark.parametrize("group_by", GROUP_KEYS)
def test_group_by_each_key(client, conn, group_by):
    w = World(window=(0, 480))
    w.ticket("t-1", 0, priority="P1", channel="chat", queue="q-1")
    w.serve("t-1", 5, 10, agent="a-1")
    w.ticket("t-2", 20, priority="P2", channel="email", queue="q-2")
    w.serve("t-2", 30, 40, agent="a-2", queue="q-2")
    w.ticket("t-3", 50, priority="P2", channel="email", queue="q-2")        # never served: in no agent's group
    load(conn, w)
    r = get(client, "/metrics", group_by=group_by, **{"from": at(0), "to": at(480)})
    assert r.status_code == 200, r.text
    groups = r.json()["data"]["groups"]
    want = {"queue": {"q-1": 1, "q-2": 2}, "priority": {"P1": 1, "P2": 2}, "channel": {"chat": 1, "email": 2},
            "agent": {"a-1": 1, "a-2": 1}}[group_by]
    assert {k: v["arrival_count"] for k, v in groups.items()} == want
    assert all(list(v) == list(METRIC_KEYS) for v in groups.values())
    if group_by == "agent":
        assert groups["a-1"]["staffed_available_minutes"] == "450.0000" and groups["a-1"]["agent_occupancy"] == d6(5, 450)
    else:
        assert all(v["staffed_available_minutes"] is None and v["agent_occupancy"] is None for v in groups.values())


def d6(a, b):
    from fractions import Fraction
    from serviceflow.timeutil import d6 as f
    return f(Fraction(a, b))


def test_group_by_priority_shows_the_tail_beside_the_mean(client, conn):
    w = World(window=(0, 480))
    for i in range(1, 11):
        w.ticket(f"t-{i:02d}", 0, priority="P1" if i == 10 else "P3")
        w.serve(f"t-{i:02d}", i * 2 if i < 10 else 90, i * 2 + 1 if i < 10 else 91)
    load(conn, w)
    d = get(client, "/metrics", group_by="priority", **{"from": at(0), "to": at(480)}).json()["data"]["groups"]
    assert d["P1"]["p90_first_response_minutes"] == "90.0000" and d["P3"]["mean_first_response_minutes"] == "10.0000"


@pytest.mark.parametrize("params,rule", [({"group_by": "colour"}, "INVALID_GROUP_BY"), ({"cutoff": "soon"}, "INVALID_FILTER"),
                                         ({"from": "x"}, "INVALID_FILTER")])
def test_invalid_metrics_requests(client, seeded, params, rule):
    r = get(client, "/metrics", **params)
    assert r.status_code == 422 and rule_ids(r) == [rule]


def test_metrics_on_an_empty_database_are_honest(client, db_url):
    r = get(client, "/metrics")
    assert r.status_code == 200
    m = r.json()["data"]["metrics"]
    assert m["empty_population"] is True and m["arrival_count"] == 0 and m["mean_first_response_minutes"] is None


def test_metrics_after_the_variant_with_rejections_equal_golden(client, conn):
    seed.seed(conn, golden_inputs("variant-rejected"))
    assert get(client, "/metrics", cutoff=CUTS, **WINDOW).json()["data"]["metrics"] == golden_expected()["metrics"]
