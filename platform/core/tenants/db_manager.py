from flask import current_app
from sqlalchemy import create_engine, text
from sqlalchemy.orm import scoped_session, sessionmaker

# Cache engines to avoid recreating them
_engine_cache = {}


def _base_uri():
    return current_app.config["TENANT_DB_BASE_URI"]


def create_tenant_db(db_name):
    """Create a new PostgreSQL database for a tenant."""
    server_engine = create_engine(
        f"{_base_uri()}/postgres", isolation_level="AUTOCOMMIT"
    )
    with server_engine.connect() as conn:
        # Check if database already exists
        result = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": db_name},
        )
        if not result.fetchone():
            # Use text() with safe identifier quoting
            conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    server_engine.dispose()


def get_tenant_engine(db_name):
    """Get or create a SQLAlchemy engine for a tenant database."""
    if db_name not in _engine_cache:
        _engine_cache[db_name] = create_engine(
            f"{_base_uri()}/{db_name}", pool_size=5, max_overflow=10
        )
    return _engine_cache[db_name]


def get_tenant_session(db_name):
    """Get a scoped session bound to a tenant's database."""
    engine = get_tenant_engine(db_name)
    factory = sessionmaker(bind=engine)
    return scoped_session(factory)


def dispose_engine(db_name):
    """Dispose of a cached engine (for cleanup)."""
    engine = _engine_cache.pop(db_name, None)
    if engine:
        engine.dispose()
