"""smartforge core schema

Creates all SmartForge domain tables (factories, lines, machines, telemetry,
alerts, work orders, incidents/RCA, jobs, production, OEE, quality, configs,
recommendations, ERP/MES sync, supply chain, customers/orders, escalations,
knowledge/askai, audit) plus the new User.role / User.customer_id columns.

Tables are created from the SQLModel metadata with checkfirst=True, so the
pre-existing `user` and `item` tables are left untouched.

Revision ID: a1b2c3d4e5f6
Revises: fe56fa70289e
Create Date: 2026-06-17

"""

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op
from sqlmodel import SQLModel

# ensure every model is registered on the shared metadata
import app.models  # noqa: F401

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "fe56fa70289e"
branch_labels = None
depends_on = None

# New SmartForge tables (everything except the pre-existing user/item).
_NEW_TABLES = [
    "factory",
    "line",
    "machine",
    "telemetry_events",
    "machine_health_scores",
    "alerts",
    "work_orders",
    "incidents",
    "rca_records",
    "jobs",
    "production_runs",
    "oee_metrics",
    "inspections",
    "defects",
    "machine_configurations",
    "recommendations",
    "erp_sync_events",
    "mes_sync_events",
    "suppliers",
    "inventory_items",
    "purchase_orders",
    "quotes",
    "customer",
    "customer_orders",
    "customer_messages",
    "escalations",
    "knowledge_documents",
    "askai_sessions",
    "audit_logs",
]


def upgrade() -> None:
    bind = op.get_bind()
    # Create all new tables (checkfirst leaves user/item in place).
    SQLModel.metadata.create_all(bind=bind, checkfirst=True)

    # Add new columns to the existing user table.
    with op.batch_alter_table("user") as batch:
        batch.add_column(
            sa.Column(
                "role",
                sqlmodel.sql.sqltypes.AutoString(),
                nullable=False,
                server_default="operator",
            )
        )
        batch.add_column(sa.Column("customer_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_user_customer_id", "customer", ["customer_id"], ["id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("user") as batch:
        batch.drop_constraint("fk_user_customer_id", type_="foreignkey")
        batch.drop_column("customer_id")
        batch.drop_column("role")

    bind = op.get_bind()
    meta = SQLModel.metadata
    for name in reversed(_NEW_TABLES):
        table = meta.tables.get(name)
        if table is not None:
            table.drop(bind=bind, checkfirst=True)
