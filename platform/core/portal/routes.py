import json

from flask import request, jsonify, render_template

from core.portal import portal_bp
from core.models import Tenant, TenantMembership, AppDefinition
from core.auth.routes import auth_required
from core.tenants.db_manager import get_tenant_connection


@portal_bp.route("/api/portal", methods=["GET"])
@auth_required
def portal_api():
    """Get the client's unified view of all businesses they belong to."""
    user = request.current_user
    memberships = TenantMembership.query.filter_by(user_id=user.id).all()

    tenant_ids = [m.tenant_id for m in memberships]
    # Exclude tenants whose app type has been deactivated
    active_app_slugs = {a.slug for a in AppDefinition.query.filter_by(is_active=True).all()}
    tenants = [
        t for t in Tenant.query.filter(Tenant.id.in_(tenant_ids)).all()
        if t.app_type_slug in active_app_slugs
    ]

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


@portal_bp.route("/api/search", methods=["GET"])
def search():
    """Search businesses by name, or published items across all myfomo tenants."""
    q = request.args.get("q", "").strip()
    search_type = request.args.get("type", "all")

    if len(q) < 2:
        return jsonify({})

    def _search_businesses():
        active_app_slugs = {a.slug for a in AppDefinition.query.filter_by(is_active=True).all()}
        tenants = Tenant.query.filter(
            Tenant.name.ilike(f"%{q}%"),
            Tenant.status == "active",
            Tenant.app_type_slug.in_(active_app_slugs),
        ).limit(20).all()
        return [{"name": t.name, "slug": t.slug, "app_type": t.app_type_slug} for t in tenants]

    def _search_items():
        results = []
        like_q = f"%{q}%"

        def _query(slug, sql, params):
            try:
                conn = get_tenant_connection(slug)
                rows = conn.execute(sql, params).fetchall()
                return rows
            except Exception:
                return []

        # myfomo — published posts
        for tenant in Tenant.query.filter_by(app_type_slug="myfomo", status="active").all():
            for row in _query(tenant.slug,
                "SELECT id, title, body, image_path, price, original_quantity, remaining_quantity "
                "FROM posts WHERE status='published' AND (title ILIKE %s OR body ILIKE %s) LIMIT 10",
                (like_q, like_q)):
                results.append({
                    "item_id": row["id"],
                    "title": row["title"],
                    "body": (row["body"] or "")[:120],
                    "image_path": row["image_path"] or "",
                    "price": row["price"],
                    "original_quantity": row["original_quantity"],
                    "remaining_quantity": row["remaining_quantity"],
                    "item_type": "product",
                    "business_name": tenant.name,
                    "business_slug": tenant.slug,
                    "business_app_type": "myfomo",
                })

        # barber — services
        for tenant in Tenant.query.filter_by(app_type_slug="barber", status="active").all():
            for row in _query(tenant.slug,
                "SELECT id, name, description, price FROM services "
                "WHERE is_active=1 AND (name ILIKE %s OR description ILIKE %s) LIMIT 10",
                (like_q, like_q)):
                results.append({
                    "item_id": row["id"],
                    "title": row["name"],
                    "body": (row["description"] or "")[:120],
                    "image_path": "",
                    "price": row["price"],
                    "remaining_quantity": None,
                    "item_type": "service",
                    "business_name": tenant.name,
                    "business_slug": tenant.slug,
                    "business_app_type": "barber",
                })

        # shop — products
        for tenant in Tenant.query.filter_by(app_type_slug="shop", status="active").all():
            for row in _query(tenant.slug,
                "SELECT id, name, description, price, quantity FROM products "
                "WHERE is_active=1 AND (name ILIKE %s OR description ILIKE %s) LIMIT 10",
                (like_q, like_q)):
                results.append({
                    "item_id": row["id"],
                    "title": row["name"],
                    "body": (row["description"] or "")[:120],
                    "image_path": "",
                    "price": row["price"],
                    "remaining_quantity": row["quantity"],
                    "item_type": "product",
                    "business_name": tenant.name,
                    "business_slug": tenant.slug,
                    "business_app_type": "shop",
                })

        # school — classes
        for tenant in Tenant.query.filter_by(app_type_slug="school", status="active").all():
            for row in _query(tenant.slug,
                "SELECT id, name FROM classes WHERE name ILIKE %s LIMIT 10",
                (like_q,)):
                results.append({
                    "item_id": row["id"],
                    "title": row["name"],
                    "body": "",
                    "image_path": "",
                    "price": None,
                    "remaining_quantity": None,
                    "item_type": "class",
                    "business_name": tenant.name,
                    "business_slug": tenant.slug,
                    "business_app_type": "school",
                })

        return results[:40]

    if search_type == "businesses":
        return jsonify({"businesses": _search_businesses(), "items": []})
    if search_type == "items":
        return jsonify({"businesses": [], "items": _search_items()})
    # type == "all"
    return jsonify({"businesses": _search_businesses(), "items": _search_items()})


