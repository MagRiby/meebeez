"""Shop app blueprint — full CRUD endpoints."""

from datetime import date
from functools import wraps

import jwt as pyjwt
from flask import (
    Blueprint, jsonify, request, session, redirect, url_for,
    render_template, current_app,
)
from werkzeug.security import generate_password_hash, check_password_hash

from apps.shop.db_utils import get_shop_db

shop_bp = Blueprint(
    "shop",
    __name__,
    url_prefix="/t/<tenant_slug>/shop",
)


# ── SSO helper ──────────────────────────────────────────────────────

def _sso_auto_login(tenant_slug):
    """Auto-login using the platform JWT cookie. Returns True on success."""
    token = request.cookies.get("token")
    if not token:
        return False
    try:
        payload = pyjwt.decode(token, current_app.config["SECRET_KEY"], algorithms=["HS256"])
        email = payload.get("email")
        if not email:
            return False
    except Exception:
        return False
    db = get_shop_db(tenant_slug)
    user = db.execute("SELECT * FROM users WHERE username=%s AND is_active=1", (email,)).fetchone()
    if not user:
        return False
    session["shop_user_id"] = user["id"]
    session["shop_role"] = user["role"]
    session["shop_username"] = user["username"]
    session["shop_tenant"] = tenant_slug
    return True


# ── Auth decorator ──────────────────────────────────────────────────

def login_required(*roles):
    """Require the user to be logged into the shop tenant app."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            tenant_slug = kwargs.get("tenant_slug", "")
            if "shop_user_id" not in session or session.get("shop_tenant") != tenant_slug:
                if not _sso_auto_login(tenant_slug):
                    return redirect("/")
            if roles and session.get("shop_role") not in roles:
                return "Unauthorized", 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator


# ── Auth routes ─────────────────────────────────────────────────────

@shop_bp.route("/")
def index(tenant_slug):
    if "shop_user_id" in session and session.get("shop_tenant") == tenant_slug:
        return redirect(url_for("shop.dashboard", tenant_slug=tenant_slug))
    if _sso_auto_login(tenant_slug):
        return redirect(url_for("shop.dashboard", tenant_slug=tenant_slug))
    return redirect("/home")


@shop_bp.route("/login", methods=["GET", "POST"])
def shop_login(tenant_slug):
    if request.method == "GET":
        return render_template("shop/login.html", tenant_slug=tenant_slug)

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    if not username or not password:
        return render_template("shop/login.html", tenant_slug=tenant_slug, error="Username and password are required")

    db = get_shop_db(tenant_slug)
    user = db.execute("SELECT * FROM users WHERE username=%s AND is_active=1", (username,)).fetchone()

    if not user or not check_password_hash(user["password_hash"], password):
        return render_template("shop/login.html", tenant_slug=tenant_slug, error="Invalid credentials")

    session["shop_user_id"] = user["id"]
    session["shop_role"] = user["role"]
    session["shop_username"] = user["username"]
    session["shop_tenant"] = tenant_slug
    return redirect(url_for("shop.dashboard", tenant_slug=tenant_slug))


@shop_bp.route("/logout")
def shop_logout(tenant_slug):
    session.pop("shop_user_id", None)
    session.pop("shop_role", None)
    session.pop("shop_username", None)
    session.pop("shop_tenant", None)
    return redirect("/signout")


# ── Dashboard ───────────────────────────────────────────────────────

@shop_bp.route("/dashboard")
@login_required()
def dashboard(tenant_slug):
    return render_template(
        "shop/dashboard.html",
        tenant_slug=tenant_slug,
        role=session.get("shop_role"),
        username=session.get("shop_username"),
    )


# ── Categories CRUD ─────────────────────────────────────────────────

@shop_bp.route("/api/categories", methods=["GET"])
@login_required()
def list_categories(tenant_slug):
    db = get_shop_db(tenant_slug)
    rows = db.execute("SELECT * FROM categories ORDER BY id").fetchall()
    return jsonify([dict(r) for r in rows])


@shop_bp.route("/api/categories", methods=["POST"])
@login_required("admin")
def create_category(tenant_slug):
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "Name is required"}), 400

    db = get_shop_db(tenant_slug)
    db.execute(
        "INSERT INTO categories (name, description, is_active) VALUES (%s, %s, %s)",
        (name, data.get("description", ""), 1),
    )
    db.commit()
    return jsonify({"message": "Category created"}), 201


@shop_bp.route("/api/categories/<int:cat_id>", methods=["PUT"])
@login_required("admin")
def update_category(tenant_slug, cat_id):
    data = request.get_json() or {}
    db = get_shop_db(tenant_slug)
    existing = db.execute("SELECT id FROM categories WHERE id=%s", (cat_id,)).fetchone()
    if not existing:
        return jsonify({"error": "Category not found"}), 404

    db.execute(
        "UPDATE categories SET name=%s, description=%s, is_active=%s WHERE id=%s",
        (data.get("name", ""), data.get("description", ""),
         1 if data.get("is_active", True) else 0, cat_id),
    )
    db.commit()
    return jsonify({"message": "Category updated"})


@shop_bp.route("/api/categories/<int:cat_id>", methods=["DELETE"])
@login_required("admin")
def delete_category(tenant_slug, cat_id):
    db = get_shop_db(tenant_slug)
    db.execute("DELETE FROM categories WHERE id=%s", (cat_id,))
    db.commit()
    return jsonify({"message": "Category deleted"})


# ── Products CRUD ───────────────────────────────────────────────────

@shop_bp.route("/api/products", methods=["GET"])
@login_required()
def list_products(tenant_slug):
    db = get_shop_db(tenant_slug)
    query = """
        SELECT p.*, c.name AS category_name
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        WHERE 1=1
    """
    params = []

    search = request.args.get("search", "").strip()
    if search:
        like = f"%{search}%"
        query += " AND (p.name LIKE ? OR p.sku LIKE ? OR p.description LIKE ?)"
        params.extend([like, like, like])

    category_id = request.args.get("category_id")
    if category_id:
        query += " AND p.category_id = ?"
        params.append(category_id)

    query += " ORDER BY p.id"
    rows = db.execute(query, params).fetchall()
    return jsonify([dict(r) for r in rows])


@shop_bp.route("/api/products", methods=["POST"])
@login_required("admin")
def create_product(tenant_slug):
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "Name is required"}), 400

    db = get_shop_db(tenant_slug)
    db.execute(
        """INSERT INTO products (name, sku, description, category_id, price, cost, quantity, low_stock_threshold, is_active)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (name, data.get("sku", ""), data.get("description", ""),
         data.get("category_id"), data.get("price", 0.0), data.get("cost", 0.0),
         data.get("quantity", 0), data.get("low_stock_threshold", 10), 1),
    )
    db.commit()
    return jsonify({"message": "Product created"}), 201


