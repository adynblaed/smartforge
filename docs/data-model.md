# SmartForge Data Model

All tables from SMART_FACTORY.md §5 are implemented as SQLModel classes under
`app/models/` (one module per domain, re-exported from `app/models/__init__.py`).

Core: `users` (+`role`,`customer_id`), `factories`, `lines`, `machine`.
Telemetry: `telemetry_events`, `machine_health_scores`.
Maintenance: `alerts`, `work_orders`, `incidents`, `rca_records`.
Production: `jobs`, `production_runs`, `oee_metrics`.
Quality: `inspections`, `defects`.
Optimization: `machine_configurations`, `recommendations`.
Integration: `erp_sync_events`, `mes_sync_events`.
Supply chain: `suppliers`, `inventory_items`, `purchase_orders`, `quotes`.
Customer: `customer`, `customer_orders`, `customer_messages`, `escalations`.
Knowledge/AI: `knowledge_documents`, `askai_sessions`.
Audit: `audit_logs`.

Every operational table carries `factory_id` and/or `line_id` for multi-site
scaling. Migration: `app/alembic/versions/a1b2c3d4e5f6_smartforge_core_schema.py`.