@portal_bp.route("/home", methods=["GET"])
def platform_home():
    """Unified platform home for all users."""
    return render_template("dashboard/home.html")


@portal_bp.route("/api/home-data", methods=["GET"])
@auth_required
def home_data():
    """Role-aware home data: owner gets their tenants, client gets followed businesses."""
    user = request.current_user

    _app_type_to_category = {
        "school": "education",
        "barber": "services",
        "shop": "shopping",
    }

    def _enrich_myfomo(slug):
        try:
            conn = get_tenant_connection(slug)
            row = conn.execute(
                "SELECT logo_path, brand_colors, category, business_tagline "
                "FROM store_settings WHERE id=1"
            ).fetchone()
            if row:
                return {
                    "logo_path": row["logo_path"] or "",
                    "brand_colors": json.loads(row["brand_colors"] or "[]"),
                    "category": row["category"] or "general",
                    "tagline": row["business_tagline"] or "",
                }
        except Exception:
            pass
        return {}

    if user.role in ("business_owner", "platform_admin"):
        active_app_slugs = {a.slug for a in AppDefinition.query.filter_by(is_active=True).all()}
        tenants = [
            t for t in Tenant.query.filter_by(owner_id=user.id).order_by(Tenant.created_at).all()
            if t.app_type_slug in active_app_slugs
        ]
        result = []
        for t in tenants:
            info = {
                "name": t.name,
                "slug": t.slug,
                "app_type": t.app_type_slug,
                "status": t.status,
                "logo_path": "",
                "brand_colors": [],
                "category": "general",
                "tagline": "",
            }
            if t.app_type_slug == "myfomo":
                info.update(_enrich_myfomo(t.slug))
            else:
                info["category"] = _app_type_to_category.get(t.app_type_slug, "general")
            result.append(info)
        return jsonify({"role": "business_owner", "name": user.name, "tenants": result})

    # client
    memberships = TenantMembership.query.filter_by(user_id=user.id).all()
    seen_slugs = set()
    all_tenants = []
    for m in memberships:
        t = m.tenant
        if t and t.status == "active" and t.slug not in seen_slugs:
            seen_slugs.add(t.slug)
            all_tenants.append(t)

    # Include myfomo follows (cross-tenant follows table in public schema)
    try:
        from apps.myfomo.db_utils import get_follows_db
        fdb = get_follows_db()
        follow_rows = fdb.execute(
            "SELECT tenant_slug FROM follows WHERE user_email=%s", (user.email,)
        ).fetchall()
        for row in follow_rows:
            slug = row["tenant_slug"]
            if slug not in seen_slugs:
                t = Tenant.query.filter_by(slug=slug, status="active").first()
                if t:
                    seen_slugs.add(slug)
                    all_tenants.append(t)
    except Exception:
        pass

    result = []
    for t in all_tenants:
        info = {
            "name": t.name,
            "slug": t.slug,
            "app_type": t.app_type_slug,
            "logo_path": "",
            "brand_colors": [],
            "category": "general",
            "tagline": "",
        }
        if t.app_type_slug == "myfomo":
            info.update(_enrich_myfomo(t.slug))
        else:
            info["category"] = _app_type_to_category.get(t.app_type_slug, "general")
        result.append(info)

    return jsonify({"role": "client", "name": user.name, "businesses": result})


@portal_bp.route("/dashboard", methods=["GET"])
def owner_dashboard():
    """Render the business owner dashboard."""
    return render_template("dashboard/owner.html")


@portal_bp.route("/portal", methods=["GET"])
def client_portal():
    """Render the client unified portal."""
    return render_template("dashboard/portal.html")
