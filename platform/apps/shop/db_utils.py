"""Tenant-aware database utilities for the Shop app (PostgreSQL / Neon)."""

from flask import g
from core.tenants.db_manager import get_tenant_connection


def get_shop_db(tenant_slug):
    """Get a PostgreSQL connection for the given tenant.

    Ensures shop tables exist on first connection.
    """
    conn = get_tenant_connection(tenant_slug)
    cache_key = f"_shop_init_{tenant_slug}"
    if not getattr(g, cache_key, False):
        _ensure_shop_tables(conn)
        setattr(g, cache_key, True)
    return conn


def close_shop_db(tenant_slug):
    """Close the cached connection for a tenant."""
    from core.tenants.db_manager import close_tenant_connection
    close_tenant_connection(tenant_slug)


def _ensure_shop_tables(conn):
    """Create all shop tables if they don't already exist."""
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        name TEXT,
        role TEXT NOT NULL CHECK(role IN ('admin', 'staff')),
        is_active INTEGER DEFAULT 1
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS categories (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT DEFAULT '',
        is_active INTEGER DEFAULT 1
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS products (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        sku TEXT,
        description TEXT DEFAULT '',
        category_id INTEGER,
        price REAL NOT NULL DEFAULT 0.0,
        cost REAL NOT NULL DEFAULT 0.0,
        quantity INTEGER NOT NULL DEFAULT 0,
        low_stock_threshold INTEGER NOT NULL DEFAULT 10,
        is_active INTEGER DEFAULT 1,
        FOREIGN KEY(category_id) REFERENCES categories(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS suppliers (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        contact_name TEXT DEFAULT '',
        email TEXT DEFAULT '',
        phone TEXT DEFAULT '',
        address TEXT DEFAULT '',
        notes TEXT DEFAULT ''
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS purchase_orders (
        id SERIAL PRIMARY KEY,
        supplier_id INTEGER NOT NULL,
        order_date TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'received', 'cancelled')),
        total_amount REAL NOT NULL DEFAULT 0.0,
        notes TEXT DEFAULT '',
        FOREIGN KEY(supplier_id) REFERENCES suppliers(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS purchase_order_items (
        id SERIAL PRIMARY KEY,
        purchase_order_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL DEFAULT 0,
        unit_cost REAL NOT NULL DEFAULT 0.0,
        FOREIGN KEY(purchase_order_id) REFERENCES purchase_orders(id),
        FOREIGN KEY(product_id) REFERENCES products(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS sales (
        id SERIAL PRIMARY KEY,
        date TEXT NOT NULL,
        total_amount REAL NOT NULL DEFAULT 0.0,
        payment_method TEXT NOT NULL DEFAULT 'cash' CHECK(payment_method IN ('cash', 'card', 'other')),
        notes TEXT DEFAULT '',
        created_by INTEGER,
        FOREIGN KEY(created_by) REFERENCES users(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS sale_items (
        id SERIAL PRIMARY KEY,
        sale_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL DEFAULT 0,
        unit_price REAL NOT NULL DEFAULT 0.0,
        FOREIGN KEY(sale_id) REFERENCES sales(id),
        FOREIGN KEY(product_id) REFERENCES products(id)
    )''')

    conn.commit()


def init_shop_db(tenant_slug):
    """Initialize the shop database schema for a tenant using raw SQL."""
    from core.tenants.db_manager import create_tenant_schema
    create_tenant_schema(tenant_slug)

    conn = get_tenant_connection(tenant_slug)
    _ensure_shop_tables(conn)
