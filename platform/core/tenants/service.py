import uuid
import re
import os
import secrets
from datetime import datetime, timezone

from flask import current_app
from werkzeug.security import generate_password_hash

from core.extensions import db
from core.models import AppDefinition, Tenant, TenantMembership, Subscription, User


def _generate_temp_password():
    """Generate a random temporary password for seeded admin accounts."""
    return secrets.token_urlsafe(16)


def _slugify(text):
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return re.sub(r"-+", "-", text).strip("-")


def _use_sqlite():
    """Check if we should use SQLite for tenant databases."""
    platform_uri = current_app.config.get("SQLALCHEMY_DATABASE_URI", "")
    return platform_uri.startswith("sqlite")


def provision_tenant(name, app_slug, owner_id):
    """Provision a new tenant: create DB, run schema, create platform records."""
    from apps import registry

    # Validate app exists
    app_def = AppDefinition.query.filter_by(slug=app_slug, is_active=True).first()
    if not app_def:
        raise ValueError(f"App type '{app_slug}' not found or inactive")

    # Get the app module from registry
    app_module = registry.get(app_slug)
    if not app_module:
        raise ValueError(f"App module '{app_slug}' not registered")

    # Generate unique slug and db name
    slug = _slugify(name)
    short_id = uuid.uuid4().hex[:8]
    if Tenant.query.filter_by(slug=slug).first():
        slug = f"{slug}-{short_id}"
    db_name = f"tenant_{slug.replace('-', '_')}_{short_id}"

    if _use_sqlite():
        # SQLite mode: use per-tenant SQLite files
        if hasattr(app_module, "setup_schema_sqlite"):
            app_module.setup_schema_sqlite(slug)
        else:
            # Fallback: create SQLite DB with SQLAlchemy models
            from sqlalchemy import create_engine
            instance_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                "instance", "tenants",
            )
            os.makedirs(instance_dir, exist_ok=True)
            engine = create_engine(f"sqlite:///{os.path.join(instance_dir, slug + '.db')}")
            app_module.setup_schema(engine)
            engine.dispose()
    else:
        # PostgreSQL mode: create a real database
        from core.tenants.db_manager import create_tenant_db, get_tenant_engine
        create_tenant_db(db_name)
        engine = get_tenant_engine(db_name)
        app_module.setup_schema(engine)

    # Create platform records
    tenant = Tenant(
        name=name,
        slug=slug,
        app_type_slug=app_slug,
        owner_id=owner_id,
        db_name=db_name,
        status="active",
    )
    db.session.add(tenant)
    db.session.flush()  # Get tenant.id

    membership = TenantMembership(
        user_id=owner_id,
        tenant_id=tenant.id,
        role_in_tenant="admin",
    )
    db.session.add(membership)

    subscription = Subscription(
        tenant_id=tenant.id,
        plan="free",
        status="active",
        started_at=datetime.now(timezone.utc),
    )
    db.session.add(subscription)

    # Create a default admin user in the tenant's own database
    temp_password = _generate_temp_password()
    platform_user = db.session.get(User, owner_id)
    if platform_user and app_slug == "school":
        _seed_school_admin(slug, platform_user.email, platform_user.name, temp_password)
    elif platform_user and app_slug == "barber":
        _seed_barber_admin(slug, platform_user.email, platform_user.name, temp_password)
    elif platform_user and app_slug == "shop":
        _seed_shop_admin(slug, platform_user.email, platform_user.name, temp_password)
    elif platform_user and app_slug == "myfomo":
        _seed_myfomo_admin(slug, platform_user.email, platform_user.name, temp_password)

    db.session.commit()

    return tenant, temp_password


def _seed_barber_admin(tenant_slug, email, name, password):
    """Create an admin user in the barber tenant's database."""
    import sqlite3

    db_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "instance", "tenants", f"{tenant_slug}.db",
    )
    if not os.path.exists(db_path):
        return

    conn = sqlite3.connect(db_path, timeout=10)
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE username=?", (email,))
    if not c.fetchone():
        password_hash = generate_password_hash(password)
        c.execute(
            "INSERT INTO users (username, password_hash, name, role, is_active) VALUES (?, ?, ?, ?, ?)",
            (email, password_hash, name, "admin", 1),
        )
        conn.commit()
    conn.close()


def _seed_shop_admin(tenant_slug, email, name, password):
    """Create an admin user in the shop tenant's database."""
    import sqlite3
    from apps.shop.db_utils import init_shop_db

    db_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "instance", "tenants", f"{tenant_slug}.db",
    )
    # Ensure the SQLite file and shop tables exist (even in PostgreSQL mode)
    if not os.path.exists(db_path):
        init_shop_db(tenant_slug)

    conn = sqlite3.connect(db_path, timeout=10)
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE username=?", (email,))
    if not c.fetchone():
        password_hash = generate_password_hash(password)
        c.execute(
            "INSERT INTO users (username, password_hash, name, role, is_active) VALUES (?, ?, ?, ?, ?)",
            (email, password_hash, name, "admin", 1),
        )
        conn.commit()
    conn.close()


def _seed_school_admin(tenant_slug, email, name, password):
    """Create a super_admin user in the school tenant's database."""
    import sqlite3

    db_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "instance", "tenants", f"{tenant_slug}.db",
    )
    if not os.path.exists(db_path):
        return

    conn = sqlite3.connect(db_path, timeout=10)
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE username=?", (email,))
    if not c.fetchone():
        password_hash = generate_password_hash(password)
        c.execute(
            "INSERT INTO users (username, password_hash, name, role) VALUES (?, ?, ?, ?)",
            (email, password_hash, name, "local_admin"),
        )
        conn.commit()
    conn.close()


def _seed_myfomo_admin(tenant_slug, email, name, password):
    """Create an admin user in the myfomo tenant's database."""
    import sqlite3
    from apps.myfomo.db_utils import init_myfomo_db

    db_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "instance", "tenants", f"{tenant_slug}.db",
    )
    if not os.path.exists(db_path):
        init_myfomo_db(tenant_slug)

    conn = sqlite3.connect(db_path, timeout=10)
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE username=?", (email,))
    if not c.fetchone():
        password_hash = generate_password_hash(password)
        c.execute(
            "INSERT INTO users (username, password_hash, name, role, is_active) VALUES (?, ?, ?, ?, ?)",
            (email, password_hash, name, "admin", 1),
        )
        conn.commit()
    conn.close()
