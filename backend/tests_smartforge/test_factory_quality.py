"""Integration tests: vision inspection, OEE/trends, configs, recommendations."""

import uuid


def test_submit_inspection_auto_verdict(internal_client):
    r = internal_client.post("/api/v1/inspection-results", json={"part_id": "PART-X1"})
    assert r.status_code == 200
    body = r.json()
    assert body["part_id"] == "PART-X1"
    assert isinstance(body["defect_detected"], bool)
    assert 0 <= body["confidence"] <= 1


def test_inspections_and_defects_lists(internal_client):
    internal_client.post("/api/v1/inspection-results", json={"part_id": "PART-X2"})
    assert internal_client.get("/api/v1/inspections").status_code == 200
    d = internal_client.get("/api/v1/defects")
    assert d.status_code == 200
    assert d.json()["count"] >= 0


def test_oee_and_production_trends(internal_client):
    oee = internal_client.get("/api/v1/oee")
    assert oee.status_code == 200
    assert oee.json()["count"] >= 1
    trends = internal_client.get("/api/v1/production-trends")
    assert trends.status_code == 200
    assert trends.json()["count"] >= 1


def test_machine_configuration_versioning_and_approval(internal_client):
    machine = internal_client.get("/api/v1/machines/").json()["data"][0]
    mid = machine["id"]
    before = internal_client.get("/api/v1/machine-configurations").json()["count"]
    r = internal_client.post(
        "/api/v1/machine-configurations",
        json={
            "machine_id": mid,
            "speed": 1400,
            "temperature": 60,
            "pressure": 130,
            "feed_rate": 0.3,
            "tooling_profile": "opt",
            "material_type": "steel",
        },
    )
    assert r.status_code == 200
    cfg = r.json()
    assert cfg["version"] >= 1
    after = internal_client.get("/api/v1/machine-configurations").json()["count"]
    assert after == before + 1
    ap = internal_client.post(f"/api/v1/machine-configurations/{cfg['id']}/approve")
    assert ap.status_code == 200 and ap.json()["approved"] is True


def test_config_approve_404(internal_client):
    assert (
        internal_client.post(
            f"/api/v1/machine-configurations/{uuid.uuid4()}/approve"
        ).status_code
        == 404
    )


def test_recommendation_decision_updates_confidence(internal_client):
    recs = internal_client.get("/api/v1/recommendations").json()["data"]
    pending = next((r for r in recs if r["status"] == "pending"), None)
    assert pending is not None
    before = pending["confidence"]
    r = internal_client.post(
        f"/api/v1/recommendations/{pending['id']}/decision?accept=true&outcome_impact=6"
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "accepted"
    assert body["outcome_impact"] == 6
    assert body["confidence"] >= before


def test_recommendation_reject(internal_client):
    recs = internal_client.get("/api/v1/recommendations").json()["data"]
    pending = next((r for r in recs if r["status"] == "pending"), None)
    if pending is None:
        return
    r = internal_client.post(
        f"/api/v1/recommendations/{pending['id']}/decision?accept=false"
    )
    assert r.json()["status"] == "rejected"