@shop_bp.route("/api/products/<int:prod_id>", methods=["PUT"])
@login_required("admin")
def update_product(tenant_slug, prod_id):
    data = request.get_json() or {}
    db = get_shop_db(tenant_slug)
    existing = db.execute("SELECT id FROM products WHERE id=%s", (prod_id,)).fetchone()
    if not existing:
        return jsonify({"error": "Product not found"}), 404

    db.execute(
        """UPDATE products SET name=%s, sku=%s, description=%s, category_id=%s, price=%s, cost=%s,
           quantity=%s, low_stock_threshold=%s, is_active=%s WHERE id=%s""",
        (data.get("name", ""), data.get("sku", ""), data.get("description", ""),
         data.get("category_id"), data.get("price", 0.0), data.get("cost", 0.0),
         data.get("quantity", 0), data.get("low_stock_threshold", 10),
         1 if data.get("is_active", True) else 0, prod_id),
    )
    db.commit()
    return jsonify({"message": "Product updated"})


@shop_bp.route("/api/products/<int:prod_id>", methods=["DELETE"])
@login_required("admin")
def delete_product(tenant_slug, prod_id):
    db = get_shop_db(tenant_slug)
    db.execute("DELETE FROM products WHERE id=%s", (prod_id,))
    db.commit()
    return jsonify({"message": "Product deleted"})


# ── Suppliers CRUD ──────────────────────────────────────────────────

@shop_bp.route("/api/suppliers", methods=["GET"])
@login_required()
def list_suppliers(tenant_slug):
    db = get_shop_db(tenant_slug)
    rows = db.execute("SELECT * FROM suppliers ORDER BY id").fetchall()
    return jsonify([dict(r) for r in rows])


@shop_bp.route("/api/suppliers", methods=["POST"])
@login_required("admin")
def create_supplier(tenant_slug):
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "Name is required"}), 400

    db = get_shop_db(tenant_slug)
    db.execute(
        "INSERT INTO suppliers (name, contact_name, email, phone, address, notes) VALUES (%s, %s, %s, %s, %s, %s)",
        (name, data.get("contact_name", ""), data.get("email", ""),
         data.get("phone", ""), data.get("address", ""), data.get("notes", "")),
    )
    db.commit()
    return jsonify({"message": "Supplier created"}), 201


