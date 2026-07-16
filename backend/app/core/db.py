from sqlmodel import Session, create_engine, select

from app import crud
from app.core.config import settings
from app.models import User, UserCreate, UserRole

engine = create_engine(str(settings.SQLALCHEMY_DATABASE_URI))


# make sure all SQLModel models are imported (app.models) before initializing DB
# otherwise, SQLModel might fail to initialize relationships properly
# for more details: https://github.com/fastapi/full-stack-fastapi-template/issues/28


def init_db(session: Session) -> None:
    # Tables should be created with Alembic migrations
    # But if you don't want to use migrations, create
    # the tables un-commenting the next lines
    # from sqlmodel import SQLModel

    # This works because the models are already imported and registered from app.models
    # SQLModel.metadata.create_all(engine)

    user = session.exec(
        select(User).where(User.email == settings.FIRST_SUPERUSER)
    ).first()
    if not user:
        user_in = UserCreate(
            email=settings.FIRST_SUPERUSER,
            password=settings.FIRST_SUPERUSER_PASSWORD,
            is_superuser=True,
            role=UserRole.admin,
        )
        user = crud.create_user(session=session, user_create=user_in)

    # The maintenance-ticketing + SOP tables were added after the baseline
    # migrations. Create just those tables if missing (idempotent, checkfirst)
    # so the feature works without a schema reset; existing tables are untouched.
    from sqlmodel import SQLModel

    from app.models.maintenance_ticket import (
        MaintenanceTicket,
        MaintenanceTicketLog,
        MaintenanceTicketPart,
    )
    from app.models.reorder import MaterialReorder
    from app.models.sop import Sop, SopSection

    # SQLModel table classes gain ``__table__`` at runtime via SQLAlchemy
    # instrumentation; sqlmodel's stubs don't expose it (third-party stub gap).
    SQLModel.metadata.create_all(
        engine,
        tables=[
            Sop.__table__,  # type: ignore[attr-defined]
            SopSection.__table__,  # type: ignore[attr-defined]
            MaintenanceTicket.__table__,  # type: ignore[attr-defined]
            MaintenanceTicketLog.__table__,  # type: ignore[attr-defined]
            MaintenanceTicketPart.__table__,  # type: ignore[attr-defined]
            MaterialReorder.__table__,  # type: ignore[attr-defined]
        ],
        checkfirst=True,
    )

    # Widen the now-encrypted chat/interaction columns to TEXT (ciphertext is
    # longer than the original VARCHAR limits). Idempotent + each in its own
    # transaction so a no-op/failure never blocks startup.
    from sqlalchemy import text as _sql

    for table_name, column in [
        ("customer_messages", "question"),
        ("customer_messages", "answer"),
        ("escalations", "original_ai_answer"),
        ("escalations", "human_response"),
    ]:
        try:
            with engine.begin() as conn:
                conn.execute(
                    _sql(f"ALTER TABLE {table_name} ALTER COLUMN {column} TYPE TEXT")
                )
        except Exception:  # noqa: BLE001 — table may not exist yet / already TEXT
            pass

    # Seed the SmartForge sandbox factory, machines, supply chain, and corpus.
    from app.core.seed import seed_sandbox, seed_tickets_and_sops

    seed_sandbox(session)
    # Idempotent on its own (keyed on the SOP table being empty) so it back-fills
    # tickets + SOPs on an already-seeded sandbox without a full re-seed.
    seed_tickets_and_sops(session)
