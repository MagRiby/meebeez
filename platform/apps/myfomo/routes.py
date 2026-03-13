"""myFomo app blueprint — social commerce / advertising routes."""

import os
import uuid
import json
import secrets
import urllib.request
from functools import wraps

import jwt as pyjwt
from flask import (
    Blueprint, jsonify, request, session, redirect, url_for,
    render_template, current_app,
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from apps.myfomo.db_utils import get_myfomo_db, get_follows_db
from apps.myfomo.ai_utils import analyze_image, analyze_logo, generate_ad_copy, generate_event_description, generate_ad_image, generate_ad_text_overlay

myfomo_bp = Blueprint(
    "myfomo",
    __name__,
    url_prefix="/t/<tenant_slug>/myfomo",
)


# ── Session helpers ─────────────────────────────────────────────────

_MYFOMO_SESSION_KEYS = [
    "myfomo_user_id", "myfomo_role", "myfomo_username",
    "myfomo_name", "myfomo_tenant",
]


def _clear_myfomo_session():
    for key in _MYFOMO_SESSION_KEYS:
        session.pop(key, None)


def _platform_user_matches_session():
    """Return True if the current platform JWT cookie matches the myfomo session user.

    Only meaningful for follower sessions created via /api/follow (where
    myfomo_username == platform email). Returns True when there is no platform
    token present (direct myfomo login, non-platform user).
    """
    platform_token = request.cookies.get("token")
    if not platform_token:
        return True  # no platform token — direct myfomo login, trust the session
    try:
        payload = pyjwt.decode(
            platform_token, current_app.config["SECRET_KEY"], algorithms=["HS256"]
        )
        return payload.get("email") == session.get("myfomo_username")
    except pyjwt.ExpiredSignatureError:
        return False  # platform session expired — treat as mismatch for followers
    except Exception:
        return True  # unreadable token — don't disturb session


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
    db = get_myfomo_db(tenant_slug)
    user = db.execute("SELECT * FROM users WHERE username=%s AND is_active=1", (email,)).fetchone()
    if not user:
        return False
    session["myfomo_user_id"] = user["id"]
    session["myfomo_role"] = user["role"]
    session["myfomo_username"] = user["username"]
    session["myfomo_name"] = user["name"]
    session["myfomo_tenant"] = tenant_slug
    return True


# ── Auth decorator ──────────────────────────────────────────────────

def login_required(*roles):
    """Require the user to be logged into the myfomo tenant app."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            tenant_slug = kwargs.get("tenant_slug", "")
            if "myfomo_user_id" not in session or session.get("myfomo_tenant") != tenant_slug:
                if not _sso_auto_login(tenant_slug):
                    return redirect("/")
            if roles and session.get("myfomo_role") not in roles:
                return "Unauthorized", 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator


# ── Auth routes ─────────────────────────────────────────────────────

@myfomo_bp.route("/")
def index(tenant_slug):
    # Preserve query string (e.g. ?item=123) through redirects
    qs = request.query_string.decode()
    def _redir(endpoint):
        url = url_for(endpoint, tenant_slug=tenant_slug)
        if qs:
            url += "?" + qs
        return redirect(url)

    if "myfomo_user_id" in session and session.get("myfomo_tenant") == tenant_slug:
        role = session.get("myfomo_role")
        if role == "admin":
            return _redir("myfomo.dashboard")
        return _redir("myfomo.store")
    if _sso_auto_login(tenant_slug):
        role = session.get("myfomo_role")
        if role == "admin":
            return _redir("myfomo.dashboard")
        return _redir("myfomo.store")
    return _redir("myfomo.explore")


@myfomo_bp.route("/explore")
def explore(tenant_slug):
    """Public store view — no login required. Shows published posts with a Follow button."""
    qs = request.query_string.decode()
    def _redir(endpoint):
        url = url_for(endpoint, tenant_slug=tenant_slug)
        if qs:
            url += "?" + qs
        return redirect(url)

    # If already logged in, redirect — but first verify the session belongs to
    # the currently logged-in platform user (guards against stale sessions when
    # a different platform account logs in on the same browser).
    if "myfomo_user_id" in session and session.get("myfomo_tenant") == tenant_slug:
        role = session.get("myfomo_role")
        if role == "admin":
            return _redir("myfomo.dashboard")
        # Follower: cross-check against current platform JWT
        if not _platform_user_matches_session():
            _clear_myfomo_session()
            # Fall through to show the public explore page
        else:
            return _redir("myfomo.store")

    from core.models import Tenant
    tenant_obj = Tenant.query.filter_by(slug=tenant_slug).first()
    business_name = tenant_obj.name if tenant_obj else tenant_slug
    return render_template("myfomo/explore.html", tenant_slug=tenant_slug, business_name=business_name)


@myfomo_bp.route("/api/public/posts", methods=["GET"])
def public_posts(tenant_slug):
    """Return published posts without requiring a session."""
    db = get_myfomo_db(tenant_slug)
    rows = db.execute(
        "SELECT * FROM posts WHERE status='published' ORDER BY id DESC"
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@myfomo_bp.route("/api/follow", methods=["POST"])
def follow(tenant_slug):
    """Auto-register/login a platform user as a follower in this tenant.

    Reads the platform JWT from the Authorization header, looks up the
    platform user, then creates or reuses a follower account in this
    tenant's database and sets a myfomo session cookie.
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return jsonify({"error": "Platform login required"}), 401
    token = auth[7:]

    try:
        payload = pyjwt.decode(
            token, current_app.config["SECRET_KEY"], algorithms=["HS256"]
        )
    except pyjwt.ExpiredSignatureError:
        return jsonify({"error": "Session expired, please log in again"}), 401
    except pyjwt.InvalidTokenError:
        return jsonify({"error": "Invalid token"}), 401

    email = payload.get("email", "")
    user_id = payload.get("user_id")
    if not email:
        return jsonify({"error": "Invalid token"}), 401

    # Resolve display name from the platform user record
    name = email.split("@")[0]
    try:
        from core.models import User as PlatformUser
        from core.extensions import db as platform_db
        platform_user = platform_db.session.get(PlatformUser, user_id)
        if platform_user:
            name = platform_user.name
    except Exception:
        pass

    # Get or create the follower account in this tenant's db
    db = get_myfomo_db(tenant_slug)
    user = db.execute("SELECT * FROM users WHERE username=%s", (email,)).fetchone()
    if not user:
        password_hash = generate_password_hash(secrets.token_hex(16))
        cur_result = db.execute(
            "INSERT INTO users (username, password_hash, name, role, is_active) VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (email, password_hash, name, "follower", 1),
        )
        new_id = cur_result.fetchone()["id"]
        db.commit()
        user = db.execute("SELECT * FROM users WHERE id=%s", (new_id,)).fetchone()

    # Set the myfomo session (same keys the login route uses)
    session["myfomo_user_id"] = user["id"]
    session["myfomo_role"] = user["role"]
    session["myfomo_username"] = user["username"]
    session["myfomo_name"] = user["name"]
    session["myfomo_tenant"] = tenant_slug

    # Record in the platform-level follows index so the home page can find all businesses
    try:
        fdb = get_follows_db()
        fdb.execute(
            "INSERT INTO follows (user_email, tenant_slug) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (email, tenant_slug),
        )
        fdb.commit()
    except Exception:
        pass

    _log_event(db, "follow", entity_name=email)
    return jsonify({"ok": True, "name": user["name"]})


@myfomo_bp.route("/login", methods=["GET", "POST"])
def myfomo_login(tenant_slug):
    if request.method == "GET":
        return render_template("myfomo/login.html", tenant_slug=tenant_slug)

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    if not username or not password:
        return render_template("myfomo/login.html", tenant_slug=tenant_slug, error="Username and password are required")

    db = get_myfomo_db(tenant_slug)
    user = db.execute("SELECT * FROM users WHERE username=%s AND is_active=1", (username,)).fetchone()

    if not user or not check_password_hash(user["password_hash"], password):
        return render_template("myfomo/login.html", tenant_slug=tenant_slug, error="Invalid credentials")

    session["myfomo_user_id"] = user["id"]
    session["myfomo_role"] = user["role"]
    session["myfomo_username"] = user["username"]
    session["myfomo_name"] = user["name"]
    session["myfomo_tenant"] = tenant_slug

    if user["role"] == "admin":
        return redirect(url_for("myfomo.dashboard", tenant_slug=tenant_slug))
    # Also register in the platform follows index (handles manual-password followers)
    try:
        fdb = get_follows_db()
        fdb.execute(
            "INSERT INTO follows (user_email, tenant_slug) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (user["username"], tenant_slug),
        )
        fdb.commit()
    except Exception:
        pass
    return redirect(url_for("myfomo.follower_home", tenant_slug=tenant_slug))


@myfomo_bp.route("/register", methods=["GET", "POST"])
def myfomo_register(tenant_slug):
    if request.method == "GET":
        return render_template("myfomo/register.html", tenant_slug=tenant_slug)

    name = request.form.get("name", "").strip()
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    phone = request.form.get("phone", "").strip()

    if not name or not username or not password:
        return render_template("myfomo/register.html", tenant_slug=tenant_slug, error="Name, username, and password are required")

    db = get_myfomo_db(tenant_slug)
    existing = db.execute("SELECT id FROM users WHERE username=%s", (username,)).fetchone()
    if existing:
        return render_template("myfomo/register.html", tenant_slug=tenant_slug, error="Username already taken")

    password_hash = generate_password_hash(password)
    db.execute(
        "INSERT INTO users (username, password_hash, name, role, phone, is_active) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
        (username, password_hash, name, "follower", phone, 1),
    )
    db.commit()

    # Auto-login after registration
    user = db.execute("SELECT * FROM users WHERE username=%s", (username,)).fetchone()
    session["myfomo_user_id"] = user["id"]
    session["myfomo_role"] = user["role"]
    session["myfomo_username"] = user["username"]
    session["myfomo_name"] = user["name"]
    session["myfomo_tenant"] = tenant_slug

    return redirect(url_for("myfomo.store", tenant_slug=tenant_slug))


@myfomo_bp.route("/logout")
def myfomo_logout(tenant_slug):
    session.pop("myfomo_user_id", None)
    session.pop("myfomo_role", None)
    session.pop("myfomo_username", None)
    session.pop("myfomo_name", None)
    session.pop("myfomo_tenant", None)
    return redirect("/signout")


# ── Dashboard (Owner) ──────────────────────────────────────────────

@myfomo_bp.route("/dashboard")
@login_required("admin")
def dashboard(tenant_slug):
    from core.models import Tenant
    tenant_obj = Tenant.query.filter_by(slug=tenant_slug).first()
    business_name = tenant_obj.name if tenant_obj else tenant_slug
    return render_template(
        "myfomo/dashboard.html",
        tenant_slug=tenant_slug,
        role=session.get("myfomo_role"),
        username=session.get("myfomo_username"),
        name=session.get("myfomo_name"),
        business_name=business_name,
    )


# ── Store (Follower) ──────────────────────────────────────────────

@myfomo_bp.route("/store")
@login_required()
def store(tenant_slug):
    # Guard against stale sessions from a different platform account
    if session.get("myfomo_role") == "follower" and not _platform_user_matches_session():
        _clear_myfomo_session()
        return redirect(url_for("myfomo.explore", tenant_slug=tenant_slug))

    from core.models import Tenant
    tenant_obj = Tenant.query.filter_by(slug=tenant_slug).first()
    business_name = tenant_obj.name if tenant_obj else tenant_slug
    return render_template(
        "myfomo/store.html",
        tenant_slug=tenant_slug,
        role=session.get("myfomo_role"),
        username=session.get("myfomo_username"),
        name=session.get("myfomo_name"),
        business_name=business_name,
    )


# ── Client self-profile ───────────────────────────────────────────

@myfomo_bp.route("/api/my-profile", methods=["GET"])
@login_required()
def get_my_profile(tenant_slug):
    uid = session.get("myfomo_user_id")
    db = get_myfomo_db(tenant_slug)
    user = db.execute("SELECT username, name, phone FROM users WHERE id=%s", (uid,)).fetchone()
    if not user:
        return jsonify({"error": "User not found"}), 404
    return jsonify({"email": user["username"], "name": user["name"] or "", "phone": user["phone"] or ""})


@myfomo_bp.route("/api/my-profile", methods=["PUT"])
@login_required()
def save_my_profile(tenant_slug):
    uid = session.get("myfomo_user_id")
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    phone = data.get("phone", "").strip()
    new_password = data.get("new_password", "").strip()
    current_password = data.get("current_password", "").strip()

    db = get_myfomo_db(tenant_slug)
    user = db.execute("SELECT * FROM users WHERE id=%s", (uid,)).fetchone()
    if not user:
        return jsonify({"error": "User not found"}), 404

    if new_password:
        if not current_password:
            return jsonify({"error": "Current password is required to set a new one"}), 400
        if not check_password_hash(user["password_hash"], current_password):
            return jsonify({"error": "Current password is incorrect"}), 400
        if len(new_password) < 6:
            return jsonify({"error": "New password must be at least 6 characters"}), 400
        pw_hash = generate_password_hash(new_password)
        db.execute("UPDATE users SET name=%s, phone=%s, password_hash=%s WHERE id=%s", (name, phone, pw_hash, uid))
    else:
        db.execute("UPDATE users SET name=%s, phone=%s WHERE id=%s", (name, phone, uid))

    db.commit()
    session["myfomo_name"] = name
    return jsonify({"ok": True, "name": name})


# ── Follower Home (multi-business landing page) ────────────────────

@myfomo_bp.route("/home")
@login_required()
def follower_home(tenant_slug):
    if session.get("myfomo_role") == "follower" and not _platform_user_matches_session():
        _clear_myfomo_session()
        return redirect(url_for("myfomo.explore", tenant_slug=tenant_slug))
    return render_template(
        "myfomo/home.html",
        tenant_slug=tenant_slug,
        name=session.get("myfomo_name"),
    )


@myfomo_bp.route("/switch")
@login_required()
def switch_store(tenant_slug):
    """Switch the active session to this tenant (if the user has an account here)."""
    email = session.get("myfomo_username", "")
    if not email:
        return redirect(url_for("myfomo.myfomo_login", tenant_slug=tenant_slug))
    db = get_myfomo_db(tenant_slug)
    user = db.execute("SELECT * FROM users WHERE username=%s AND is_active=1", (email,)).fetchone()
    if not user:
        return redirect(url_for("myfomo.explore", tenant_slug=tenant_slug))
    session["myfomo_user_id"] = user["id"]
    session["myfomo_role"] = user["role"]
    session["myfomo_username"] = user["username"]
    session["myfomo_name"] = user["name"]
    session["myfomo_tenant"] = tenant_slug
    return redirect(url_for("myfomo.store", tenant_slug=tenant_slug))


@myfomo_bp.route("/api/my-businesses", methods=["GET"])
@login_required()
def my_businesses(tenant_slug):
    """Return all businesses the current user follows, with branding & category."""
    email = session.get("myfomo_username", "")
    if not email:
        return jsonify([])
    try:
        fdb = get_follows_db()
        rows = fdb.execute(
            "SELECT tenant_slug FROM follows WHERE user_email=%s ORDER BY followed_at",
            (email,),
        ).fetchall()
        slugs = [r["tenant_slug"] for r in rows]
    except Exception:
        slugs = [tenant_slug]

    from core.models import Tenant
    result = []
    for slug in slugs:
        try:
            tenant_obj = Tenant.query.filter_by(slug=slug).first()
            biz_name = tenant_obj.name if tenant_obj else slug
            tdb = get_myfomo_db(slug)
            s = tdb.execute("SELECT * FROM store_settings WHERE id=1").fetchone()
            colors = json.loads(s["brand_colors"] or "[]") if s else []
            # Fetch featured published posts for this store
            featured_rows = tdb.execute(
                "SELECT id, title, image_path, price FROM posts WHERE featured=1 AND status='published' ORDER BY id DESC LIMIT 10"
            ).fetchall()
            featured_posts = [dict(r) for r in featured_rows]
            result.append({
                "slug": slug,
                "name": biz_name,
                "tagline": s["business_tagline"] if s else "",
                "logo_path": s["logo_path"] if s else "",
                "category": (s["category"] if s and s["category"] else "general"),
                "brand_colors": colors,
                "featured_posts": featured_posts,
            })
        except Exception:
            pass
    return jsonify(result)


# ── Posts API ──────────────────────────────────────────────────────

@myfomo_bp.route("/api/posts", methods=["GET"])
@login_required()
def list_posts(tenant_slug):
    db = get_myfomo_db(tenant_slug)
    role = session.get("myfomo_role")
    status_filter = request.args.get("status")

    if role == "admin":
        if status_filter:
            rows = db.execute("SELECT * FROM posts WHERE status=%s ORDER BY id DESC", (status_filter,)).fetchall()
        else:
            rows = db.execute("SELECT * FROM posts ORDER BY id DESC").fetchall()
    else:
        # Followers only see published posts
        rows = db.execute("SELECT * FROM posts WHERE status='published' ORDER BY id DESC").fetchall()

    return jsonify([dict(r) for r in rows])


@myfomo_bp.route("/api/posts", methods=["POST"])
@login_required("admin")
def create_post(tenant_slug):
    data = request.get_json() or {}
    title = data.get("title", "").strip()
    if not title:
        return jsonify({"error": "Title is required"}), 400

    db = get_myfomo_db(tenant_slug)
    original_qty = int(data.get("original_quantity", 0))
    cur_result = db.execute(
        """INSERT INTO posts (title, body, image_path, original_image_path, post_type, price,
           original_quantity, remaining_quantity, sale_ends_at, status, ai_generated, featured)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (title, data.get("body", ""), data.get("image_path", ""),
         data.get("original_image_path", ""),
         data.get("post_type", "product"), data.get("price", 0.0),
         original_qty, original_qty,
         data.get("sale_ends_at"), data.get("status", "draft"),
         1 if data.get("ai_generated") else 0,
         1 if data.get("featured") else 0),
    )
    new_id = cur_result.fetchone()["id"]
    db.commit()
    return jsonify({"message": "Post created", "id": new_id}), 201


@myfomo_bp.route("/api/posts/<int:post_id>", methods=["PUT"])
@login_required("admin")
def update_post(tenant_slug, post_id):
    data = request.get_json() or {}
    db = get_myfomo_db(tenant_slug)
    existing = db.execute("SELECT * FROM posts WHERE id=%s", (post_id,)).fetchone()
    if not existing:
        return jsonify({"error": "Post not found"}), 404

    db.execute(
        """UPDATE posts SET title=%s, body=%s, image_path=%s, original_image_path=%s,
           post_type=%s, price=%s,
           original_quantity=%s, remaining_quantity=%s, sale_ends_at=%s, status=%s, ai_generated=%s, featured=%s
           WHERE id=%s""",
        (data.get("title", existing["title"]),
         data.get("body", existing["body"]),
         data.get("image_path", existing["image_path"]),
         data.get("original_image_path", existing["original_image_path"]),
         data.get("post_type", existing["post_type"]),
         data.get("price", existing["price"]),
         data.get("original_quantity", existing["original_quantity"]),
         data.get("remaining_quantity", existing["remaining_quantity"]),
         data.get("sale_ends_at", existing["sale_ends_at"]),
         data.get("status", existing["status"]),
         1 if data.get("ai_generated", existing["ai_generated"]) else 0,
         1 if data.get("featured", existing.get("featured", 0)) else 0,
         post_id),
    )
    db.commit()
    return jsonify({"message": "Post updated"})


@myfomo_bp.route("/api/posts/<int:post_id>", methods=["DELETE"])
@login_required("admin")
def delete_post(tenant_slug, post_id):
    db = get_myfomo_db(tenant_slug)
    with db.transaction():
        db.execute("DELETE FROM bookings WHERE post_id=%s", (post_id,))
        db.execute("DELETE FROM posts WHERE id=%s", (post_id,))
    return jsonify({"message": "Post deleted"})


# ── Events API ─────────────────────────────────────────────────────

@myfomo_bp.route("/api/events", methods=["GET"])
@login_required()
def list_events(tenant_slug):
    db = get_myfomo_db(tenant_slug)
    rows = db.execute("SELECT * FROM events ORDER BY event_date DESC, id DESC").fetchall()
    return jsonify([dict(r) for r in rows])


@myfomo_bp.route("/api/events", methods=["POST"])
@login_required("admin")
def create_event(tenant_slug):
    data = request.get_json() or {}
    title = data.get("title", "").strip()
    if not title:
        return jsonify({"error": "Title is required"}), 400

    db = get_myfomo_db(tenant_slug)
    cur_result = db.execute(
        """INSERT INTO events (title, description, image_path, event_date, event_time, location, status, ai_generated)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (title, data.get("description", ""), data.get("image_path", ""),
         data.get("event_date"), data.get("event_time"),
         data.get("location", ""), data.get("status", "upcoming"),
         1 if data.get("ai_generated") else 0),
    )
    new_id = cur_result.fetchone()["id"]
    db.commit()
    return jsonify({"message": "Event created", "id": new_id}), 201


@myfomo_bp.route("/api/events/<int:event_id>", methods=["PUT"])
@login_required("admin")
def update_event(tenant_slug, event_id):
    data = request.get_json() or {}
    db = get_myfomo_db(tenant_slug)
    existing = db.execute("SELECT * FROM events WHERE id=%s", (event_id,)).fetchone()
    if not existing:
        return jsonify({"error": "Event not found"}), 404

    db.execute(
        """UPDATE events SET title=%s, description=%s, image_path=%s, event_date=%s,
           event_time=%s, location=%s, status=%s, ai_generated=%s WHERE id=%s""",
        (data.get("title", existing["title"]),
         data.get("description", existing["description"]),
         data.get("image_path", existing["image_path"]),
         data.get("event_date", existing["event_date"]),
         data.get("event_time", existing["event_time"]),
         data.get("location", existing["location"]),
         data.get("status", existing["status"]),
         1 if data.get("ai_generated", existing["ai_generated"]) else 0,
         event_id),
    )
    db.commit()
    return jsonify({"message": "Event updated"})


@myfomo_bp.route("/api/events/<int:event_id>", methods=["DELETE"])
@login_required("admin")
def delete_event(tenant_slug, event_id):
    db = get_myfomo_db(tenant_slug)
    db.execute("DELETE FROM events WHERE id=%s", (event_id,))
    db.commit()
    return jsonify({"message": "Event deleted"})


# ── Bookings API ───────────────────────────────────────────────────

@myfomo_bp.route("/api/bookings", methods=["GET"])
@login_required()
def list_bookings(tenant_slug):
    db = get_myfomo_db(tenant_slug)
    role = session.get("myfomo_role")

    if role == "admin":
        rows = db.execute(
            """SELECT b.*, u.name AS user_name, u.username AS user_username, p.title AS post_title
               FROM bookings b
               LEFT JOIN users u ON b.user_id = u.id
               LEFT JOIN posts p ON b.post_id = p.id
               ORDER BY b.id DESC"""
        ).fetchall()
    else:
        user_id = session.get("myfomo_user_id")
        rows = db.execute(
            """SELECT b.*, p.title AS post_title, p.image_path AS post_image
               FROM bookings b
               LEFT JOIN posts p ON b.post_id = p.id
               WHERE b.user_id=%s
               ORDER BY b.id DESC""",
            (user_id,),
        ).fetchall()

    return jsonify([dict(r) for r in rows])


@myfomo_bp.route("/api/bookings", methods=["POST"])
@login_required("follower")
def create_booking(tenant_slug):
    data = request.get_json() or {}
    post_id = data.get("post_id")
    quantity = int(data.get("quantity", 1))

    if not post_id or quantity < 1:
        return jsonify({"error": "Valid post_id and quantity required"}), 400

    db = get_myfomo_db(tenant_slug)
    post = db.execute("SELECT * FROM posts WHERE id=%s AND status='published'", (post_id,)).fetchone()
    if not post:
        return jsonify({"error": "Post not found or not available"}), 404

    if post["remaining_quantity"] < quantity:
        return jsonify({"error": "Not enough stock available"}), 400

    user_id = session.get("myfomo_user_id")
    db.execute(
        "INSERT INTO bookings (post_id, user_id, quantity, status, notes) VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (post_id, user_id, quantity, "pending", data.get("notes", "")),
    )
    db.execute(
        "UPDATE posts SET remaining_quantity = remaining_quantity - %s WHERE id=%s",
        (quantity, post_id),
    )
    db.commit()
    _log_event(db, "booking", entity_id=post_id, entity_name=post["title"],
               metadata={"quantity": quantity})
    return jsonify({"message": "Booking created"}), 201


@myfomo_bp.route("/api/bookings/<int:booking_id>", methods=["PUT"])
@login_required("admin")
def update_booking(tenant_slug, booking_id):
    data = request.get_json() or {}
    new_status = data.get("status")
    if not new_status:
        return jsonify({"error": "Status is required"}), 400

    db = get_myfomo_db(tenant_slug)
    existing = db.execute("SELECT * FROM bookings WHERE id=%s", (booking_id,)).fetchone()
    if not existing:
        return jsonify({"error": "Booking not found"}), 404

    # If cancelling, restore stock
    if new_status == "cancelled" and existing["status"] != "cancelled":
        db.execute(
            "UPDATE posts SET remaining_quantity = remaining_quantity + %s WHERE id=%s",
            (existing["quantity"], existing["post_id"]),
        )

    db.execute("UPDATE bookings SET status=%s WHERE id=%s", (new_status, booking_id))
    db.commit()
    return jsonify({"message": "Booking updated"})


# ── AI API ─────────────────────────────────────────────────────────

@myfomo_bp.route("/api/ai/analyze-image", methods=["POST"])
@login_required("admin")
def ai_analyze_image(tenant_slug):
    if "image" not in request.files:
        return jsonify({"error": "No image file provided"}), 400
    file = request.files["image"]
    image_bytes = file.read()
    language = request.form.get("language", request.args.get("language", "en"))
    result = analyze_image(image_bytes, language=language)
    return jsonify(result)


@myfomo_bp.route("/api/ai/generate-copy", methods=["POST"])
@login_required("admin")
def ai_generate_copy(tenant_slug):
    data = request.get_json() or {}
    result = generate_ad_copy(
        data,
        tone=data.get("tone", "engaging"),
        language=data.get("language", "en"),
    )
    return jsonify(result)


@myfomo_bp.route("/api/ai/generate-event", methods=["POST"])
@login_required("admin")
def ai_generate_event(tenant_slug):
    data = request.get_json() or {}
    result = generate_event_description(data)
    return jsonify(result)


@myfomo_bp.route("/api/ai/generate-text-overlay", methods=["POST"])
@login_required("admin")
def ai_generate_text_overlay(tenant_slug):
    data = request.get_json() or {}
    result = generate_ad_text_overlay(
        data,
        tone=data.get("tone", "engaging"),
        language=data.get("language", "en"),
    )
    return jsonify(result)


@myfomo_bp.route("/api/ai/generate-ad-image", methods=["POST"])
@login_required("admin")
def ai_generate_ad_image(tenant_slug):
    if "image" not in request.files:
        return jsonify({"error": "No image file provided"}), 400
    file = request.files["image"]
    image_bytes = file.read()
    product_name = request.form.get("product_name", "")
    style = request.form.get("style", "promotional")

    # ── Load store settings once ──────────────────────────────────
    brand_colors, brand_style, brand_mood, market_audience = [], "", "", ""
    settings = None
    try:
        db = get_myfomo_db(tenant_slug)
        settings = db.execute("SELECT * FROM store_settings WHERE id=1").fetchone()
        if settings:
            if settings["logo_path"]:
                brand_colors = json.loads(settings["brand_colors"] or "[]")
                brand_style = settings["brand_style"] or ""
                brand_mood = settings["mood"] or ""
            market_audience = settings["market_audience"] or ""
    except Exception:
        pass

    # ── Restrict brand colors to brand mode only ──────────────────
    # Brand colors are loaded above but should only influence the prompt when
    # the user explicitly chose "Brand Colors" mode. For every other mode,
    # clear them so generate_ad_image doesn't weave them into the prompt.
    bg_mode = request.form.get("background_mode", "basic")
    if bg_mode != "brand":
        brand_colors = []
        # Keep brand_style / brand_mood cleared too — they describe visual feel
        # which should not override the user's chosen background direction.
        brand_style = ""
        brand_mood = ""

    # ── Background detail level ───────────────────────────────────
    _detail_map = {
        "1": "very minimal and clean — almost plain, barely any texture or elements",
        "2": "simple and uncluttered — light background with subtle accents",
        "3": "moderately detailed — balanced composition with supporting elements",
        "4": "richly detailed — multiple visual layers, textures, and supporting elements",
        "5": "highly intricate and elaborate — complex patterns, rich layering, and fine detail throughout",
    }
    detail_desc = _detail_map.get(request.form.get("background_detail", "3"), _detail_map["3"])

    # ── Background ────────────────────────────────────────────────
    if bg_mode == "brand":
        if brand_colors:
            color_str = ", ".join(brand_colors[:3])
            background_text = (
                f"background built around the brand palette ({color_str}), "
                f"creating a cohesive, on-brand environment; {detail_desc}"
            )
        else:
            background_text = detail_desc
    elif bg_mode == "audience":
        if market_audience:
            background_text = (
                f"background and overall aesthetic that strongly resonates with "
                f"{market_audience} — use cultural references, colors, and design "
                f"elements that feel authentic and appealing to this audience; {detail_desc}"
            )
        else:
            background_text = f"background that appeals to a broad, diverse audience; {detail_desc}"
    elif bg_mode == "custom":
        custom = request.form.get("background_custom", "")
        background_text = f"{custom}; {detail_desc}" if custom else detail_desc
    else:  # basic — infer a contextually appropriate real-world environment for the product
        background_text = (
            f"contextually appropriate background that naturally suits the product — "
            f"look at the product in the photo and infer the real-world environment where it is "
            f"typically found, used, or sold (for example: a kitchen or dining scene for food and "
            f"beverages, a retail or fashion setting for clothing and accessories, an outdoor or "
            f"sports environment for athletic gear, a tech desk setup for electronics, a beauty "
            f"counter for cosmetics); use a setting that feels authentic and enhances the product "
            f"naturally — avoid abstract patterns, decorative motifs, or generic studio gradients; "
            f"{detail_desc}"
        )

    # ── Text overlay ──────────────────────────────────────────────
    text_content = request.form.get("text_content", "").strip()
    overlay_text = ""
    if text_content:
        placement_map = {
            "top":    "at the top of the image",
            "center": "centered in the middle of the image",
            "bottom": "at the bottom of the image",
        }
        size_map = {
            "small":  "small and subtle",
            "medium": "medium-sized, clearly legible",
            "large":  "large and dominant",
        }
        effect_map = {
            "none":    "",
            "shadow":  "with a strong drop shadow for depth",
            "outline": "with a bold stroke/outline so it pops off the background",
            "neon":    "with a vivid neon glow effect — electric and eye-catching",
            "vintage": "styled as a vintage stamp or badge with distressed texture",
        }
        placement = placement_map.get(request.form.get("text_placement", "bottom"),
                                      "at the bottom of the image")
        size     = size_map.get(request.form.get("text_size", "medium"), "medium-sized, clearly legible")
        effect   = effect_map.get(request.form.get("text_effect", "none"), "")
        overlay_text = (
            f'"{text_content}" — place it {placement}, {size}'
            f'{", " + effect if effect else ""}'
        )

    # ── Frame ─────────────────────────────────────────────────────
    if request.form.get("add_frame") == "true":
        frame_desc = (
            "Add a decorative frame or border around the entire image. "
            "The frame style should harmonize with and be inspired by the background "
            "choice — e.g. ornate for ethnic/cultural themes, clean geometric for brand "
            "colors, rustic for vintage text effects."
        )
        background_text = (background_text + " " + frame_desc).strip() if background_text else frame_desc

    result = generate_ad_image(image_bytes, product_name=product_name, style=style,
                               background_text=background_text, overlay_text=overlay_text,
                               brand_colors=brand_colors, brand_style=brand_style,
                               brand_mood=brand_mood)
    if "error" in result:
        return jsonify(result), 500

    import base64 as b64mod
    upload_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "static", "uploads", "myfomo", tenant_slug,
    )
    os.makedirs(upload_dir, exist_ok=True)

    urls = []
    for img in result.get("images", []):
        if "image_base64" in img:
            img_data = b64mod.b64decode(img["image_base64"])
            ext = ".png" if "png" in img.get("mime_type", "") else ".jpg"
            fname = f"{uuid.uuid4().hex}{ext}"
        else:
            req = urllib.request.Request(img["image_url"])
            with urllib.request.urlopen(req, timeout=30) as resp:
                img_data = resp.read()
            fname = f"{uuid.uuid4().hex}.png"
        with open(os.path.join(upload_dir, fname), "wb") as f:
            f.write(img_data)
        urls.append(f"/static/uploads/myfomo/{tenant_slug}/{fname}")

    if not urls:
        return jsonify({"error": "No images could be saved"}), 500

    # Log AI generation cost (n images × cost per image)
    db = get_myfomo_db(tenant_slug)
    _log_event(db, "ai_generation",
               entity_name=product_name or "unnamed",
               metadata={"cost": round(len(urls) * _GPT_IMAGE_COST, 4), "images": len(urls)})

    return jsonify({"urls": urls}), 201


