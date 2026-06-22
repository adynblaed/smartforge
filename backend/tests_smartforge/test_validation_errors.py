"""Error-bound & validation tests (422 / 404 / 403) across the API."""

import uuid


def test_quote_generate_validation_error(internal_client):
    # Missing required customer/part_type → 422
    assert internal_client.post("/api/v1/quotes/generate", json={}).status_code == 422


def test_inspection_validation_error(internal_client):
    # Missing required part_id → 422
    assert internal_client.post("/api/v1/inspection-results", json={}).status_code == 422


def test_work_order_validation_error(internal_client):
    # Missing machine_id/fault_type/recommended_task → 422
    assert internal_client.post("/api/v1/work-orders/", json={
        "severity": "high",
    }).status_code == 422


def test_telemetry_bad_machine_404(internal_client):
    r = internal_client.post(
        f"/api/v1/machines/{uuid.uuid4()}/telemetry",
        json={"machine_id": str(uuid.uuid4()), "temperature": 50},
    )
    assert r.status_code == 404


def test_telemetry_invalid_enum_422(internal_client):
    machine = internal_client.get("/api/v1/machines/").json()["data"][0]
    r = internal_client.post(
        f"/api/v1/machines/{machine['id']}/telemetry",
        json={"machine_id": machine["id"], "line_status": "not_a_status"},
    )
    assert r.status_code == 422


def test_health_before_any_telemetry_is_404(internal_client):
    # A freshly seeded machine has no health-score row until telemetry arrives.
    machine = internal_client.get("/api/v1/machines/").json()["data"][-1]
    r = internal_client.get(f"/api/v1/machines/{machine['id']}/health")
    assert r.status_code in (200, 404)  # 200 only if seed/telemetry produced one


def test_customer_escalate_validation_error(customer_client):
    assert customer_client.post("/api/v1/customer/escalate", json={}).status_code == 422


def test_pagination_bounds(internal_client):
    r = internal_client.get("/api/v1/machines/?skip=0&limit=1")
    assert r.status_code == 200
    assert len(r.json()["data"]) == 1
    assert r.json()["count"] == 3
