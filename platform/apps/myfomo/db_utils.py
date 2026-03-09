"""Tenant-aware database utilities for the MyFomo app (PostgreSQL / Neon)."""

from flask import g
from core.tenants.db_manager import get_tenant_connection, get_platform_connection


def get_myfomo_db(tenant_slug):
    """Get a PostgreSQL connection for the given tenant.

    Ensures myfomo tables exist on first connection.
    """
    conn = get_tenant_connection(tenant_slug)
    cache_key = f"_myfomo_init_{tenant_slug}"
    if not getattr(g, cache_key, False):
        _ensure_myfomo_tables(conn)
        setattr(g, cache_key, True)
    return conn


def close_myfomo_db(tenant_slug):
    """Close the cached connection for a tenant."""
    from core.tenants.db_manager import close_tenant_connection
    close_tenant_connection(tenant_slug)


def _ensure_myfomo_tables(conn):
    """Create all myfomo tables if they don't already exist."""
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        name TEXT,
        role TEXT NOT NULL CHECK(role IN ('admin', 'follower')),
        phone TEXT DEFAULT '',
        is_active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT (NOW()::TEXT)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS posts (
        id SERIAL PRIMARY KEY,
        title TEXT NOT NULL,
        body TEXT DEFAULT '',
        image_path TEXT DEFAULT '',
        post_type TEXT NOT NULL DEFAULT 'product' CHECK(post_type IN ('product', 'announcement', 'event')),
        price REAL DEFAULT 0.0,
        original_quantity INTEGER DEFAULT 0,
        remaining_quantity INTEGER DEFAULT 0,
        sale_ends_at TEXT,
        status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft', 'published', 'archived')),
        ai_generated INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (NOW()::TEXT)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS events (
        id SERIAL PRIMARY KEY,
        title TEXT NOT NULL,
        description TEXT DEFAULT '',
        image_path TEXT DEFAULT '',
        event_date TEXT,
        event_time TEXT,
        location TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'upcoming' CHECK(status IN ('upcoming', 'passed', 'cancelled')),
        ai_generated INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (NOW()::TEXT)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS bookings (
        id SERIAL PRIMARY KEY,
        post_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        quantity INTEGER NOT NULL DEFAULT 1,
        status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'confirmed', 'cancelled', 'collected')),
        notes TEXT DEFAULT '',
        created_at TEXT DEFAULT (NOW()::TEXT),
        FOREIGN KEY(post_id) REFERENCES posts(id),
        FOREIGN KEY(user_id) REFERENCES users(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS analytics_events (
        id SERIAL PRIMARY KEY,
        event_type TEXT NOT NULL,
        entity_id INTEGER,
        entity_name TEXT DEFAULT '',
        metadata TEXT DEFAULT '{}',
        created_at TEXT DEFAULT (NOW()::TEXT)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS store_settings (
        id INTEGER PRIMARY KEY DEFAULT 1,
        logo_path TEXT DEFAULT '',
        brand_colors TEXT DEFAULT '[]',
        brand_style TEXT DEFAULT '',
        font_style TEXT DEFAULT '',
        mood TEXT DEFAULT '',
        business_phone TEXT DEFAULT '',
        business_email TEXT DEFAULT '',
        business_address TEXT DEFAULT '',
        business_website TEXT DEFAULT '',
        business_tagline TEXT DEFAULT '',
        social_instagram TEXT DEFAULT '',
        social_facebook TEXT DEFAULT '',
        social_twitter TEXT DEFAULT '',
        social_tiktok TEXT DEFAULT '',
        social_whatsapp TEXT DEFAULT '',
        business_hours TEXT DEFAULT '',
        category TEXT DEFAULT 'general',
        updated_at TEXT DEFAULT (NOW()::TEXT)
    )''')

    # Migrate posts table — keep original photo alongside AI-edited version
    for _col, _def in [
        ('original_image_path', "TEXT DEFAULT ''"),
    ]:
        c.execute(
            f"ALTER TABLE posts ADD COLUMN IF NOT EXISTS {_col} {_def}"
        )

    # Migrate existing databases that pre-date profile columns
    for _col, _def in [
        ('business_phone', "TEXT DEFAULT ''"),
        ('business_email', "TEXT DEFAULT ''"),
        ('business_address', "TEXT DEFAULT ''"),
        ('business_website', "TEXT DEFAULT ''"),
        ('business_tagline', "TEXT DEFAULT ''"),
        ('social_instagram', "TEXT DEFAULT ''"),
        ('social_facebook', "TEXT DEFAULT ''"),
        ('social_twitter', "TEXT DEFAULT ''"),
        ('social_tiktok', "TEXT DEFAULT ''"),
        ('social_whatsapp', "TEXT DEFAULT ''"),
        ('business_hours', "TEXT DEFAULT ''"),
        ('market_audience', "TEXT DEFAULT ''"),
        ('category', "TEXT DEFAULT 'general'"),
    ]:
        c.execute(
            f"ALTER TABLE store_settings ADD COLUMN IF NOT EXISTS {_col} {_def}"
        )

    conn.commit()


def get_follows_db():
    """Return a connection to the platform-level myfomo follows table.

    Stored in the public schema of the shared neondb database.
    One row per (user_email, tenant_slug).
    """
    conn = get_platform_connection()
    cache_key = "_follows_init"
    if not getattr(g, cache_key, False):
        conn.execute("""
            CREATE TABLE IF NOT EXISTS follows (
                user_email  TEXT NOT NULL,
                tenant_slug TEXT NOT NULL,
                followed_at TEXT DEFAULT (NOW()::TEXT),
                PRIMARY KEY (user_email, tenant_slug)
            )
        """)
        conn.commit()
        setattr(g, cache_key, True)
    return conn


def init_myfomo_db(tenant_slug):
    """Initialize the myfomo database schema for a tenant using raw SQL."""
    from core.tenants.db_manager import create_tenant_schema
    create_tenant_schema(tenant_slug)

    conn = get_tenant_connection(tenant_slug)
    _ensure_myfomo_tables(conn)
