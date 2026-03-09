"""Schema-per-tenant database manager using psycopg (PostgreSQL / Neon).

Each tenant gets its own PostgreSQL **schema** inside the single `neondb`
database.  The schema name is derived from the tenant slug:
    tenant_slug  "al-noor-academy"  →  schema "tenant_al_noor_academy"

This avoids CREATE DATABASE (which Neon pooler endpoints don't support)
while still providing full isolation between tenants.
"""

import re
import socket

import psycopg
from psycopg.rows import dict_row
from flask import current_app, g

# Cache the resolved IPv4 address to avoid DNS lookup on every connection
_resolved_hostaddr = None


def _base_uri():
    """Return the Neon connection string with an explicit IPv4 hostaddr.

    Many networks advertise IPv6 but can't actually route it, causing
    psycopg.connect() to hang.  We resolve the hostname to IPv4 once
    and append ``hostaddr=<ip>`` so libpq/psycopg always uses IPv4.
    """
    global _resolved_hostaddr
    uri = current_app.config["TENANT_DB_BASE_URI"]

    if "hostaddr" in uri:
        return uri

    # Extract hostname from URI
    m = re.search(r"@([^/:?]+)", uri)
    if not m:
        return uri

    hostname = m.group(1)

    # Resolve once and cache
    if _resolved_hostaddr is None:
        try:
            results = socket.getaddrinfo(hostname, 5432, socket.AF_INET, socket.SOCK_STREAM)
            _resolved_hostaddr = results[0][4][0]
        except Exception:
            return uri

    sep = "&" if "?" in uri else "?"
    return uri + sep + "hostaddr=" + _resolved_hostaddr


def _slug_to_schema(slug: str) -> str:
    """Convert a tenant slug to a valid PostgreSQL schema name."""
    safe = re.sub(r"[^a-z0-9_]", "_", slug.lower())
    return f"tenant_{safe}"


def create_tenant_schema(slug: str):
    """Create the PostgreSQL schema for a tenant (idempotent)."""
    schema = _slug_to_schema(slug)
    conn = psycopg.connect(_base_uri(), autocommit=True, connect_timeout=10)
    conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    conn.close()


def get_tenant_connection(slug: str):
    """Return a psycopg connection whose search_path is the tenant's schema.

    The connection uses `dict_row` so every fetchone() / fetchall() returns
    dict-like objects, matching the sqlite3.Row interface the app expects.

    Connections are cached on Flask's `g` object (one per request per tenant).
    """
    cache_key = f"_pg_conn_{slug}"
    conn = getattr(g, cache_key, None)
    if conn is None or conn.closed:
        schema = _slug_to_schema(slug)
        conn = psycopg.connect(_base_uri(), row_factory=dict_row, autocommit=False, connect_timeout=10)
        conn.execute(f"SET search_path TO {schema}, public")
        setattr(g, cache_key, conn)
    return conn


def close_tenant_connection(slug: str):
    """Close (and remove from g) the cached connection for a tenant."""
    cache_key = f"_pg_conn_{slug}"
    conn = getattr(g, cache_key, None)
    if conn is not None and not conn.closed:
        conn.close()
    try:
        delattr(g, cache_key)
    except AttributeError:
        pass


def get_platform_connection():
    """Return a psycopg connection to the public schema (platform-level tables).

    Used for cross-tenant data like the myfomo follows table.
    """
    cache_key = "_pg_conn_platform"
    conn = getattr(g, cache_key, None)
    if conn is None or conn.closed:
        conn = psycopg.connect(_base_uri(), row_factory=dict_row, autocommit=False, connect_timeout=10)
        conn.execute("SET search_path TO public")
        setattr(g, cache_key, conn)
    return conn


def close_all_connections(exception=None):
    """Close all psycopg connections cached on Flask's g object.

    Register this as a teardown_appcontext handler so connections are
    returned to Neon's pool after every request.
    """
    for key in list(vars(g)):
        if key.startswith("_pg_conn_"):
            conn = getattr(g, key, None)
            if conn is not None:
                try:
                    if not conn.closed:
                        conn.close()
                except Exception:
                    pass


def init_db_teardown(app):
    """Register the connection cleanup handler on the Flask app."""
    app.teardown_appcontext(close_all_connections)