# Cost per image for gpt-image-1 at 1024×1024 (approximate)
_GPT_IMAGE_COST = 0.04


def _log_event(db, event_type, entity_id=None, entity_name="", metadata=None):
    """Insert an analytics event — fire-and-forget, never raises."""
    try:
        db.execute(
            "INSERT INTO analytics_events (event_type, entity_id, entity_name, metadata) VALUES (%s, %s, %s, %s)",
            (event_type, entity_id, entity_name, json.dumps(metadata or {})),
        )
        db.commit()
    except Exception:
        pass


# ── Analytics ──────────────────────────────────────────────────────

@myfomo_bp.route("/api/analytics/track", methods=["POST"])
def track_event(tenant_slug):
    """Public event tracking endpoint called from client JS."""
    data = request.get_json() or {}
    event_type = data.get("event_type", "").strip()
    if not event_type:
        return jsonify({"ok": False}), 400
    db = get_myfomo_db(tenant_slug)
    _log_event(db, event_type,
               entity_id=data.get("entity_id"),
               entity_name=data.get("entity_name", ""),
               metadata=data.get("metadata", {}))
    return jsonify({"ok": True})


@myfomo_bp.route("/api/analytics", methods=["GET"])
@login_required("admin")
def get_analytics(tenant_slug):
    """Aggregated analytics for the admin dashboard."""
    db = get_myfomo_db(tenant_slug)

    followers = db.execute(
        "SELECT COUNT(*) as c FROM users WHERE role='follower'"
    ).fetchone()["c"]

    total_bookings = db.execute("SELECT COUNT(*) as c FROM bookings").fetchone()["c"]
    booking_statuses = db.execute(
        "SELECT status, COUNT(*) as c FROM bookings GROUP BY status"
    ).fetchall()

    page_views = db.execute(
        "SELECT COUNT(*) as c FROM analytics_events WHERE event_type='page_view'"
    ).fetchone()["c"]

    item_views = db.execute(
        "SELECT COUNT(*) as c FROM analytics_events WHERE event_type='item_view'"
    ).fetchone()["c"]

    ai_count = db.execute(
        "SELECT COUNT(*) as c FROM analytics_events WHERE event_type='ai_generation'"
    ).fetchone()["c"]

    ai_cost = sum(
        json.loads(r["metadata"] or "{}").get("cost", 0.0)
        for r in db.execute(
            "SELECT metadata FROM analytics_events WHERE event_type='ai_generation'"
        ).fetchall()
    )

    top_items = db.execute(
        """SELECT entity_id, entity_name, COUNT(*) as views
           FROM analytics_events WHERE event_type='item_view' AND entity_id IS NOT NULL
           GROUP BY entity_id, entity_name ORDER BY views DESC LIMIT 5"""
    ).fetchall()

    ai_per_post = db.execute(
        """SELECT entity_id, entity_name, COUNT(*) as gens,
           COALESCE(SUM((metadata::json->>'cost')::float), 0) as cost
           FROM analytics_events WHERE event_type='ai_generation' AND entity_id IS NOT NULL
           GROUP BY entity_id, entity_name ORDER BY gens DESC"""
    ).fetchall()

    recent = db.execute(
        "SELECT event_type, entity_name, created_at FROM analytics_events ORDER BY id DESC LIMIT 20"
    ).fetchall()

    return jsonify({
        "followers": followers,
        "total_bookings": total_bookings,
        "booking_statuses": [{"status": r["status"], "count": r["c"]} for r in booking_statuses],
        "page_views": page_views,
        "item_views": item_views,
        "ai_generations": ai_count,
        "estimated_ai_cost": round(ai_cost, 4),
        "top_items": [{"id": r["entity_id"], "name": r["entity_name"], "views": r["views"]} for r in top_items],
        "ai_per_post": [{"title": r["entity_name"], "gens": r["gens"], "cost": round(r["cost"] or 0, 4)} for r in ai_per_post],
        "recent_events": [{"type": r["event_type"], "name": r["entity_name"] or "—", "at": str(r["created_at"] or "")} for r in recent],
    })


