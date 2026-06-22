"""add knowledge_bases table

User-authored knowledge bases that feed every internal AskAI / ForgeAI prompt.
Created from the SQLModel metadata with checkfirst=True so existing tables are
left untouched.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-18

"""

from alembic import op
from sqlmodel import SQLModel

# ensure every model is registered on the shared metadata
import app.models  # noqa: F401

# revision identifiers, used by Alembic.
revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    SQLModel.metadata.create_all(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    table = SQLModel.metadata.tables.get("knowledge_bases")
    if table is not None:
        table.drop(bind=bind, checkfirst=True)
