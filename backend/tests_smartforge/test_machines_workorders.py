"""Integration tests: machines, telemetry, alerts, and work-order lifecycle."""

import uuid


def _first_machine(client):
    r = client.get("/api/v1/machines/")
    assert r.status_code == 200
    return r.json()["data"][0]


def test_list_and_get_machines(internal_client):
    r = internal_client.get("/api/v1/machines/")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 3
    mid = body["data"][0]["id"]
    r2 = internal_client.get(f"/api/v1/machines/{mid}")
    assert r2.status_code == 200
    assert r2.json()["id"] == mid


def test_get_machine_404(internal_client):
    r = internal_client.get(f"/api/v1/machines/{uuid.uuid4()}")
    assert r.status_code == 404


def test_telemetry_ingest_drives_alerts_health_and_workorders(internal_client):
    machine = _first_machine(internal_client)
    mid = machine["id"]
    payload = {
        "machine_id": mid,
        "temperature": 96.0,
        "vibration": 0.92,
        "cycle_time": 12.0,
        "runtime_hours": 5000.0,
        "fault_code": "E101",
        "power_draw": 12.0,
        "line_status": "down",
        "maintenance_state": "ok",
    }
    r = internal_client.post(f"/api/v1/machines/{mid}/telemetry", json=payload)
    assert r.status_code == 200

    # Telemetry stored
    t = internal_client.get(f"/api/v1/machines/{mid}/telemetry")
    assert t.status_code == 200
    assert t.json()["count"] >= 1

    # Health score recorded
    h = internal_client.get(f"/api/v1/machines/{mid}/health")
    assert h.status_code == 200
    assert 0 <= h.json()["score"] <= 100

    # Alerts generated for this machine
    a = internal_client.get("/api/v1/alerts/?status=active")
    assert a.status_code == 200
    rules = {x["rule"] for x in a.json()["data"] if x["machine_id"] == mid}
    assert "repeated_fault" in rules

    # Work orders auto-drafted from high/critical alerts
    w = internal_client.get("/api/v1/work-orders/")
    drafts = [x for x in w.json()["data"] if x["machine_id"] == mid]
    assert drafts, "expected at least one auto-drafted work order"


def test_alert_acknowledge_and_resolve(internal_client):
    machine = _first_machine(internal_client)
    mid = machine["id"]
    internal_client.post(
        f"/api/v1/machines/{mid}/telemetry",
        json={"machine_id": mid, "temperature": 96.0, "vibration": 0.95,
              "fault_code": "E1", "line_status": "down"},
    )
    alerts = internal_client.get("/api/v1/alerts/?status=active").json()["data"]
    assert alerts
    aid = alerts[0]["id"]
    ack = internal_client.post(f"/api/v1/alerts/{aid}/acknowledge")
    assert ack.status_code == 200 and ack.json()["status"] == "acknowledged"
    res = internal_client.post(f"/api/v1/alerts/{aid}/resolve")
    assert res.status_code == 200 and res.json()["status"] == "resolved"


def test_alert_actions_404(internal_client):
    assert internal_client.post(
        f"/api/v1/alerts/{uuid.uuid4()}/acknowledge"
    ).status_code == 404


def test_work_order_full_lifecycle(internal_client):
    machine = _first_machine(internal_client)
    mid = machine["id"]
    # Manual create
    r = internal_client.post("/api/v1/work-orders/", json={
        "machine_id": mid, "fault_type": "bearing", "severity": "high",
        "recommended_task": "Replace bearing", "required_skill": "mechanical",
        "priority": 2,
    })
    assert r.status_code == 200
    wo = r.json()
    assert wo["status"] == "draft" and wo["fiix_sync_state"] == "not_synced"
    wid = wo["id"]

    # Approve
    ap = internal_client.post(f"/api/v1/work-orders/{wid}/approve?approve=true")
    assert ap.status_code == 200 and ap.json()["status"] == "approved"

    # Fiix sync
    fx = internal_client.post(f"/api/v1/work-orders/{wid}/sync-fiix")
    assert fx.status_code == 200
    assert fx.json()["fiix_sync_state"] == "synced"
    assert fx.json()["fiix_id"]


def test_work_order_reject(internal_client):
    machine = _first_machine(internal_client)
    r = internal_client.post("/api/v1/work-orders/", json={
        "machine_id": machine["id"], "fault_type": "x", "severity": "low",
        "recommended_task": "t",
    })
    wid = r.json()["id"]
    rej = internal_client.post(f"/api/v1/work-orders/{wid}/approve?approve=false")
    assert rej.json()["status"] == "rejected"


def test_work_order_approve_404(internal_client):
    assert internal_client.post(
        f"/api/v1/work-orders/{uuid.uuid4()}/approve"
    ).status_code == 404


def test_machine_ask_returns_answer(internal_client):
    machine = _first_machine(internal_client)
    r = internal_client.post(
        f"/api/v1/machines/{machine['id']}/ask",
        json={"question": "Why is the health score dropping?"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["answer"]
    assert "confidence" in body