# ── Branding ───────────────────────────────────────────────────────

@myfomo_bp.route("/api/branding", methods=["GET"])
@login_required("admin")
def get_branding(tenant_slug):
    """Return the current store branding settings."""
    db = get_myfomo_db(tenant_slug)
    row = db.execute("SELECT * FROM store_settings WHERE id=1").fetchone()
    if not row:
        return jsonify({"logo_path": "", "brand_colors": [], "brand_style": "", "font_style": "", "mood": ""})
    return jsonify({
        "logo_path": row["logo_path"],
        "brand_colors": json.loads(row["brand_colors"] or "[]"),
        "brand_style": row["brand_style"],
        "font_style": row["font_style"],
        "mood": row["mood"],
    })


@myfomo_bp.route("/api/branding/logo", methods=["POST"])
@login_required("admin")
def upload_logo(tenant_slug):
    """Upload a logo, extract brand identity, and save to store settings."""
    if "logo" not in request.files:
        return jsonify({"error": "No logo file provided"}), 400
    file = request.files["logo"]
    image_bytes = file.read()

    # Save the logo file
    ext = os.path.splitext(secure_filename(file.filename))[1] or ".png"
    filename = f"logo{ext}"
    upload_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "static", "uploads", "myfomo", tenant_slug,
    )
    os.makedirs(upload_dir, exist_ok=True)
    with open(os.path.join(upload_dir, filename), "wb") as f:
        f.write(image_bytes)
    logo_path = f"/static/uploads/myfomo/{tenant_slug}/{filename}"

    # Analyze brand identity
    brand = analyze_logo(image_bytes)

    # Upsert into store_settings (id=1 is the single settings row)
    db = get_myfomo_db(tenant_slug)
    existing = db.execute("SELECT id FROM store_settings WHERE id=1").fetchone()
    if existing:
        db.execute(
            """UPDATE store_settings SET logo_path=%s, brand_colors=%s, brand_style=%s,
               font_style=%s, mood=%s, updated_at=NOW() WHERE id=1""",
            (logo_path, json.dumps(brand.get("colors", [])),
             brand.get("style", ""), brand.get("font_style", ""), brand.get("mood", "")),
        )
    else:
        db.execute(
            """INSERT INTO store_settings (id, logo_path, brand_colors, brand_style, font_style, mood)
               VALUES (1, %s, %s, %s, %s, %s)""",
            (logo_path, json.dumps(brand.get("colors", [])),
             brand.get("style", ""), brand.get("font_style", ""), brand.get("mood", "")),
        )
    db.commit()

    return jsonify({
        "logo_path": logo_path,
        "brand_colors": brand.get("colors", []),
        "brand_style": brand.get("style", ""),
        "font_style": brand.get("font_style", ""),
        "mood": brand.get("mood", ""),
    }), 201


