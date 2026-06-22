"""Integration tests: ERP/MES sync, incidents/RCA, planning, command center, metrics."""

import uuid


def test_integration_status_and_sync(internal_client):
    assert internal_client.get("/api/v1/integrations/status").status_code == 200
    erp = internal_client.post("/api/v1/integrations/erp/sync")
    assert erp.status_code == 200 and erp.json()["count"] >= 1
    mes = internal_client.post("/api/v1/integrations/mes/sync")
    assert mes.status_code == 200
    status = internal_client.get("/api/v1/integrations/status").json()
    assert status["erp"]["total_events"] >= 1
    assert status["erp"]["failed_records"] >= 1
    events = internal_client.get("/api/v1/integrations/events?system=erp")
    assert events.status_code == 200 and events.json()["count"] >= 1


def test_incident_and_rca_flow(internal_client):
    factory = internal_client.get("/api/v1/factories").json()["data"][0]
    inc = internal_client.post("/api/v1/incidents/", json={
        "title": "Test outage", "factory_id": factory["id"],
        "downtime_minutes": 30, "estimated_cost": 5000, "severity": "high",
    })
    assert inc.status_code == 200
    iid = inc.json()["id"]
    rca = internal_client.post(f"/api/v1/incidents/{iid}/rca", json={
        "root_cause": "Sensor failure", "corrective_actions": "Replace sensor",
    })
    assert rca.status_code == 200
    listing = internal_client.get(f"/api/v1/incidents/{iid}/rca")
    assert listing.status_code == 200 and listing.json()["count"] >= 1


def test_rca_for_missing_incident_404(internal_client):
    assert internal_client.post(
        f"/api/v1/incidents/{uuid.uuid4()}/rca",
        json={"root_cause": "x"},
    ).status_code == 404


def test_planning_capacity_and_simulate(internal_client):
    cap = internal_client.get("/api/v1/planning/capacity")
    assert cap.status_code == 200
    assert cap.json()["total_machines"] == 3
    sim = internal_client.post("/api/v1/planning/simulate")
    assert sim.status_code == 200
    body = sim.json()
    assert "proposed_schedule" in body
    assert "capacity_units" in body and "demand_units" in body


def test_command_center_and_kpis(internal_client):
    cc = internal_client.get("/api/v1/command-center")
    assert cc.status_code == 200
    body = cc.json()
    for key in ("factory_health_summary", "kpis", "risk_alerts",
                "production_status", "maintenance_status", "customer_impact"):
        assert key in body
    kpis = internal_client.get("/api/v1/factory/kpis")
    assert kpis.status_code == 200
    assert "avg_oee" in kpis.json()


def test_factories_and_lines(internal_client):
    assert internal_client.get("/api/v1/factories").json()["count"] == 1
    assert internal_client.get("/api/v1/lines").json()["count"] == 1


def test_metrics_prometheus_format(internal_client):
    r = internal_client.get("/api/v1/metrics")
    assert r.status_code == 200
    text = r.text
    assert "smartforge_machine_health_score" in text
    assert "smartforge_oee_percent" in text
    assert "smartforge_open_work_orders_total" in text


def test_askai_ingest_and_list_documents(internal_client):
    before = internal_client.get("/api/v1/ask-ai/documents").json()["count"]
    r = internal_client.post("/api/v1/ask-ai/documents", json={
        "title": "Test SOP", "kind": "sop", "content": "Lubricate weekly.",
    })
    assert r.status_code == 200
    after = internal_client.get("/api/v1/ask-ai/documents").json()["count"]
    assert after == before + 1


def test_internal_askai_ask(internal_client):
    r = internal_client.post("/api/v1/ask-ai/ask",
                             json={"question": "How do I fix high vibration?"})
    assert r.status_code == 200
    assert r.json()["answer"]
    assert r.json()["session_id"]


def test_forge_ai_at_risk_highlights_a_machine(internal_client):
    r = internal_client.post("/api/v1/ask-ai/forge",
                             json={"question": "Which machine is most at risk?"})
    assert r.status_code == 200
    body = r.json()
    assert body["answer"]
    assert isinstance(body["highlight"], list)
    assert len(body["highlight"]) >= 1


