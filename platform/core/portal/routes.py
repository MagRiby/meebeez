from flask import request, jsonify, render_template

from core.portal import portal_bp
from core.models import Tenant, TenantMembership
from core.auth.routes import auth_required


@portal_bp.route("/api/portal", methods=["GET"])
@auth_required
def portal_api():
    """Get the client's unified view of all businesses they belong to."""
    user = request.current_user
    memberships = TenantMembership.query.filter_by(user_id=user.id).all()

    tenant_ids = [m.tenant_id for m in memberships]
    tenants = Tenant.query.filter(Tenant.id.in_(tenant_ids)).all()

    membership_map = {m.tenant_id: m.role_in_tenant for m in memberships}

    return jsonify(
        [
            {
                "id": t.id,
                "name": t.name,
                "slug": t.slug,
                "app_type": t.app_type_slug,
                "status": t.status,
                "role": membership_map.get(t.id, "client"),
            }
            for t in tenants
        ]
    )


@portal_bp.route("/dashboard", methods=["GET"])
def owner_dashboard():
    """Render the business owner dashboard."""
    return render_template("dashboard/owner.html")


@portal_bp.route("/portal", methods=["GET"])
def client_portal():
    """Render the client unified portal."""
    return render_template("dashboard/portal.html")
