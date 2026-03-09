"""Tenant-aware database utilities for the Barber app (PostgreSQL / Neon)."""

from flask import g
from core.tenants.db_manager import get_tenant_connection


def get_barber_db(tenant_slug):
    """Get a PostgreSQL connection for the given tenant."""
    return get_tenant_connection(tenant_slug)


def close_barber_db(tenant_slug):
    """Close the cached connection for a tenant."""
    from core.tenants.db_manager import close_tenant_connection
    close_tenant_connection(tenant_slug)


def init_barber_db(tenant_slug):
    """Initialize the barber database schema for a tenant using raw SQL."""
    from core.tenants.db_manager import create_tenant_schema
    create_tenant_schema(tenant_slug)

    conn = get_tenant_connection(tenant_slug)
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        name TEXT,
        role TEXT NOT NULL CHECK(role IN ('admin', 'staff')),
        is_active INTEGER DEFAULT 1
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS services (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT DEFAULT '',
        duration_minutes INTEGER NOT NULL DEFAULT 30,
        price REAL NOT NULL DEFAULT 0.0,
        is_active INTEGER DEFAULT 1
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS staff (
        id SERIAL PRIMARY KEY,
        user_id INTEGER,
        name TEXT NOT NULL,
        email TEXT,
        phone TEXT,
        specialization TEXT DEFAULT '',
        is_active INTEGER DEFAULT 1,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS clients (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        email TEXT,
        phone TEXT,
        notes TEXT DEFAULT ''
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS appointments (
        id SERIAL PRIMARY KEY,
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
        id SERIAL PRIMARY KEY,
        staff_id INTEGER NOT NULL,
        day_of_week INTEGER NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL,
        is_active INTEGER DEFAULT 1,
        FOREIGN KEY(staff_id) REFERENCES staff(id)
    )''')

    conn.commit()
