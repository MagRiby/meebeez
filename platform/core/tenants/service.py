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


def provision_tenant(name, app_slug, owner_id):
    """Provision a new tenant: create schema, run DDL, create platform records."""
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

    # Always use PostgreSQL schema-per-tenant
    if hasattr(app_module, "setup_schema_sqlite"):
        # Repurposed: init_*_db functions now create PG schemas
        app_module.setup_schema_sqlite(slug)
    else:
        from core.tenants.db_manager import create_tenant_schema, get_tenant_connection
        create_tenant_schema(slug)

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
    from core.tenants.db_manager import get_tenant_connection

    conn = get_tenant_connection(tenant_slug)
    row = conn.execute(
        "SELECT id FROM users WHERE username=%s", (email,)
    ).fetchone()
    if not row:
        password_hash = generate_password_hash(password)
        conn.execute(
            "INSERT INTO users (username, password_hash, name, role, is_active) VALUES (%s, %s, %s, %s, %s)",
            (email, password_hash, name, "admin", 1),
        )
        conn.commit()


def _seed_shop_admin(tenant_slug, email, name, password):
    """Create an admin user in the shop tenant's database."""
    from apps.shop.db_utils import init_shop_db
    from core.tenants.db_manager import get_tenant_connection

    # Ensure the schema and shop tables exist
    init_shop_db(tenant_slug)

    conn = get_tenant_connection(tenant_slug)
    row = conn.execute(
        "SELECT id FROM users WHERE username=%s", (email,)
    ).fetchone()
    if not row:
        password_hash = generate_password_hash(password)
        conn.execute(
            "INSERT INTO users (username, password_hash, name, role, is_active) VALUES (%s, %s, %s, %s, %s)",
            (email, password_hash, name, "admin", 1),
        )
        conn.commit()


def _seed_school_admin(tenant_slug, email, name, password):
    """Create a super_admin user in the school tenant's database."""
    from core.tenants.db_manager import get_tenant_connection

    conn = get_tenant_connection(tenant_slug)
    row = conn.execute(
        "SELECT id FROM users WHERE username=%s", (email,)
    ).fetchone()
    if not row:
        password_hash = generate_password_hash(password)
        conn.execute(
            "INSERT INTO users (username, password_hash, name, role) VALUES (%s, %s, %s, %s)",
            (email, password_hash, name, "local_admin"),
        )
        conn.commit()


def _seed_myfomo_admin(tenant_slug, email, name, password):
    """Create an admin user in the myfomo tenant's database."""
    from apps.myfomo.db_utils import init_myfomo_db
    from core.tenants.db_manager import get_tenant_connection

    # Ensure the schema and myfomo tables exist
    init_myfomo_db(tenant_slug)

    conn = get_tenant_connection(tenant_slug)
    row = conn.execute(
        "SELECT id FROM users WHERE username=%s", (email,)
    ).fetchone()
    if not row:
        password_hash = generate_password_hash(password)
        conn.execute(
            "INSERT INTO users (username, password_hash, name, role, is_active) VALUES (%s, %s, %s, %s, %s)",
            (email, password_hash, name, "admin", 1),
        )
        conn.commit()
