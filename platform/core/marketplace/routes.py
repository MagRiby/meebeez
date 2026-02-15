from flask import request, jsonify

from core.marketplace import marketplace_bp
from core.extensions import db
from core.models import AppDefinition, Tenant, TenantMembership
from core.auth.routes import auth_required
from core.tenants.service import provision_tenant


@marketplace_bp.route("/api/apps", methods=["GET"])
def list_apps():
    """List all available app types."""
    apps = AppDefinition.query.filter_by(is_active=True).all()
    return jsonify(
        [
            {
                "slug": a.slug,
                "name": a.name,
                "description": a.description,
                "icon": a.icon,
            }
            for a in apps
        ]
    )


@marketplace_bp.route("/api/tenants", methods=["POST"])
@auth_required
def create_tenant():
    """Create a new tenant (deploy an app)."""
    user = request.current_user
    if user.role not in ("business_owner", "platform_admin"):
        return jsonify({"error": "Only business owners can create tenants"}), 403

    data = request.get_json() or {}
    name = data.get("name", "").strip()
    app_slug = data.get("app_slug", "").strip()

    if not name or not app_slug:
        return jsonify({"error": "name and app_slug are required"}), 400

    try:
        tenant = provision_tenant(name, app_slug, user.id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    return jsonify(
        {
            "message": "Tenant created successfully",
            "tenant": {
                "id": tenant.id,
                "name": tenant.name,
                "slug": tenant.slug,
                "app_type": tenant.app_type_slug,
                "status": tenant.status,
                "db_name": tenant.db_name,
            },
        }
    ), 201


@marketplace_bp.route("/api/tenants", methods=["GET"])
@auth_required
def list_tenants():
    """List tenants the current user owns or is a member of."""
    user = request.current_user

    if user.role == "platform_admin":
        tenants = Tenant.query.all()
    elif user.role == "business_owner":
        tenants = Tenant.query.filter_by(owner_id=user.id).all()
    else:
        membership_ids = [
            m.tenant_id for m in TenantMembership.query.filter_by(user_id=user.id).all()
        ]
        tenants = Tenant.query.filter(Tenant.id.in_(membership_ids)).all()

    return jsonify(
        [
            {
                "id": t.id,
                "name": t.name,
                "slug": t.slug,
                "app_type": t.app_type_slug,
                "status": t.status,
            }
            for t in tenants
        ]
    )


@marketplace_bp.route("/api/tenants/<slug>", methods=["GET"])
@auth_required
def get_tenant(slug):
    """Get details of a specific tenant."""
    tenant = Tenant.query.filter_by(slug=slug).first()
    if not tenant:
        return jsonify({"error": "Tenant not found"}), 404

    user = request.current_user
    is_member = TenantMembership.query.filter_by(
        user_id=user.id, tenant_id=tenant.id
    ).first()

    if not is_member and user.role != "platform_admin":
        return jsonify({"error": "Access denied"}), 403

    return jsonify(
        {
            "id": tenant.id,
            "name": tenant.name,
            "slug": tenant.slug,
            "app_type": tenant.app_type_slug,
            "owner_id": tenant.owner_id,
            "status": tenant.status,
            "created_at": tenant.created_at.isoformat(),
            "subscription": {
                "plan": tenant.subscription.plan,
                "status": tenant.subscription.status,
            }
            if tenant.subscription
            else None,
        }
    )


@marketplace_bp.route("/api/tenants/<slug>/join", methods=["POST"])
@auth_required
def join_tenant(slug):
    """Join a tenant as a client."""
    tenant = Tenant.query.filter_by(slug=slug, status="active").first()
    if not tenant:
        return jsonify({"error": "Tenant not found or not active"}), 404

    user = request.current_user
    existing = TenantMembership.query.filter_by(
        user_id=user.id, tenant_id=tenant.id
    ).first()
    if existing:
        return jsonify({"error": "Already a member of this tenant"}), 409

    membership = TenantMembership(
        user_id=user.id,
        tenant_id=tenant.id,
        role_in_tenant="client",
    )
    db.session.add(membership)
    db.session.commit()

    return jsonify(
        {
            "message": "Joined tenant successfully",
            "tenant": {"name": tenant.name, "slug": tenant.slug},
            "role": "client",
        }
    ), 201