# ── Business Profile ───────────────────────────────────────────────

@myfomo_bp.route("/api/profile", methods=["GET"])
def get_profile(tenant_slug):
    """Return public business profile info (no auth required)."""
    db = get_myfomo_db(tenant_slug)
    row = db.execute("SELECT * FROM store_settings WHERE id=1").fetchone()
    if not row:
        return jsonify({})
    return jsonify({
        "logo_path": row["logo_path"] or "",
        "business_tagline": row["business_tagline"] or "",
        "business_phone": row["business_phone"] or "",
        "business_email": row["business_email"] or "",
        "business_address": row["business_address"] or "",
        "business_website": row["business_website"] or "",
        "business_hours": row["business_hours"] or "",
        "social_instagram": row["social_instagram"] or "",
        "social_facebook": row["social_facebook"] or "",
        "social_twitter": row["social_twitter"] or "",
        "social_tiktok": row["social_tiktok"] or "",
        "social_whatsapp": row["social_whatsapp"] or "",
        "market_audience": row["market_audience"] or "",
        "brand_colors": json.loads(row["brand_colors"] or "[]"),
        "brand_style": row["brand_style"] or "",
        "font_style": row["font_style"] or "",
        "mood": row["mood"] or "",
        "category": row["category"] or "general",
    })


