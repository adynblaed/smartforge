"""Targeted tests closing remaining SmartForge branch gaps."""

import uuid


def _machine(client):
    return client.get("/api/v1/machines/").json()["data"][0]


def test_work_order_from_alert(internal_client):
    machine = _machine(internal_client)
    mid = machine["id"]
    internal_client.post(f"/api/v1/machines/{mid}/telemetry", json={
        "machine_id": mid, "temperature": 96, "vibration": 0.95,
        "fault_code": "E101", "line_status": "down",
    })
    alert = internal_client.get("/api/v1/alerts/?status=active").json()["data"][0]
    r = internal_client.post(f"/api/v1/work-orders/from-alert/{alert['id']}")
    assert r.status_code == 200
    assert r.json()["source_alert_id"] == alert["id"]
    assert r.json()["status"] == "draft"


def test_work_order_from_alert_404(internal_client):
    assert internal_client.post(
        f"/api/v1/work-orders/from-alert/{uuid.uuid4()}"
    ).status_code == 404


def test_sync_fiix_404(internal_client):
    assert internal_client.post(
        f"/api/v1/work-orders/{uuid.uuid4()}/sync-fiix"
    ).status_code == 404


def test_ask_ai_continues_session(internal_client):
    first = internal_client.post("/api/v1/ask-ai/ask",
                                 json={"question": "What is the PM schedule?"})
    sid = first.json()["session_id"]
    assert sid
    second = internal_client.post("/api/v1/ask-ai/ask",
                                  json={"question": "And for the press?",
                                        "session_id": sid})
    assert second.status_code == 200
    assert second.json()["session_id"] == sid


def test_ask_ai_sessions_list(internal_client):
    internal_client.post("/api/v1/ask-ai/ask", json={"question": "test"})
    r = internal_client.get("/api/v1/ask-ai/sessions")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert len(r.json()) >= 1


def test_customer_order_detail_success(customer_client):
    orders = customer_client.get("/api/v1/customer/orders").json()["data"]
    assert orders
    oid = orders[0]["id"]
    r = customer_client.get(f"/api/v1/customer/orders/{oid}")
    assert r.status_code == 200
    assert r.json()["id"] == oid
    # Customer-safe projection excludes internal fields.
    assert "customer_id" not in r.json()


def test_machine_telemetry_listing_order(internal_client):
    machine = _machine(internal_client)
    mid = machine["id"]
    for temp in (60, 70, 80):
        internal_client.post(f"/api/v1/machines/{mid}/telemetry", json={
            "machine_id": mid, "temperature": temp, "vibration": 0.2,
            "line_status": "running",
        })
    rows = internal_client.get(f"/api/v1/machines/{mid}/telemetry").json()["data"]
    assert len(rows) >= 3
    # newest first
    assert rows[0]["temperature"] == 80


def test_incidents_empty_then_present(internal_client):
    listing = internal_client.get("/api/v1/incidents/")
    assert listing.status_code == 200
    # seed creates one incident
    assert listing.json()["count"] >= 1
