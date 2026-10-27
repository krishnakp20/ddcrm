from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Columns added to tables that already exist (create_all only creates missing tables). Safe to run on every start.
COLUMN_UPDATES = [
    "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS source VARCHAR(12) NOT NULL DEFAULT 'manual'",
    "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS channel_id INTEGER",
    "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS contact_name VARCHAR(150)",
    "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS contact_email VARCHAR(255)",
    "ALTER TABLE dialer_ids ADD COLUMN IF NOT EXISTS dialer_server_id INTEGER",
    "ALTER TABLE campaign_batches ADD COLUMN IF NOT EXISTS name VARCHAR(120)",
    # dashboards and reports filter calls and tickets by date; with millions of rows they need these
    "CREATE INDEX IF NOT EXISTS ix_interactions_started ON interactions (started_at)",
    "CREATE INDEX IF NOT EXISTS ix_interactions_client_started ON interactions (client_id, started_at)",
    "CREATE INDEX IF NOT EXISTS ix_tickets_created ON tickets (created_at)",
]


def ensure_columns() -> None:
    from sqlalchemy import text
    with engine.begin() as conn:
        for stmt in COLUMN_UPDATES:
            conn.execute(text(stmt))
