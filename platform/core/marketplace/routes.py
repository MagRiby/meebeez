from flask import request, jsonify

from core.marketplace import marketplace_bp
from core.extensions import db
from core.models import AppDefinition, Tenant, TenantMembership, Subscription
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
        tenant, temp_password = provision_tenant(name, app_slug, user.id)
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
            "admin_credentials": {
                "email": user.email,
                "temp_password": temp_password,
                "warning": "Save this password now. It cannot be retrieved later.",
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

    # Exclude tenants whose app type has been deactivated
    active_app_slugs = {a.slug for a in AppDefinition.query.filter_by(is_active=True).all()}
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
            if t.app_type_slug in active_app_slugs
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


@marketplace_bp.route("/api/tenants/<slug>", methods=["PUT"])
@auth_required
def update_tenant(slug):
    """Update a tenant's name."""
    tenant = Tenant.query.filter_by(slug=slug).first()
    if not tenant:
        return jsonify({"error": "Tenant not found"}), 404

    user = request.current_user
    if tenant.owner_id != user.id and user.role != "platform_admin":
        return jsonify({"error": "Access denied"}), 403

    data = request.get_json() or {}
    name = data.get("name", "").strip()

    if not name:
        return jsonify({"error": "name is required"}), 400

    tenant.name = name
    db.session.commit()

    return jsonify(
        {
            "message": "Tenant updated successfully",
            "tenant": {
                "id": tenant.id,
                "name": tenant.name,
                "slug": tenant.slug,
                "app_type": tenant.app_type_slug,
                "status": tenant.status,
            },
        }
    )


@marketplace_bp.route("/api/tenants/<slug>", methods=["DELETE"])
@auth_required
def delete_tenant(slug):
    """Delete a tenant."""
    tenant = Tenant.query.filter_by(slug=slug).first()
    if not tenant:
        return jsonify({"error": "Tenant not found"}), 404

    user = request.current_user
    if tenant.owner_id != user.id and user.role != "platform_admin":
        return jsonify({"error": "Access denied"}), 403

    # Delete related records
    TenantMembership.query.filter_by(tenant_id=tenant.id).delete()
    Subscription.query.filter_by(tenant_id=tenant.id).delete()
    db.session.delete(tenant)
    db.session.commit()

    return jsonify({"message": "Tenant deleted successfully"})


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
