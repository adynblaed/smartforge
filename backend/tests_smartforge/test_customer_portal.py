"""Integration tests: customer portal, data scoping, escalations, and RBAC."""

import uuid


def test_customer_sees_only_their_orders(customer_client):
    r = customer_client.get("/api/v1/customer/orders")
    assert r.status_code == 200
    assert r.json()["count"] >= 1


def test_customer_order_cross_account_is_404(customer_client, other_customer_client):
    other = other_customer_client.get("/api/v1/customer/orders").json()["data"]
    assert other
    other_id = other[0]["id"]
    # Acme cannot read a Globex order.
    r = customer_client.get(f"/api/v1/customer/orders/{other_id}")
    assert r.status_code == 404


def test_customer_ask_is_customer_safe(customer_client):
    r = customer_client.post("/api/v1/customer/ask",
                             json={"question": "When will my order be done?"})
    assert r.status_code == 200
    assert r.json()["answer"]


def test_customer_escalation_flow(customer_client, internal_client):
    esc = customer_client.post("/api/v1/customer/escalate", json={
        "question": "Where is my order?", "ai_confidence": 0.3,
    })
    assert esc.status_code == 200
    eid = esc.json()["id"]
    assert esc.json()["status"] == "open"

    # Internal staff can list and respond.
    listing = internal_client.get("/api/v1/customer/escalations")
    assert listing.status_code == 200
    assert any(e["id"] == eid for e in listing.json()["data"])

    resp = internal_client.post(
        f"/api/v1/customer/escalations/{eid}/respond",
        json={"human_response": "Shipping tomorrow.", "assigned_team": "cs"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "resolved"
    assert resp.json()["human_response"] == "Shipping tomorrow."


def test_escalation_respond_404(internal_client):
    assert internal_client.post(
        f"/api/v1/customer/escalations/{uuid.uuid4()}/respond",
        json={"human_response": "x"},
    ).status_code == 404


# ---- RBAC boundaries (spec §11) ----
def test_customer_blocked_from_internal_apis(customer_client):
    for ep in ["/api/v1/machines/", "/api/v1/work-orders/", "/api/v1/oee",
               "/api/v1/command-center"]:
        assert customer_client.get(ep).status_code == 403


def test_internal_blocked_from_customer_orders(internal_client):
    assert internal_client.get("/api/v1/customer/orders").status_code == 403
