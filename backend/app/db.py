"""Connexion SQLite via SQLAlchemy (migrable vers PostgreSQL en changeant DB_URL)."""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import DB_URL

engine = create_engine(DB_URL, connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")  # lectures possibles pendant une mise à jour
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    from . import models  # noqa: F401  (enregistre les tables)
    from .assets import seed_assets, seed_settings

    Base.metadata.create_all(engine)
    _migrate()
    with SessionLocal() as s:
        seed_assets(s)
        seed_settings(s)
        s.commit()


def _migrate() -> None:
    """Ajoute les colonnes apparues après la création de la base (SQLite ne le fait pas tout seul)."""
    new_cols = {"assets": [("category", "VARCHAR(40) DEFAULT 'Autres'"),
                           ("quote_factor", "FLOAT DEFAULT 1.0"),
                           ("origin", "VARCHAR(10) DEFAULT 'catalogue'")]}
    with engine.begin() as conn:
        for table, cols in new_cols.items():
            have = {r[1] for r in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            for name, ddl in cols:
                if name not in have:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def get_session():
    with SessionLocal() as s:
        yield s
