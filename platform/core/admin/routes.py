"""Platform Admin dashboard — management endpoints for platform_admin users."""

from functools import wraps

import jwt
from flask import request, jsonify, render_template, current_app
from sqlalchemy import func

from core.admin import admin_bp
from core.extensions import db
from core.models import User, Tenant, AppDefinition, Subscription


def platform_admin_required(f):
    """Require a valid JWT with role == platform_admin."""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
        if not token:
            token = request.cookies.get("token")
        if not token:
            return jsonify({"error": "Authentication required"}), 401

        try:
            payload = jwt.decode(
                token, current_app.config["SECRET_KEY"], algorithms=["HS256"]
            )
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token has expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid token"}), 401

        user = db.session.get(User, payload["user_id"])
        if not user or not user.is_active:
            return jsonify({"error": "User not found or inactive"}), 401
        if user.role != "platform_admin":
            return jsonify({"error": "Platform admin access required"}), 403

        request.current_user = user
        return f(*args, **kwargs)
    return decorated


# ── Dashboard page ──────────────────────────────────────────────────

@admin_bp.route("/")
def admin_dashboard():
    return render_template("dashboard/admin.html")


# ── Stats ───────────────────────────────────────────────────────────

@admin_bp.route("/api/stats")
@platform_admin_required
def admin_stats():
    total_users = User.query.count()
    total_tenants = Tenant.query.count()

    subs = (
        db.session.query(Subscription.plan, func.count(Subscription.id))
        .group_by(Subscription.plan)
        .all()
    )
    subscriptions = {plan: count for plan, count in subs}

    return jsonify({
        "total_users": total_users,
        "total_tenants": total_tenants,
        "subscriptions": subscriptions,
    })


# ── Users ───────────────────────────────────────────────────────────

@admin_bp.route("/api/users")
@platform_admin_required
def admin_list_users():
    search = request.args.get("search", "").strip()
    query = User.query
    if search:
        like = f"%{search}%"
        query = query.filter(
            db.or_(User.email.ilike(like), User.name.ilike(like))
        )
    users = query.order_by(User.id).all()
    return jsonify([
        {
            "id": u.id,
            "email": u.email,
            "name": u.name,
            "role": u.role,
            "is_active": u.is_active,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in users
    ])


@admin_bp.route("/api/users/<int:user_id>/toggle-active", methods=["PUT"])
@platform_admin_required
def admin_toggle_user_active(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
    if user.id == request.current_user.id:
        return jsonify({"error": "Cannot deactivate yourself"}), 400
    user.is_active = not user.is_active
    db.session.commit()
    return jsonify({"id": user.id, "is_active": user.is_active})


@admin_bp.route("/api/users/<int:user_id>/role", methods=["PUT"])
@platform_admin_required
def admin_change_user_role(user_id):
    data = request.get_json() or {}
    new_role = data.get("role", "")
    if new_role not in ("platform_admin", "business_owner", "client"):
        return jsonify({"error": "Invalid role"}), 400

    user = db.session.get(User, user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    user.role = new_role
    db.session.commit()
    return jsonify({"id": user.id, "role": user.role})


# ── Tenants ─────────────────────────────────────────────────────────

@admin_bp.route("/api/tenants")
@platform_admin_required
def admin_list_tenants():
    tenants = Tenant.query.order_by(Tenant.id).all()
    result = []
    for t in tenants:
        owner = db.session.get(User, t.owner_id)
        sub = Subscription.query.filter_by(tenant_id=t.id).first()
        result.append({
            "id": t.id,
            "name": t.name,
            "slug": t.slug,
            "app_type": t.app_type_slug,
            "owner_name": owner.name if owner else "N/A",
            "owner_email": owner.email if owner else "N/A",
            "plan": sub.plan if sub else "none",
            "status": t.status,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        })
    return jsonify(result)


@admin_bp.route("/api/tenants/<int:tenant_id>/suspend", methods=["PUT"])
@platform_admin_required
def admin_suspend_tenant(tenant_id):
    tenant = db.session.get(Tenant, tenant_id)
    if not tenant:
        return jsonify({"error": "Tenant not found"}), 404
    tenant.status = "suspended"
    db.session.commit()
    return jsonify({"id": tenant.id, "status": tenant.status})


@admin_bp.route("/api/tenants/<int:tenant_id>/reactivate", methods=["PUT"])
@platform_admin_required
def admin_reactivate_tenant(tenant_id):
    tenant = db.session.get(Tenant, tenant_id)
    if not tenant:
        return jsonify({"error": "Tenant not found"}), 404
    tenant.status = "active"
    db.session.commit()
    return jsonify({"id": tenant.id, "status": tenant.status})


# ── Apps ────────────────────────────────────────────────────────────

@admin_bp.route("/api/apps")
@platform_admin_required
def admin_list_apps():
    apps = AppDefinition.query.order_by(AppDefinition.id).all()
    return jsonify([
        {
            "id": a.id,
            "slug": a.slug,
            "name": a.name,
            "description": a.description,
            "icon": a.icon,
            "is_active": a.is_active,
        }
        for a in apps
    ])


@admin_bp.route("/api/apps/<int:app_id>/toggle-active", methods=["PUT"])
@platform_admin_required
def admin_toggle_app_active(app_id):
    app_def = db.session.get(AppDefinition, app_id)
    if not app_def:
        return jsonify({"error": "App not found"}), 404
    app_def.is_active = not app_def.is_active
    db.session.commit()
    return jsonify({"id": app_def.id, "is_active": app_def.is_active})