@shop_bp.route("/api/suppliers/<int:sup_id>", methods=["PUT"])
@login_required("admin")
def update_supplier(tenant_slug, sup_id):
    data = request.get_json() or {}
    db = get_shop_db(tenant_slug)
    existing = db.execute("SELECT id FROM suppliers WHERE id=%s", (sup_id,)).fetchone()
    if not existing:
        return jsonify({"error": "Supplier not found"}), 404

    db.execute(
        "UPDATE suppliers SET name=%s, contact_name=%s, email=%s, phone=%s, address=%s, notes=%s WHERE id=%s",
        (data.get("name", ""), data.get("contact_name", ""), data.get("email", ""),
         data.get("phone", ""), data.get("address", ""), data.get("notes", ""), sup_id),
    )
    db.commit()
    return jsonify({"message": "Supplier updated"})


@shop_bp.route("/api/suppliers/<int:sup_id>", methods=["DELETE"])
@login_required("admin")
def delete_supplier(tenant_slug, sup_id):
    db = get_shop_db(tenant_slug)
    db.execute("DELETE FROM suppliers WHERE id=%s", (sup_id,))
    db.commit()
    return jsonify({"message": "Supplier deleted"})


# ── Purchase Orders CRUD ────────────────────────────────────────────

@shop_bp.route("/api/purchase-orders", methods=["GET"])
@login_required()
def list_purchase_orders(tenant_slug):
    db = get_shop_db(tenant_slug)
    query = """
        SELECT po.*, s.name AS supplier_name
        FROM purchase_orders po
        LEFT JOIN suppliers s ON po.supplier_id = s.id
        WHERE 1=1
    """
    params = []

    status_filter = request.args.get("status")
    if status_filter:
        query += " AND po.status = ?"
        params.append(status_filter)

    query += " ORDER BY po.id DESC"
    rows = db.execute(query, params).fetchall()
    result = []
    for r in rows:
        po = dict(r)
        items = db.execute(
            """SELECT poi.*, p.name AS product_name
               FROM purchase_order_items poi
               LEFT JOIN products p ON poi.product_id = p.id
               WHERE poi.purchase_order_id = %s""",
            (po["id"],),
        ).fetchall()
        po["items"] = [dict(i) for i in items]
        result.append(po)
    return jsonify(result)


@shop_bp.route("/api/purchase-orders", methods=["POST"])
@login_required("admin")
def create_purchase_order(tenant_slug):
    data = request.get_json() or {}
    if not data.get("supplier_id"):
        return jsonify({"error": "supplier_id is required"}), 400
    items = data.get("items", [])
    if not items:
        return jsonify({"error": "At least one item is required"}), 400

    total = sum(i.get("quantity", 0) * i.get("unit_cost", 0) for i in items)

    db = get_shop_db(tenant_slug)
    cur_result = db.execute(
        "INSERT INTO purchase_orders (supplier_id, order_date, status, total_amount, notes) VALUES (%s, %s, %s, %s, %s)",
        (data["supplier_id"], data.get("order_date", date.today().isoformat()),
         "pending", total, data.get("notes", "")),
    )
    po_id = cur_result.fetchone()[0]

    for item in items:
        db.execute(
            "INSERT INTO purchase_order_items (purchase_order_id, product_id, quantity, unit_cost) VALUES (%s, %s, %s, %s)",
            (po_id, item["product_id"], item.get("quantity", 0), item.get("unit_cost", 0)),
        )

    db.commit()
    return jsonify({"message": "Purchase order created", "id": po_id}), 201


@shop_bp.route("/api/purchase-orders/<int:po_id>", methods=["PUT"])
@login_required("admin")
def update_purchase_order(tenant_slug, po_id):
    data = request.get_json() or {}
    db = get_shop_db(tenant_slug)
    existing = db.execute("SELECT * FROM purchase_orders WHERE id=%s", (po_id,)).fetchone()
    if not existing:
        return jsonify({"error": "Purchase order not found"}), 404

    new_status = data.get("status", existing["status"])
    old_status = existing["status"]

    db.execute(
        "UPDATE purchase_orders SET status=%s, notes=%s WHERE id=%s",
        (new_status, data.get("notes", existing["notes"]), po_id),
    )

    # Auto-update stock when status changes to "received"
    if new_status == "received" and old_status != "received":
        items = db.execute(
            "SELECT product_id, quantity FROM purchase_order_items WHERE purchase_order_id=%s",
            (po_id,),
        ).fetchall()
        for item in items:
            db.execute(
                "UPDATE products SET quantity = quantity + %s WHERE id=%s",
                (item["quantity"], item["product_id"]),
            )

    db.commit()
    return jsonify({"message": "Purchase order updated"})


# ── Sales CRUD ──────────────────────────────────────────────────────

@shop_bp.route("/api/sales", methods=["GET"])
@login_required()
def list_sales(tenant_slug):
    db = get_shop_db(tenant_slug)
    query = "SELECT * FROM sales WHERE 1=1"
    params = []

    date_filter = request.args.get("date")
    if date_filter:
        query += " AND date = ?"
        params.append(date_filter)

    query += " ORDER BY id DESC"
    rows = db.execute(query, params).fetchall()
    result = []
    for r in rows:
        sale = dict(r)
        items = db.execute(
            """SELECT si.*, p.name AS product_name
               FROM sale_items si
               LEFT JOIN products p ON si.product_id = p.id
               WHERE si.sale_id = %s""",
            (sale["id"],),
        ).fetchall()
        sale["items"] = [dict(i) for i in items]
        result.append(sale)
    return jsonify(result)


@shop_bp.route("/api/sales/<int:sale_id>", methods=["GET"])
@login_required()
def get_sale(tenant_slug, sale_id):
    db = get_shop_db(tenant_slug)
    row = db.execute("SELECT * FROM sales WHERE id=%s", (sale_id,)).fetchone()
    if not row:
        return jsonify({"error": "Sale not found"}), 404
    sale = dict(row)
    items = db.execute(
        """SELECT si.*, p.name AS product_name
           FROM sale_items si
           LEFT JOIN products p ON si.product_id = p.id
           WHERE si.sale_id = %s""",
        (sale_id,),
    ).fetchall()
    sale["items"] = [dict(i) for i in items]
    return jsonify(sale)


@shop_bp.route("/api/sales", methods=["POST"])
@login_required()
def create_sale(tenant_slug):
    data = request.get_json() or {}
    items = data.get("items", [])
    if not items:
        return jsonify({"error": "At least one item is required"}), 400

    total = sum(i.get("quantity", 0) * i.get("unit_price", 0) for i in items)

    db = get_shop_db(tenant_slug)
    cur_result = db.execute(
        "INSERT INTO sales (date, total_amount, payment_method, notes, created_by) VALUES (%s, %s, %s, %s, %s)",
        (data.get("date", date.today().isoformat()), total,
         data.get("payment_method", "cash"), data.get("notes", ""),
         session.get("shop_user_id")),
    )
    sale_id = cur_result.fetchone()[0]

    for item in items:
        db.execute(
            "INSERT INTO sale_items (sale_id, product_id, quantity, unit_price) VALUES (%s, %s, %s, %s)",
            (sale_id, item["product_id"], item.get("quantity", 0), item.get("unit_price", 0)),
        )
        # Deduct stock
        db.execute(
            "UPDATE products SET quantity = quantity - %s WHERE id=%s",
            (item.get("quantity", 0), item["product_id"]),
        )

    db.commit()
    return jsonify({"message": "Sale created", "id": sale_id}), 201


# ── Inventory ───────────────────────────────────────────────────────

@shop_bp.route("/api/inventory/low-stock", methods=["GET"])
@login_required()
def low_stock(tenant_slug):
    db = get_shop_db(tenant_slug)
    rows = db.execute(
        """SELECT p.*, c.name AS category_name
           FROM products p
           LEFT JOIN categories c ON p.category_id = c.id
           WHERE p.is_active = 1 AND p.quantity <= p.low_stock_threshold
           ORDER BY p.quantity ASC""",
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@shop_bp.route("/api/inventory/adjust", methods=["PUT"])
@login_required("admin")
def adjust_stock(tenant_slug):
    data = request.get_json() or {}
    product_id = data.get("product_id")
    adjustment = data.get("adjustment", 0)
    if not product_id:
        return jsonify({"error": "product_id is required"}), 400

    db = get_shop_db(tenant_slug)
    existing = db.execute("SELECT id, quantity FROM products WHERE id=%s", (product_id,)).fetchone()
    if not existing:
        return jsonify({"error": "Product not found"}), 404

    new_qty = existing["quantity"] + adjustment
    if new_qty < 0:
        return jsonify({"error": "Stock cannot go below zero"}), 400

    db.execute("UPDATE products SET quantity=%s WHERE id=%s", (new_qty, product_id))
    db.commit()
    return jsonify({"message": "Stock adjusted", "new_quantity": new_qty})
