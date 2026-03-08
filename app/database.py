from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

connect_args = {}
if settings.database_url.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(
    settings.database_url,
    echo=False,
    connect_args=connect_args,
)

if settings.database_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def ensure_sqlite_columns():
    """Add new columns to existing SQLite tables (no Alembic). Safe to call on every startup."""
    if not settings.database_url.startswith("sqlite"):
        return
    with engine.connect() as conn:
        cursor = conn.execute(text("PRAGMA table_info(auditoriums)"))
        rows = cursor.fetchall()
        # rows: (cid, name, type, notnull, dflt_value, pk)
        col_names = {r[1] for r in rows}
        if "stage_cols" not in col_names:
            conn.execute(text("ALTER TABLE auditoriums ADD COLUMN stage_cols INTEGER"))
        if "row_gaps" not in col_names:
            conn.execute(text("ALTER TABLE auditoriums ADD COLUMN row_gaps TEXT"))
        if "col_gaps" not in col_names:
            conn.execute(text("ALTER TABLE auditoriums ADD COLUMN col_gaps TEXT"))
        conn.commit()


SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass
