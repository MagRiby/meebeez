"""Tenant-aware database utilities for the Barber app."""

import sqlite3
import os

from flask import g


def _get_tenant_db_path(tenant_slug):
    """Get the SQLite database file path for a tenant."""
    instance_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "instance",
        "tenants",
    )
    os.makedirs(instance_dir, exist_ok=True)
    return os.path.join(instance_dir, f"{tenant_slug}.db")


def get_barber_db(tenant_slug):
    """Get a SQLite connection for the given tenant.

    Uses Flask's g object to cache the connection per-request.
    """
    cache_key = f"barber_db_{tenant_slug}"
    if not hasattr(g, cache_key):
        db_path = _get_tenant_db_path(tenant_slug)
        conn = sqlite3.connect(db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        setattr(g, cache_key, conn)
    return getattr(g, cache_key)


def close_barber_db(tenant_slug):
    """Close the cached connection for a tenant."""
    cache_key = f"barber_db_{tenant_slug}"
    conn = g.pop(cache_key, None)
    if conn is not None:
        conn.close()


def init_barber_db(tenant_slug):
    """Initialize the barber database schema for a tenant using raw SQL."""
    conn = sqlite3.connect(_get_tenant_db_path(tenant_slug), timeout=10)
    c = conn.cursor()
    conn.execute("PRAGMA journal_mode=WAL;")

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        name TEXT,
        role TEXT NOT NULL CHECK(role IN ('admin', 'staff')),
        is_active INTEGER DEFAULT 1
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS services (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT DEFAULT '',
        duration_minutes INTEGER NOT NULL DEFAULT 30,
        price REAL NOT NULL DEFAULT 0.0,
        is_active INTEGER DEFAULT 1
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS staff (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        name TEXT NOT NULL,
        email TEXT,
        phone TEXT,
        specialization TEXT DEFAULT '',
        is_active INTEGER DEFAULT 1,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS clients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT,
        phone TEXT,
        notes TEXT DEFAULT ''
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS appointments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER NOT NULL,
        staff_id INTEGER NOT NULL,
        service_id INTEGER NOT NULL,
        date TEXT NOT NULL,
        time TEXT NOT NULL,
        duration INTEGER NOT NULL DEFAULT 30,
        status TEXT NOT NULL DEFAULT 'scheduled',
        notes TEXT DEFAULT '',
        FOREIGN KEY(client_id) REFERENCES clients(id),
        FOREIGN KEY(staff_id) REFERENCES staff(id),
        FOREIGN KEY(service_id) REFERENCES services(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS working_hours (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        staff_id INTEGER NOT NULL,
        day_of_week INTEGER NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL,
        is_active INTEGER DEFAULT 1,
        FOREIGN KEY(staff_id) REFERENCES staff(id)
    )''')

    conn.commit()
    conn.close()
