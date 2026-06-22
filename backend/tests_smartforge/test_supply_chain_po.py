"""Integration tests: supply chain, inventory, quoting, job intake, and the
full purchase-order lifecycle (intake → quote → job → PO linkage → readiness)."""


def test_inventory_flags_below_threshold(internal_client):
    r = internal_client.get("/api/v1/inventory")
    assert r.status_code == 200
    items = r.json()["data"]
    assert items
    for i in items:
        assert i["below_threshold"] == (i["quantity"] < i["reorder_threshold"])
    assert any(i["below_threshold"] for i in items)


def test_suppliers_and_risks(internal_client):
    assert internal_client.get("/api/v1/suppliers").status_code == 200
    risks = internal_client.get("/api/v1/supply-chain/risks")
    assert risks.status_code == 200
    body = risks.json()
    assert "low_stock_materials" in body
    assert "delayed_suppliers" in body
    assert "suggested_reorders" in body
    assert len(body["low_stock_materials"]) >= 1


def test_quote_generation_and_listing(internal_client):
    r = internal_client.post("/api/v1/quotes/generate", json={
        "customer": "Acme", "part_type": "bracket", "quantity": 250, "rush": True,
    })
    assert r.status_code == 200
    q = r.json()
    assert q["estimated_price"] > 0
    assert q["timeline_days"] >= 1
    assert q["rush"] is True
    listing = internal_client.get("/api/v1/quotes")
    assert listing.status_code == 200
    assert any(x["id"] == q["id"] for x in listing.json()["data"])


def test_purchase_orders_are_linked(internal_client):
    r = internal_client.get("/api/v1/purchase-orders")
    assert r.status_code == 200
    pos = r.json()["data"]
    assert pos
    # Seeded POs link to inventory and (job or order).
    assert all(p["inventory_item_id"] for p in pos)
    assert any(p["job_id"] or p["customer_order_id"] for p in pos)
    assert any(p["shop_floor_ready"] for p in pos)


def test_full_po_lifecycle(internal_client):
    """intake (parse) → approve job → quote → POs linked + readiness visible."""
    # 1. AI-assisted job intake (offline fallback parses into a job).
    intake = internal_client.post(
        "/api/v1/jobs/intake?raw_text=" "Acme needs 300 steel brackets next week"
    )
    assert intake.status_code == 200
    job = intake.json()
    assert job["status"] == "intake"
    assert job["suggested_priority"] is not None

    # 2. Approve the job.
    ap = internal_client.post(f"/api/v1/jobs/{job['id']}/approve")
    assert ap.status_code == 200 and ap.json()["status"] == "approved"

    # 3. Generate a quote for it.
    quote = internal_client.post("/api/v1/quotes/generate", json={
        "customer": job["customer"], "part_type": job["part_type"],
        "quantity": job["quantity"],
    })
    assert quote.status_code == 200 and quote.json()["estimated_price"] > 0

    # 4. POs exist and are linked to jobs/materials with shop-floor readiness.
    pos = internal_client.get("/api/v1/purchase-orders").json()["data"]
    assert pos
    assert any(p["shop_floor_ready"] for p in pos)


def test_manual_job_create_flags_missing_info(internal_client):
    r = internal_client.post("/api/v1/jobs", json={
        "customer": "Acme", "part_type": "bracket", "quantity": 10,
    })
    assert r.status_code == 200
    # due_date omitted → flagged as missing
    assert r.json()["missing_info"] and "due_date" in r.json()["missing_info"]