@myfomo_bp.route("/api/profile", methods=["POST"])
@login_required("admin")
def save_profile(tenant_slug):
    """Save business profile info."""
    data = request.get_json() or {}
    db = get_myfomo_db(tenant_slug)
    existing = db.execute("SELECT id FROM store_settings WHERE id=1").fetchone()
    vals = (
        data.get("business_tagline", ""),
        data.get("business_phone", ""),
        data.get("business_email", ""),
        data.get("business_address", ""),
        data.get("business_website", ""),
        data.get("business_hours", ""),
        data.get("social_instagram", ""),
        data.get("social_facebook", ""),
        data.get("social_twitter", ""),
        data.get("social_tiktok", ""),
        data.get("social_whatsapp", ""),
        data.get("market_audience", ""),
        data.get("category", "general"),
    )
    if existing:
        db.execute(
            """UPDATE store_settings SET
               business_tagline=?, business_phone=?, business_email=?,
               business_address=?, business_website=?, business_hours=?,
               social_instagram=?, social_facebook=?, social_twitter=?,
               social_tiktok=?, social_whatsapp=?, market_audience=?, category=?,
               updated_at=NOW()
               WHERE id=1""",
            vals,
        )
    else:
        db.execute(
            """INSERT INTO store_settings
               (id, business_tagline, business_phone, business_email,
                business_address, business_website, business_hours,
                social_instagram, social_facebook, social_twitter,
                social_tiktok, social_whatsapp, market_audience, category)
               VALUES (1, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            vals,
        )
    db.commit()
    return jsonify({"ok": True})


# ── Image Upload ───────────────────────────────────────────────────

@myfomo_bp.route("/api/upload", methods=["POST"])
@login_required("admin")
def upload_image(tenant_slug):
    if "image" not in request.files:
        return jsonify({"error": "No image file provided"}), 400

    file = request.files["image"]
    if not file.filename:
        return jsonify({"error": "No file selected"}), 400

    ext = os.path.splitext(secure_filename(file.filename))[1] or ".jpg"
    filename = f"{uuid.uuid4().hex}{ext}"

    upload_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "static", "uploads", "myfomo", tenant_slug,
    )
    os.makedirs(upload_dir, exist_ok=True)

    filepath = os.path.join(upload_dir, filename)
    file.save(filepath)

    image_url = f"/static/uploads/myfomo/{tenant_slug}/{filename}"
    return jsonify({"url": image_url}), 201
