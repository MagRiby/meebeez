import uuid
import re
from datetime import datetime, timezone

from core.extensions import db
from core.models import AppDefinition, Tenant, TenantMembership, Subscription
from core.tenants.db_manager import create_tenant_db, get_tenant_engine


def _slugify(text):
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return re.sub(r"-+", "-", text).strip("-")


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

    # Create the tenant database
    create_tenant_db(db_name)

    # Run the app's schema setup on the new database
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

    db.session.commit()

    return tenant