def test_forge_ai_locates_by_type(internal_client):
    r = internal_client.post("/api/v1/ask-ai/forge",
                             json={"question": "show me the press"})
    assert r.status_code == 200
    codes = r.json()["highlight"]
    assert len(codes) >= 1


def test_forge_ai_overview_highlights_all(internal_client):
    r = internal_client.post("/api/v1/ask-ai/forge",
                             json={"question": "give me a fleet overview of all machines"})
    assert len(r.json()["highlight"]) == 3


def test_datasource_snapshot_export_import_roundtrip(internal_client):
    # export every operational table to one CSV
    r = internal_client.get("/api/v1/datasources/export")
    assert r.status_code == 200
    csv_text = r.text
    assert csv_text.startswith("table,row")
    assert "machines" in csv_text

    # re-import the same snapshot (replaces operational data)
    imp = internal_client.post(
        "/api/v1/datasources/import",
        files={"file": ("smart_forge_schema.csv", csv_text, "text/csv")},
    )
    assert imp.status_code == 200
    assert imp.json()["summary"]["machines"] >= 1

    # data is intact after the round-trip
    assert internal_client.get("/api/v1/machines/").json()["count"] >= 1
    assert internal_client.get("/api/v1/purchase-orders").json()["count"] >= 1


def test_snapshot_import_rejects_bad_header(internal_client):
    before = internal_client.get("/api/v1/machines/").json()["count"]
    r = internal_client.post(
        "/api/v1/datasources/import",
        files={"file": ("x.csv", "foo,bar\n1,2\n", "text/csv")},
    )
    assert r.status_code == 400
    assert "header" in r.json()["detail"].lower()
    # data untouched (parsing/validation happens before any writes)
    assert internal_client.get("/api/v1/machines/").json()["count"] == before


def test_snapshot_import_rejects_bad_json(internal_client):
    before = internal_client.get("/api/v1/machines/").json()["count"]
    r = internal_client.post(
        "/api/v1/datasources/import",
        files={"file": ("x.csv", "table,row\nmachines,{not json}\n", "text/csv")},
    )
    assert r.status_code == 400
    assert "json" in r.json()["detail"].lower()
    assert internal_client.get("/api/v1/machines/").json()["count"] == before


def test_snapshot_import_rejects_empty_file(internal_client):
    r = internal_client.post(
        "/api/v1/datasources/import",
        files={"file": ("x.csv", "", "text/csv")},
    )
    assert r.status_code == 400


def test_snapshot_export_includes_expected_tables(internal_client):
    text = internal_client.get("/api/v1/datasources/export").text
    assert text.startswith("table,row")
    for table in ("machines", "purchase_orders", "incidents", "rca_records"):
        assert f"{table}," in text


def test_knowledge_base_update_and_delete_404(internal_client):
    missing = str(uuid.uuid4())
    assert internal_client.patch(
        f"/api/v1/ask-ai/knowledge-bases/{missing}", json={"content": "x"}
    ).status_code == 404
    assert internal_client.delete(
        f"/api/v1/ask-ai/knowledge-bases/{missing}"
    ).status_code == 404


def test_knowledge_base_crud_and_askai_inclusion(internal_client):
    # create
    r = internal_client.post("/api/v1/ask-ai/knowledge-bases", json={
        "name": "Torque SOP",
        "description": "Bolt torque spec",
        "content": "All press bolts must be torqued to 88 newton-metres.",
    })
    assert r.status_code == 200
    kb_id = r.json()["id"]

    # list
    listing = internal_client.get("/api/v1/ask-ai/knowledge-bases")
    assert listing.status_code == 200
    assert any(k["id"] == kb_id for k in listing.json()["data"])

    # the KB is surfaced as a source in AskAI answers
    ans = internal_client.post("/api/v1/ask-ai/ask",
                               json={"question": "What torque for press bolts?"})
    assert ans.status_code == 200
    assert any(s["kind"] == "knowledge_base" for s in ans.json()["sources"])

    # update
    upd = internal_client.patch(f"/api/v1/ask-ai/knowledge-bases/{kb_id}",
                                json={"content": "Updated: 90 Nm."})
    assert upd.status_code == 200 and "90 Nm" in upd.json()["content"]

    # delete
    assert internal_client.delete(
        f"/api/v1/ask-ai/knowledge-bases/{kb_id}").status_code == 200
